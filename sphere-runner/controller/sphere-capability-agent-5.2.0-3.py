#!/usr/bin/python3
"""Target-scoped, local-only Sphere capability issuer for L1."""

from __future__ import annotations

import json
import os
import pwd
import signal
import socket
import stat
import sys
import time
import uuid
from pathlib import Path


RELEASE = "5.2.0-3"
REQUEST_SCHEMA = "install-sphere-capability-request/v1"
OPERATIONS = {
    "install": "sphere-install:5.2.0-3",
    "verify": "sphere-verify:5.2.0-3",
    "result": "sphere-result:5.2.0-3",
    "maintenance-health": "sphere-maintenance-health:5.2.0-3",
}
RUNNER_DIGESTS = {
    "install": "6f72c1232f9a302c99fd21dc663f6521d8645216c5dbc03158a0080bf3a479bd",
    "verify": "438015722535b0ce8bc315b25c22780c6fb888ce6e6366f4c1302bc26e866e65",
    "result": "f2a6ec2e72349f8d2bd1a527caac692a83cf9643c44c3d49f73d6c5888e482c5",
    "maintenance-health": "bd0911628cff52964bfb58f0df1e64a7ab927b5b77beaff8046f90c8b1b58867",
}
KEY_IDS = {
    "L1": "sphere-l1-capability-5.2.0-3-758f4aa2f513",
    "L9": "sphere-l9-capability-5.2.0-3-47827e08eef9",
}


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"Sphere capability agent failed: {message}")


def safe_private_key(path: Path) -> None:
    item = os.lstat(path)
    if (
        not stat.S_ISREG(item.st_mode)
        or item.st_uid != os.getuid()
        or item.st_mode & 0o077
    ):
        fail(f"unsafe private key: {path}")


def receive_frame(connection: socket.socket) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = connection.recv(1025 - total)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > 1024:
            fail("request frame is overlong")
    return b"".join(chunks)


def parse_request(raw: bytes) -> tuple[str, str]:
    try:
        request = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("request is malformed") from error
    if not isinstance(request, dict) or set(request) != {"schema", "target", "verb"}:
        raise ValueError("request fields are invalid")
    if request["schema"] != REQUEST_SCHEMA:
        raise ValueError("request schema is invalid")
    target = request["target"]
    verb = request["verb"]
    if target not in KEY_IDS or verb not in OPERATIONS:
        raise ValueError("target or verb is not admitted")
    return target, verb


def main() -> int:
    if sys.argv != [sys.argv[0]]:
        fail("arguments are forbidden")
    if os.geteuid() == 0:
        fail("the issuer must run as the L1 controller user, never root")

    account = pwd.getpwuid(os.getuid())
    controller_root = Path(account.pw_dir) / ".local/share/sphere-install-controller" / RELEASE
    runtime_root = Path(f"/run/user/{os.getuid()}") / "sphere-install-controller" / RELEASE
    socket_path = runtime_root / "issuer.sock"
    library_dir = Path(__file__).resolve().parents[1] / "lib"
    sys.path.insert(0, str(library_dir))
    try:
        from sphere_capability import sign_token
    except ImportError as error:
        fail(f"capability library is unavailable: {error}")

    private_keys = {
        "L1": controller_root / "l1-capability.pem",
        "L9": controller_root / "l9-capability.pem",
    }
    for private_key in private_keys.values():
        safe_private_key(private_key)

    runtime_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    item = os.lstat(runtime_root)
    if item.st_uid != os.getuid() or not stat.S_ISDIR(item.st_mode) or item.st_mode & 0o077:
        fail("runtime directory is unsafe")
    try:
        socket_path.unlink()
    except FileNotFoundError:
        pass

    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    os.chmod(socket_path, 0o600)
    listener.listen(8)

    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True
        listener.close()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    try:
        while not stopping:
            try:
                connection, _ = listener.accept()
            except OSError:
                if stopping:
                    break
                raise
            with connection:
                credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                peer_uid = int.from_bytes(credentials[4:8], sys.byteorder)
                if peer_uid != os.getuid():
                    continue
                try:
                    target, verb = parse_request(receive_frame(connection))
                    now = int(time.time())
                    claims = {
                        "iss": "L1",
                        "aud": target,
                        "target": target,
                        "release": RELEASE,
                        "operation": OPERATIONS[verb],
                        "runner_sha256": RUNNER_DIGESTS[verb],
                        "iat": now - 1,
                        "exp": now + 120,
                        "jti": str(uuid.uuid4()),
                        "correlation_id": str(uuid.uuid4()),
                        "key_id": KEY_IDS[target],
                    }
                    token = sign_token(claims, private_keys[target])
                    connection.sendall(token)
                except (OSError, ValueError):
                    continue
    finally:
        listener.close()
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
