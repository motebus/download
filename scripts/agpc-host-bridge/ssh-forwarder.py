#!/usr/bin/python3
"""Container loopback SSH listener; forwards only to host-owned stdio slots."""
import fcntl
import os
from pathlib import Path
import signal
import socket
import socketserver
import stat
import struct
import threading
import time

DIRECTORY = Path('/run/mote/host-ssh')
SLOTS = 4


def host_slot(directory, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for index in range(SLOTS):
            fd = os.open(directory / f'{index}.client-lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            lock = os.fdopen(fd, 'w')
            peer = socket.socket(socket.AF_UNIX)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                peer.connect(str(directory / f'{index}.sock'))
                _, uid, _ = struct.unpack('3i', peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if uid != os.getuid():
                    raise PermissionError('host slot UID mismatch')
                return peer, lock
            except (BlockingIOError, FileNotFoundError, ConnectionRefusedError):
                peer.close()
                lock.close()
            except BaseException:
                peer.close()
                lock.close()
                raise
        time.sleep(.1)
    raise TimeoutError('no Mac SSH worker is available')


def forward(left, right):
    def copy(source, target):
        try:
            while True:
                data = source.recv(65536)
                if not data:
                    break
                target.sendall(data)
        except OSError:
            pass  # Closing either side ends this SSH transport session.
        finally:
            for peer in (source, target):
                try:
                    peer.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
    thread = threading.Thread(target=copy, args=(left, right), daemon=True)
    thread.start()
    copy(right, left)
    thread.join(timeout=2)
    if thread.is_alive():
        raise RuntimeError('SSH copy thread did not terminate')


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            peer, lock = host_slot(self.server.directory)
            with peer, lock:
                forward(self.request, peer)
        except OSError as error:
            print(f'agpc-host-ssh: {error}', file=__import__('sys').stderr, flush=True)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, directory):
        self.directory = directory
        self.capacity = threading.BoundedSemaphore(SLOTS)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.capacity.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.capacity.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.capacity.release()


def main():
    os.umask(0o077)
    DIRECTORY.mkdir(mode=0o700, parents=False, exist_ok=True)
    info = DIRECTORY.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError('SSH bridge directory must be private and owned by the service user')
    signal.signal(signal.SIGTERM, lambda *_: __import__('sys').exit(0))
    with Server(('127.0.0.1', 22), DIRECTORY) as server:
        notify = os.environ.get('NOTIFY_SOCKET')
        if notify:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as status:
                status.connect(notify.replace('@', '\0', 1) if notify.startswith('@') else notify)
                status.sendall(b'READY=1')
        server.serve_forever()


if __name__ == '__main__':
    main()
