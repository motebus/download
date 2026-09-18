"""Component-only transport tests with fake protocol endpoints; no Codex login."""
import json
import os
from pathlib import Path
import selectors
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / 'scripts/agpc-host-bridge/codex-stream.py'
HOST = ROOT / 'scripts/agpc-host-bridge/mac-codex-session.sh'


def read_exact(pipe, count, timeout=10):
    result = bytearray()
    deadline = time.monotonic() + timeout
    with selectors.DefaultSelector() as poll:
        poll.register(pipe, selectors.EVENT_READ)
        while len(result) < count:
            if not poll.select(max(0, deadline - time.monotonic())):
                raise AssertionError('timed out receiving bridge output')
            chunk = os.read(pipe.fileno(), count - len(result))
            if not chunk:
                raise AssertionError('bridge closed early')
            result.extend(chunk)
    return bytes(result)


@unittest.skipUnless(sys.platform == 'linux', 'container bridge uses Linux peer credentials')
class StreamTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'private' / 'stdio.sock'
        self.children = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
            for pipe in (child.stdin, child.stdout, child.stderr):
                pipe.close()

    def start(self, mode, timeout=2):
        child = subprocess.Popen([sys.executable, str(BRIDGE), mode, '--socket', str(self.path),
                                  '--timeout', str(timeout)], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.children.append(child)
        return child

    def pair(self):
        server = self.start('serve')
        client = self.start('app-server')
        return server, client

    def test_requests_approvals_notifications_and_half_close(self):
        server, client = self.pair()
        for sender, receiver, value in (
            (client, server, {'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'fixture'}}}),
            (server, client, {'id': 1, 'result': {'platformOs': 'macos'}}),
            (server, client, {'id': 20, 'method': 'item/commandExecution/requestApproval', 'params': {}}),
            (client, server, {'id': 20, 'result': {'decision': 'decline'}}),
            (server, client, {'method': 'turn/completed', 'params': {}}),
        ):
            payload = json.dumps(value).encode() + b'\n'
            sender.stdin.write(payload)
            sender.stdin.flush()
            self.assertEqual(read_exact(receiver.stdout, len(payload)), payload)
        # CX closes its input; host sees EOF but may still emit a final response.
        client.stdin.close()
        self.assertEqual(server.stdout.read(), b'')
        server.stdin.write(b'final-response\n'); server.stdin.flush()
        self.assertEqual(read_exact(client.stdout, 15), b'final-response\n')
        server.stdin.close()
        self.assertEqual(server.wait(timeout=5), 0, server.stderr.read())
        self.assertEqual(client.wait(timeout=5), 0, client.stderr.read())
        self.assertFalse(self.path.exists())

    def test_large_stream_with_backpressure(self):
        import threading
        server, client = self.pair()
        payload = (b'x' * 1023 + b'\n') * 2048
        writer = threading.Thread(target=lambda: (client.stdin.write(payload), client.stdin.flush()), daemon=True)
        writer.start()
        self.assertEqual(read_exact(server.stdout, len(payload)), payload)
        writer.join(timeout=5)
        self.assertFalse(writer.is_alive())

    def test_missing_host_fails_without_stdout(self):
        client = self.start('app-server', .2)
        self.assertEqual(client.wait(timeout=3), 1)
        self.assertEqual(client.stdout.read(), b'')
        self.assertIn(b'unavailable', client.stderr.read())

    def test_duplicate_listener_preserves_first_socket(self):
        server = self.start('serve')
        deadline = time.monotonic() + 2
        while not self.path.exists():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.01)
        inode = self.path.stat().st_ino
        duplicate = self.start('serve')
        self.assertEqual(duplicate.wait(timeout=2), 1)
        self.assertEqual(self.path.stat().st_ino, inode)
        self.assertIsNone(server.poll())

    def test_non_socket_and_insecure_directory_are_preserved(self):
        self.path.parent.mkdir(mode=0o700)
        self.path.write_text('preserve')
        server = self.start('serve')
        self.assertEqual(server.wait(timeout=2), 1)
        self.assertEqual(self.path.read_text(), 'preserve')
        self.path.parent.chmod(0o755)
        server = self.start('serve')
        self.assertEqual(server.wait(timeout=2), 1)
        self.assertIn(b'0700', server.stderr.read())

    def test_host_disconnect_terminates_client(self):
        server, client = self.pair()
        client.stdin.write(b'connected\n'); client.stdin.flush()
        self.assertEqual(read_exact(server.stdout, 10), b'connected\n')
        server.terminate()
        self.assertEqual(server.wait(timeout=3), 143)
        self.assertEqual(client.wait(timeout=3), 0)


class ConfigurationTests(unittest.TestCase):
    def test_only_backend_command_and_args_change(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('configure_cx', ROOT / 'scripts/agpc-host-bridge/configure-cx.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original = ('[node]\nname = "preserve"\n[codex]\nbackend = "app-server"\n'
                    'mode = "managed"\ncommand = "/usr/lib/chatgpt/resources/codex"\n'
                    'args = ["app-server", "--listen", "stdio://"]\n'
                    '[exec]\ncommand = "/usr/bin/cx-exec"\n')
        updated = module.configure(original)
        self.assertIn('name = "preserve"', updated)
        self.assertIn(f'command = "{module.COMMAND}"', updated)
        self.assertEqual(module.configure(updated), updated)
        with self.assertRaises(ValueError):
            module.configure(original.replace('mode = "managed"', 'mode = "external"'))


class HostScriptTests(unittest.TestCase):
    def test_source_is_inert(self):
        result = subprocess.run(['/bin/bash', '-c', 'source "$1"', 'fixture', str(HOST)], capture_output=True)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b'', b''))

    def test_host_only_guard(self):
        result = subprocess.run(['/bin/bash', str(HOST), '/missing/codex', '0' * 64, '/'], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')

    def test_supervisor_term_cleans_children_and_fifos(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            paths = []
            for name in ('codex', 'docker'):
                executable = directory / name
                executable.write_text('#!/bin/bash\nprintf "%s" "$$" > "$PID_DIR/' + name + '.pid"\nexec sleep 60\n')
                executable.chmod(0o700)
                paths.append(str(executable))
            supervisor = subprocess.Popen(['/bin/bash', '-c',
                'source "$1"; CODEX=$2; DOCKER=$3; CONTAINER=fixture; TMPDIR=$4; run_session',
                'fixture', str(HOST), *paths, temporary], env=dict(os.environ, PID_DIR=temporary),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 3
                while not all((directory / (name + '.pid')).exists() for name in ('codex', 'docker')):
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(.01)
                pids = [int((directory / (name + '.pid')).read_text()) for name in ('codex', 'docker')]
                supervisor.terminate()
                self.assertEqual(supervisor.wait(timeout=12), 143)
                for pid in pids:
                    with self.assertRaises(ProcessLookupError):
                        os.kill(pid, 0)
                self.assertFalse(list(directory.glob('agpc-codex.*')))
            finally:
                if supervisor.poll() is None:
                    supervisor.kill()
                supervisor.wait(timeout=3)
                supervisor.stdout.close(); supervisor.stderr.close()

    def test_fifo_lifecycle_with_fake_endpoints(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            codex = directory / 'codex'
            docker = directory / 'docker'
            codex.write_text('#!/bin/bash\nIFS= read -r line\nprintf "%s\\n" "$line"\n')
            docker.write_text('#!/bin/bash\nprintf "fixture\\n"\nIFS= read -r line\n[[ "$line" == fixture ]]\n')
            codex.chmod(0o700); docker.chmod(0o700)
            result = subprocess.run(['/bin/bash', '-c',
                'source "$1"; CODEX=$2; DOCKER=$3; CONTAINER=fixture; TMPDIR=$4; run_session',
                'fixture', str(HOST), str(codex), str(docker), temporary], capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, b'')
            self.assertEqual(sorted(p.name for p in directory.iterdir()), ['codex', 'docker'])


if __name__ == '__main__':
    unittest.main()
