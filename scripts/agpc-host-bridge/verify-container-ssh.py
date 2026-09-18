#!/usr/bin/python3
"""Remote CI: actual image/exec SSH transport; host SSH authentication is not tested."""
import json
import os
import selectors
import subprocess
import time


def exact(pipe, count):
    data = bytearray()
    deadline = time.monotonic() + 15
    with selectors.DefaultSelector() as events:
        events.register(pipe, selectors.EVENT_READ)
        while len(data) < count:
            if not events.select(max(0, deadline - time.monotonic())):
                raise RuntimeError('SSH transport timed out')
            chunk = os.read(pipe.fileno(), count - len(data))
            if not chunk:
                raise RuntimeError('SSH transport ended early')
            data.extend(chunk)
    return bytes(data)


def main():
    container = subprocess.check_output([
        'docker', 'run', '-d', '--network', 'none', '--entrypoint', '/usr/bin/sleep',
        'agpc-ubuntu26:candidate', 'infinity'], text=True).strip()
    processes = []
    try:
        subprocess.run(['docker', 'exec', container, 'install', '-d', '-m0700',
                        '-o', 'moted', '-g', 'mote', '/run/mote/host-ssh'], check=True)
        def start(command):
            proc = subprocess.Popen(['docker', 'exec', '-i', '--user', 'moted', container, *command],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            processes.append(proc)
            return proc
        forwarder = start(['python3', '/usr/local/libexec/agpc/ssh-forwarder.py'])
        host = start(['python3', '/usr/local/libexec/agpc/codex-stream.py', 'serve',
                      '--socket', '/run/mote/host-ssh/0.sock', '--announce-ssh'])
        # Exercise the exact loopback endpoint used by the packaged Mote B relay.
        client = start(['python3', '-c', '''
import socket, time
for attempt in range(100):
    try:
        peer = socket.create_connection(('127.0.0.1', 22), timeout=5)
        break
    except ConnectionRefusedError:
        time.sleep(.1)
else:
    raise RuntimeError('loopback SSH listener did not start')
with peer:
    banner = b''
    while not banner.endswith(b'\\n'):
        chunk = peer.recv(1)
        assert chunk, 'SSH banner truncated'
        banner += chunk
    assert banner == b'SSH-2.0-host-fixture\\r\\n'
    payload = bytes(range(256)) * 64
    peer.sendall(payload)
    response = bytearray()
    while len(response) < len(payload):
        chunk = peer.recv(len(payload) - len(response))
        assert chunk, 'SSH response truncated'
        response.extend(chunk)
    assert response == payload
'''])
        assert exact(host.stdout, 15) == b'AGPC-SSH-READY\n'
        host.stdin.write(b'SSH-2.0-host-fixture\r\n'); host.stdin.flush()
        payload = bytes(range(256)) * 64
        assert exact(host.stdout, len(payload)) == payload
        host.stdin.write(payload); host.stdin.flush()
        assert client.wait(timeout=15) == 0
        assert host.wait(timeout=15) == 0
        assert forwarder.poll() is None
        print(json.dumps({'container_loopback_ssh_bridge': 'passed',
                          'published_ports': [], 'host_sshd': 'simulated',
                          'mac_ssh_authentication': 'not-tested', 'runtime_ready': False}))
    finally:
        # Stop exec processes at their owner before reaping the Docker clients.
        subprocess.run(['docker', 'rm', '-f', container], check=True, stdout=subprocess.DEVNULL)
        for proc in processes:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait()
            proc.stdin.close(); proc.stdout.close()


if __name__ == '__main__':
    main()
