#!/usr/bin/python3
import datetime as dt
import hashlib
import json
import os
import socket
import stat
import subprocess
import sys


ADMISSION_PATH = "/etc/sphere/install-sphere-5.2.0-3.privilege-admission.json"
ADMISSION_SIGNATURE_PATH = ADMISSION_PATH + ".asc"
TRUST_KEYRING_PATH = "/usr/share/keyrings/sphere-release-archive-keyring.gpg"
LIBRARY_DIR = "/usr/libexec/sphere/lib"
LIBRARY_PATH = LIBRARY_DIR + "/sphere_capability.py"
DISPATCHER_PATH = "/usr/libexec/sphere/sphere-install-dispatch-5.2.0-3"
EXPECTED_KEYRING_SHA256 = "756fc2632c307509b8e5ece665ced7f4d1a58636ac935aefc1e017f7dcfcbfbd"
TARGETS = {
    "medge-home": {
        "id": "L1",
        "public_key_path": "/etc/sphere/keys/l1-capability-5.2.0-3.ed25519.pub",
        "replay_dir": "/var/lib/sphere-install/replay/l1",
    },
    "medge-tv": {
        "id": "L9",
        "public_key_path": "/etc/sphere/keys/l1-to-l9-capability-5.2.0-3.ed25519.pub",
        "replay_dir": "/var/lib/sphere-install/replay/l9",
    },
}
OPERATIONS = {
    "sphere-install:5.2.0-3": "/usr/libexec/sphere/install-sphere-5.2.0-3",
    "sphere-verify:5.2.0-3": "/usr/libexec/sphere/sphere-verify-5.2.0-3",
    "sphere-result:5.2.0-3": "/usr/libexec/sphere/sphere-result-5.2.0-3",
    "sphere-maintenance-health:5.2.0-3": "/usr/libexec/sphere/sphere-maintenance-health-5.2.0-3",
}


TARGET_ID = "unresolved"


def deny(reason):
    subprocess.run(
        [
            "/usr/bin/logger",
            "-p",
            "authpriv.warning",
            "-t",
            "sphere-capability-verifier",
            f"target={TARGET_ID} decision=deny reason={reason}",
        ],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"},
    )
    raise SystemExit("Sphere capability denied")


def safe_root_file(path):
    current = os.path.abspath(path)
    first = True
    while True:
        try:
            item = os.lstat(current)
        except OSError:
            deny("missing-root-path")
        expected_type = stat.S_ISREG if first else stat.S_ISDIR
        if not expected_type(item.st_mode) or item.st_uid != 0 or item.st_gid != 0 or item.st_mode & 0o022:
            deny("unsafe-root-path")
        parent = os.path.dirname(current)
        if current == "/" or parent == current:
            break
        current = parent
        first = False


