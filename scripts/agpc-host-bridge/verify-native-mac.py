#!/usr/bin/env python3
"""Mac CI: native official App-Server handshake, isolated state, no model/API call."""
import hashlib
import json
import os
from pathlib import Path
import platform
import selectors
import subprocess
import tarfile
import tempfile
import time

VERSION = '0.155.0'
URL = 'https://github.com/openai/codex/releases/download/rust-v0.155.0/codex-package-aarch64-apple-darwin.tar.gz'
SHA256 = 'b1411ec00ac410467e05cf8fb5b063cf83632613530201cd4724ef8dd0e9c33f'


def main():
    assert platform.system() == 'Darwin' and platform.machine() == 'arm64'
    assert os.getuid() != 0
    with tempfile.TemporaryDirectory(prefix='agpc-native-codex-') as temporary:
        root = Path(temporary)
        archive = root / 'codex.tar.gz'
        subprocess.run(['curl', '-fsSL', '--proto', '=https', '--proto-redir', '=https',
                        '--max-time', '180', URL, '-o', str(archive)], check=True)
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == SHA256
        with tarfile.open(archive) as bundle:
            bundle.extractall(root / 'package', filter='data')
        binary = root / 'package/bin/codex'
        subprocess.run(['codesign', '--verify', '--strict', str(binary)], check=True)
        version = subprocess.check_output([str(binary), '--version'], text=True).strip()
        assert VERSION in version, version
        home = root / 'state'
        home.mkdir(mode=0o700)
        # No inherited auth variables or existing user Codex state.
        environment = {'HOME': str(root), 'CODEX_HOME': str(home),
                       'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'TMPDIR': temporary}
        with (root / 'stderr.log').open('w+') as errors:
            proc = subprocess.Popen([str(binary), 'app-server', '--listen', 'stdio://'],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                                    cwd=root, env=environment)
            try:
                request = {'id': 1, 'method': 'initialize', 'params': {
                    'clientInfo': {'name': 'agpc_host_probe', 'version': '0.1.0'}}}
                proc.stdin.write(json.dumps(request).encode() + b'\n')
                proc.stdin.flush()
                buffer = bytearray()
                response = None
                deadline = time.monotonic() + 20
                with selectors.DefaultSelector() as events:
                    events.register(proc.stdout, selectors.EVENT_READ)
                    while response is None:
                        if not events.select(max(0, deadline - time.monotonic())):
                            raise RuntimeError('native initialize response timed out')
                        chunk = os.read(proc.stdout.fileno(), 65536)
                        if not chunk:
                            errors.seek(0)
                            raise RuntimeError('native App-Server closed: ' + errors.read()[-2000:])
                        buffer.extend(chunk)
                        while b'\n' in buffer:
                            line, _, tail = buffer.partition(b'\n')
                            buffer = bytearray(tail)
                            item = json.loads(line)
                            if item.get('id') == 1:
                                response = item
                result = response['result']
                assert result['platformOs'] in ('macos', 'darwin'), result
                proc.stdin.write(b'{"method":"initialized","params":{}}\n')
                proc.stdin.flush()
                proc.stdin.close()
                assert proc.wait(timeout=20) == 0
                print(json.dumps({'native_app_server': 'passed', 'codex_version': version,
                                  'host_os': result['platformOs'], 'host_uid': os.getuid(),
                                  'model_calls': 0, 'docker_on_mac_acceptance': False}))
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                proc.stdin.close()
                proc.stdout.close()


if __name__ == '__main__':
    main()
