#!/usr/bin/python3
"""Remote CI only: real image/cx-exec transport with simulated host protocol frames."""
import json
import os
import selectors
import subprocess
import time


def frame(sender, receiver, value):
    payload = json.dumps(value).encode() + b'\n'
    sender.stdin.write(payload)
    sender.stdin.flush()
    received = bytearray()
    deadline = time.monotonic() + 15
    with selectors.DefaultSelector() as events:
        events.register(receiver.stdout, selectors.EVENT_READ)
        while len(received) < len(payload):
            if not events.select(max(0, deadline - time.monotonic())):
                raise RuntimeError('Docker bridge frame timed out')
            chunk = os.read(receiver.stdout.fileno(), len(payload) - len(received))
            if not chunk:
                raise RuntimeError('Docker bridge closed early')
            received.extend(chunk)
    assert received == payload, 'protocol frame changed'


def main():
    container = subprocess.check_output([
        'docker', 'run', '-d', '--network', 'none', '--entrypoint', '/usr/bin/sleep',
        'agpc-ubuntu26:candidate', 'infinity'], text=True).strip()
    processes = []
    try:
        subprocess.run(['docker', 'exec', container, 'install', '-d', '-m0700',
                        '-o', 'cx-mesh', '-g', 'cx-mesh', '/run/cx-mesh'], check=True)
        def start(command):
            proc = subprocess.Popen(['docker', 'exec', '-i', '--user', 'cx-mesh', container, *command],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            processes.append(proc)
            return proc
        host = start(['/usr/bin/python3', '/usr/local/libexec/agpc/codex-stream.py', 'serve'])
        client = start(['/usr/bin/cx-exec', 'app-server', '--config', '/etc/cx-mesh/cx-mesh.toml'])
        frame(client, host, {'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'transport_fixture'}}})
        frame(host, client, {'id': 1, 'result': {'fixture': True}})
        frame(host, client, {'id': 2, 'method': 'item/commandExecution/requestApproval', 'params': {}})
        frame(client, host, {'id': 2, 'result': {'decision': 'decline'}})
        frame(host, client, {'method': 'turn/completed', 'params': {'fixture': True}})
        client.stdin.close()
        # Docker exec must exit to deliver input EOF to the host App-Server.
        # Closing only the helper stdout cannot complete this lifecycle.
        with selectors.DefaultSelector() as events:
            events.register(host.stdout, selectors.EVENT_READ)
            assert events.select(10), 'host did not observe client EOF'
            assert os.read(host.stdout.fileno(), 1) == b''
        host.stdin.close()
        assert host.wait(timeout=10) == 0
        assert client.wait(timeout=10) == 0
        print(json.dumps({'container_cx_exec_bridge': 'passed', 'host_protocol': 'simulated',
                          'real_mac_acceptance': False}))
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            proc.stdin.close()
            proc.stdout.close()
        subprocess.run(['docker', 'rm', '-f', container], check=True, stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