def sha256(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


if len(sys.argv) != 2 or sys.argv[1] not in OPERATIONS:
    deny("unlisted-operation")
operation = sys.argv[1]

stable_identity = socket.gethostname().split(".", 1)[0]
target_config = TARGETS.get(stable_identity)
if target_config is None:
    deny("target-identity")
TARGET_ID = target_config["id"]
PUBLIC_KEY_PATH = target_config["public_key_path"]
REPLAY_DIR = target_config["replay_dir"]

for path in (ADMISSION_PATH, ADMISSION_SIGNATURE_PATH, TRUST_KEYRING_PATH, PUBLIC_KEY_PATH):
    safe_root_file(path)
if sha256(TRUST_KEYRING_PATH) != EXPECTED_KEYRING_SHA256:
    deny("trust-keyring-digest")

signature_check = subprocess.run(
    [
        "/usr/bin/gpgv",
        "--keyring",
        TRUST_KEYRING_PATH,
        ADMISSION_SIGNATURE_PATH,
        ADMISSION_PATH,
    ],
    check=False,
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"},
)
if signature_check.returncode != 0:
    deny("admission-signature")

try:
    with open(ADMISSION_PATH, encoding="utf-8") as handle:
        admission = json.load(handle)
except (OSError, json.JSONDecodeError):
    deny("admission-shape")
if (
    admission.get("schema") != "install-sphere-privilege-admission/v1"
    or admission.get("status") != "approved"
    or admission.get("release_version") != "5.2.0-3"
):
    deny("admission-status")

admitted_targets = [item for item in admission.get("targets", []) if item.get("id") == TARGET_ID]
if (
    len(admitted_targets) != 1
    or admitted_targets[0].get("stable_identity") != stable_identity
    or operation not in admitted_targets[0].get("accepted_operations", [])
):
    deny("target-admission")

try:
    now = dt.datetime.now(dt.timezone.utc)
    valid_from = dt.datetime.fromisoformat(admission["valid_from"].replace("Z", "+00:00"))
    valid_until = dt.datetime.fromisoformat(admission["valid_until"].replace("Z", "+00:00"))
except (KeyError, TypeError, ValueError):
    deny("admission-validity")
if valid_from.tzinfo is None or valid_until.tzinfo is None or not valid_from <= now <= valid_until:
    deny("admission-expired")

capability = admission.get("capability_token", {})
if (
    capability.get("schema") != "install-sphere-capability-token/v1"
    or capability.get("issuer") != "L1"
    or capability.get("max_ttl_seconds") != 300
):
    deny("capability-admission")

target_records = [item for item in capability.get("targets", []) if item.get("id") == TARGET_ID]
if len(target_records) != 1:
    deny("capability-target")
token_target = target_records[0]
if (
    token_target.get("audience") != TARGET_ID
    or token_target.get("public_key_path") != PUBLIC_KEY_PATH
    or token_target.get("replay_dir") != REPLAY_DIR
):
    deny("capability-target-binding")

artifact_records = capability.get("artifacts", {})
artifact_paths = {
    "verifier_sha256": os.path.abspath(__file__),
    "library_sha256": LIBRARY_PATH,
    "dispatcher_sha256": DISPATCHER_PATH,
}
for digest_field, artifact_path in artifact_paths.items():
    safe_root_file(artifact_path)
    if artifact_records.get(digest_field) != sha256(artifact_path):
        deny("capability-artifact-digest")

operation_records = capability.get("allowed_operations", [])
matches = [item for item in operation_records if item.get("operation") == operation]
if len(matches) != 1:
    deny("operation-admission")
operation_record = matches[0]
runner_path = OPERATIONS[operation]
if operation_record.get("runner_path") != runner_path:
    deny("operation-runner-path")
safe_root_file(runner_path)
runner_digest = sha256(runner_path)
if operation_record.get("runner_sha256") != runner_digest:
    deny("operation-runner-digest")

public_key_digest = token_target.get("public_key_sha256")
key_id = token_target.get("issuer_key_id")
if (
    not isinstance(public_key_digest, str)
    or len(public_key_digest) != 64
    or "OWNER_APPROVAL_REQUIRED" in public_key_digest
    or not isinstance(key_id, str)
    or "OWNER_APPROVAL_REQUIRED" in key_id
):
    deny("issuer-key-admission")

sys.path.insert(0, LIBRARY_DIR)
try:
    from sphere_capability import CapabilityError, verify_and_consume
except (ImportError, OSError):
    deny("verifier-library")

raw = sys.stdin.buffer.read(16385)
if not raw or len(raw) > 16384:
    deny("token-frame")
try:
    replay_record = verify_and_consume(
        raw=raw,
        public_key_path=PUBLIC_KEY_PATH,
        public_key_digest=public_key_digest,
        expected={
            "iss": "L1",
            "aud": TARGET_ID,
            "target": TARGET_ID,
            "release": "5.2.0-3",
            "operation": operation,
            "runner_sha256": runner_digest,
            "key_id": key_id,
            "max_ttl_seconds": 300,
            "clock_skew_seconds": 30,
        },
        replay_dir=REPLAY_DIR,
    )
except CapabilityError as error:
    deny(type(error).__name__)
except OSError:
    deny("token-io")

subprocess.run(
    [
        "/usr/bin/logger",
        "-p",
        "authpriv.notice",
        "-t",
        "sphere-capability-verifier",
        f"target={TARGET_ID} decision=allow "
        f"operation={operation} correlation={replay_record['correlation_id']} "
        f"token_id_sha256={replay_record['token_id_sha256']}",
    ],
    check=False,
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"},
)
print(replay_record["correlation_id"])

