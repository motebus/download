#!/usr/bin/python3
"""Container-only byte bridge. No JSON interpretation or remote command execution."""
import argparse
import fcntl
import os
from pathlib import Path
import selectors
import signal
import socket
import stat
import sys
import time

LIMIT = 256 * 1024
DEFAULT_SOCKET = '/run/cx-mesh/host-codex/stdio.sock'


def pump(peer, host_side=False):
    """Bounded duplex forwarding, preserving half-close and stdout backpressure."""
    peer.setblocking(False)
    os.set_blocking(0, False)
    os.set_blocking(1, False)
    to_peer, to_stdout = bytearray(), bytearray()
    input_open = peer_open = True
    sent_eof = False
    close_deadline = None
    stdout_closed = False
    while True:
        if not input_open and not to_peer and not sent_eof:
            peer.shutdown(socket.SHUT_WR)
            sent_eof = True
            close_deadline = time.monotonic() + 5
        if not peer_open and not to_stdout:
            if not host_side or (not input_open and not to_peer):
                return
            if not stdout_closed:
                os.close(1)  # Tell host App-Server that its input reached EOF.
                stdout_closed = True
                close_deadline = time.monotonic() + 5
        with selectors.DefaultSelector() as events:
            if input_open and len(to_peer) < LIMIT:
                events.register(0, selectors.EVENT_READ, 'stdin')
            mask = 0
            if peer_open and len(to_stdout) < LIMIT:
                mask |= selectors.EVENT_READ
            if to_peer:
                mask |= selectors.EVENT_WRITE
            if mask:
                events.register(peer, mask, 'peer')
            if to_stdout:
                events.register(1, selectors.EVENT_WRITE, 'stdout')
            remaining = None if close_deadline is None else max(0, close_deadline - time.monotonic())
            ready_events = events.select(remaining)
            if close_deadline is not None and time.monotonic() >= close_deadline:
                raise TimeoutError("peer did not close after host input EOF")
            for key, ready in ready_events:
                try:
                    if key.data == 'stdin':
                        chunk = os.read(0, min(65536, LIMIT - len(to_peer)))
                        if chunk:
                            to_peer.extend(chunk)
                        else:
                            input_open = False
                    elif key.data == 'stdout':
                        count = os.write(1, to_stdout)
                        del to_stdout[:count]
                    else:
                        if ready & selectors.EVENT_READ:
                            chunk = peer.recv(min(65536, LIMIT - len(to_stdout)))
                            if chunk:
                                to_stdout.extend(chunk)
                            else:
                                peer_open = False
                        if ready & selectors.EVENT_WRITE:
                            count = peer.send(to_peer)
                            del to_peer[:count]
                except BlockingIOError:
                    pass


def private_directory(path):
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError('bridge directory must be owned by this UID with mode 0700')


def serve(path, timeout):
    private_directory(path.parent)
    # Prevent two host sessions from replacing each other's socket, including
    # stale sockets left after a Docker exec is interrupted.
    fd = os.open(str(path) + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path.is_symlink() or (path.exists() and not stat.S_ISSOCK(path.stat().st_mode)):
            raise RuntimeError('refusing to replace a non-socket bridge path')
        path.unlink(missing_ok=True)
        try:
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(str(path))
                os.chmod(path, 0o600)
                listener.listen(1)
                # Never leave a detached exec waiting indefinitely for a client.
                listener.settimeout(timeout)
                peer, _ = listener.accept()
                with peer:
                    # Linux peer credentials; production helpers run as cx-mesh.
                    import struct
                    _, uid, _ = struct.unpack('3i', peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    if uid != os.getuid():
                        raise RuntimeError('unexpected bridge client UID')
                    pump(peer, host_side=True)
        finally:
            path.unlink(missing_ok=True)


def connect(path, timeout):
    deadline = time.monotonic() + timeout
    while True:
        with socket.socket(socket.AF_UNIX) as peer:
            try:
                peer.connect(str(path))
            except (FileNotFoundError, ConnectionRefusedError):
                if time.monotonic() >= deadline:
                    raise TimeoutError('Mac host Codex bridge is unavailable')
                time.sleep(0.1)
                continue
            import struct
            _, uid, _ = struct.unpack('3i', peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != os.getuid():
                raise RuntimeError('unexpected bridge server UID')
            pump(peer)
            return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('serve', 'app-server'))
    parser.add_argument('--socket', type=Path, default=Path(DEFAULT_SOCKET))
    parser.add_argument('--timeout', type=float, default=30)
    args = parser.parse_args()
    if not args.socket.is_absolute() or not 0 < args.timeout <= 120:
        parser.error('absolute socket path and timeout in (0, 120] are required')
    os.umask(0o077)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        if args.mode == 'serve':
            serve(args.socket, args.timeout)
        else:
            connect(args.socket, args.timeout)
    except (OSError, RuntimeError) as error:
        print(f'agpc-host-codex: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
