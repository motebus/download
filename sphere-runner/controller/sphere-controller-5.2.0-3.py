#!/usr/bin/python3
"""Send one fixed Sphere lifecycle operation through a constrained target key."""

from __future__ import annotations

import json
import os
import pwd
import socket
import subprocess
import sys
from pathlib import Path


RELEASE = "5.2.0-3"
REQUEST_SCHEMA = "install-sphere-capability-request/v1"
OPERATIONS = {
    "install": "sphere-install:5.2.0-3",
    "verify": "sphere-verify:5.2.0-3",
    "result": "sphere-result:5.2.0-3",
    "maintenance-health": "sphere-maintenance-health:5.2.0-3",
}


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"Sphere controller failed: {message}")


def receive_token(connection: socket.socket) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = connection.recv(16385 - total)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > 16384:
            fail("issuer returned an overlong token")
    token = b"".join(chunks)
    if not token:
        fail("issuer returned no token")
    return token


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"L1", "L9"} or sys.argv[2] not in OPERATIONS:
        fail("usage: sphere-controller-5.2.0-3.py L1|L9 install|verify|result|maintenance-health")
    target, verb = sys.argv[1:]
    operation = OPERATIONS[verb]
    account = pwd.getpwuid(os.getuid())
    controller_root = Path(account.pw_dir) / ".local/share/sphere-install-controller" / RELEASE
    socket_path = Path(f"/run/user/{os.getuid()}") / "sphere-install-controller" / RELEASE / "issuer.sock"

    request = json.dumps(
        {"schema": REQUEST_SCHEMA, "target": target, "verb": verb},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.connect(str(socket_path))
        connection.sendall(request)
        connection.shutdown(socket.SHUT_WR)
        token = receive_token(connection)
    finally:
        connection.close()

    common = [
        "/usr/bin/ssh",
        "-T",
        "-o", "BatchMode=yes",
        "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "IdentitiesOnly=yes",
        "-o", "ClearAllForwardings=yes",
        "-o", "RequestTTY=no",
        "-o", f"UserKnownHostsFile={controller_root / 'known_hosts'}",
    ]
    if target == "L1":
        command = common + [
            "-o", "HostKeyAlias=sphere-install-l1",
            "-i", str(controller_root / "l1-ssh"),
            "sphere-install-l1@127.0.0.1",
            operation,
        ]
    else:
        command = common + [
            "-o", "ProxyCommand=/usr/libexec/mote-proxy/ssh-proxy %h %p",
            "-i", str(controller_root / "l9-ssh"),
            "sphere-install-l9@medge-tv.mote",
            operation,
        ]
    completed = subprocess.run(command, input=token, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
