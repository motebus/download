"""Opaque SSH-byte transport checks; these do not claim authenticated Mac SSH."""
import importlib.util
import os
from pathlib import Path
import selectors
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'scripts/agpc-host-bridge'
HOST = DIRECTORY / 'mac-ssh-session.sh'


def exact(pipe, count):
    data = bytearray()
    with selectors.DefaultSelector() as events:
        events.register(pipe, selectors.EVENT_READ)
        while len(data) < count:
            if not events.select(5):
                raise AssertionError('SSH test stream timed out')
            chunk = os.read(pipe.fileno(), count - len(data))
            if not chunk:
                raise AssertionError('SSH test stream closed early')
            data.extend(chunk)
    return bytes(data)


@unittest.skipUnless(sys.platform == 'linux', 'container peer credentials require Linux')
class ForwarderTests(unittest.TestCase):
    def test_ssh_banner_and_binary_data_reach_host_worker(self):
        spec = importlib.util.spec_from_file_location('ssh_forwarder', DIRECTORY / 'ssh-forwarder.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            worker = subprocess.Popen([sys.executable, str(DIRECTORY / 'codex-stream.py'),
                                       'serve', '--socket', str(path / '0.sock'), '--announce-ssh'],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            server = module.Server(('127.0.0.1', 0), path)
            loop = threading.Thread(target=server.serve_forever, daemon=True)
            loop.start()
            try:
                with socket.create_connection(server.server_address, timeout=5) as client:
                    self.assertEqual(exact(worker.stdout, 15), b'AGPC-SSH-READY\n')
                    banner = b'SSH-2.0-native-host-fixture\r\n'
                    worker.stdin.write(banner); worker.stdin.flush()
                    self.assertEqual(client.recv(len(banner)), banner)
                    payload = bytes(range(256)) * 64
                    client.sendall(payload)
                    self.assertEqual(exact(worker.stdout, len(payload)), payload)
                self.assertEqual(worker.wait(timeout=5), 0, worker.stderr.read())
            finally:
                server.shutdown(); server.server_close(); loop.join(timeout=2)
                if worker.poll() is None:
                    worker.kill()
                worker.wait(timeout=3)
                worker.stdin.close(); worker.stdout.close(); worker.stderr.close()

    def test_four_slots_are_exclusive_and_reusable(self):
        spec = importlib.util.spec_from_file_location('ssh_slots', DIRECTORY / 'ssh-forwarder.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            listeners, acquired = [], []
            try:
                for index in range(module.SLOTS):
                    listener = socket.socket(socket.AF_UNIX)
                    listener.bind(str(directory / f'{index}.sock'))
                    listener.listen(4)
                    listeners.append(listener)
                for _ in range(module.SLOTS):
                    acquired.append(module.host_slot(directory, timeout=.2))
                with self.assertRaises(TimeoutError):
                    module.host_slot(directory, timeout=.1)
                peer, lock = acquired.pop()
                peer.close(); lock.close()
                acquired.append(module.host_slot(directory, timeout=.2))
            finally:
                for peer, lock in acquired:
                    peer.close(); lock.close()
                for listener in listeners:
                    listener.close()

    def test_no_host_worker_fails_closed(self):
        spec = importlib.util.spec_from_file_location('ssh_forwarder_missing', DIRECTORY / 'ssh-forwarder.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(TimeoutError):
                module.host_slot(Path(temporary), timeout=.1)


class HostSSHTests(unittest.TestCase):
    def test_source_is_inert(self):
        result = subprocess.run(['/bin/bash', '-c', 'source "$1"', 'fixture', str(HOST)], capture_output=True)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b'', b''))

    def fixture(self, preamble):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            docker = path / 'docker'
            netcat = path / 'nc'
            marker = path / 'connected'
            docker.write_text('#!/bin/bash\nprintf "' + preamble + '\\n"\n'
                              'printf "ssh-bytes\\n"\nIFS= read -r line\n[[ "$line" == ssh-bytes ]]\n')
            netcat.write_text('#!/bin/bash\n[[ "$1:$2" == 127.0.0.1:22 ]] || exit 90\n'
                              'touch "$MARKER"\ncat\n')
            docker.chmod(0o700); netcat.chmod(0o700)
            result = subprocess.run(['/bin/bash', '-c',
                'source "$1"; DOCKER=$2; NETCAT=$3; SLOT=0; CONTAINER=fixture; TMPDIR=$4; run_ssh_session',
                'fixture', str(HOST), str(docker), str(netcat), temporary], env=dict(os.environ, MARKER=str(marker)),
                capture_output=True, timeout=15)
            connected = marker.exists()
            self.assertFalse(list(path.glob('agpc-ssh.*')))
            return result, connected

    def test_host_connects_only_after_worker_accepts(self):
        result, connected = self.fixture('AGPC-SSH-READY')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(connected)
        self.assertEqual(result.stdout, b'')

    def test_invalid_worker_never_connects_to_host_sshd(self):
        result, connected = self.fixture('wrong-preamble')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(connected)


if __name__ == '__main__':
    unittest.main()
