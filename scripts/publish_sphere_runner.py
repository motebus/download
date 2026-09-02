#!/usr/bin/env python3
"""Validate and stage the immutable public Sphere restricted-runner release."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path


TAG = "sphere-runner-v5.2.0-3-5"
RELEASE = "5.2.0-3"
FINGERPRINT = "AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ARTIFACTS = (
    ("bootstrap-sphere-runner-5.2.0-3", "bootstrap-sphere-runner-5.2.0-3", ("BOOTSTRAP",), 0o755),
    ("install-sphere-5.2.0-3", "install-sphere-5.2.0-3", ("L1", "L9"), 0o755),
    ("sphere-install-dispatch-5.2.0-3", "sphere-install-dispatch-5.2.0-3", ("L1", "L9"), 0o755),
    ("sphere-verify-5.2.0-3", "sphere-verify-5.2.0-3", ("L1", "L9"), 0o755),
    ("sphere-result-5.2.0-3", "sphere-result-5.2.0-3", ("L1", "L9"), 0o755),
    ("sphere-maintenance-health-5.2.0-3", "sphere-maintenance-health-5.2.0-3", ("L1", "L9"), 0o755),
    ("verify-sphere-capability-5.2.0-3.py", "verify-sphere-capability-5.2.0-3.py", ("L1", "L9"), 0o755),
    ("sphere_capability.py", "lib/sphere_capability.py", ("L1", "L9"), 0o644),
    ("install-sphere-5.2.0-3.privilege-admission.json", "install-sphere-5.2.0-3.privilege-admission.json", ("L1", "L9"), 0o644),
    ("sshd-sphere-install.conf", "templates/sshd-sphere-install.conf", ("L1", "L9"), 0o644),
    ("l1-controller-ssh.pub", "public/l1-controller-ssh.pub", ("L1",), 0o644),
    ("l9-controller-ssh.pub", "public/l9-controller-ssh.pub", ("L1", "L9"), 0o644),
    ("l1-capability.pub.pem", "public/l1-capability.pub.pem", ("L1",), 0o644),
    ("l9-capability.pub.pem", "public/l9-capability.pub.pem", ("L1", "L9"), 0o644),
    ("controller-known_hosts", "public/controller-known_hosts", ("L1",), 0o600),
    ("authorized_keys-l1.template", "templates/authorized_keys-l1.template", ("L1",), 0o644),
    ("authorized_keys-l9.template", "templates/authorized_keys-l9.template", ("L9",), 0o644),
    ("sudoers-l1", "templates/sudoers-l1", ("L1",), 0o440),
    ("sudoers-l9", "templates/sudoers-l9", ("L9",), 0o440),
    ("sphere-capability-agent-5.2.0-3.py", "controller/sphere-capability-agent-5.2.0-3.py", ("L1",), 0o755),
    ("sphere-controller-5.2.0-3.py", "controller/sphere-controller-5.2.0-3.py", ("L1",), 0o755),
)
SOURCE_FILES = {"README.md", *(source for _, source, _, _ in ARTIFACTS)}


class RunnerReleaseError(ValueError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RunnerReleaseError(f"invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise RunnerReleaseError(f"JSON root is not an object: {path}")
    return value


def validate_source(root: Path) -> dict:
    if not root.is_dir() or root.is_symlink():
        raise RunnerReleaseError("Sphere runner source directory is unsafe")
    actual = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    if actual != SOURCE_FILES:
        extra = sorted(actual - SOURCE_FILES)
        missing = sorted(SOURCE_FILES - actual)
        raise RunnerReleaseError(f"Sphere runner public source is not exact; extra={extra} missing={missing}")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RunnerReleaseError(f"symlink is forbidden: {path}")
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            lowered = text.lower()
            if "gitlab.ypcloud.com" in lowered or "gitlab.com" in lowered:
                raise RunnerReleaseError(f"GitLab reference is forbidden: {path}")
            if "begin openssh private key" in lowered or "begin private key" in lowered:
                raise RunnerReleaseError(f"private key material is forbidden: {path}")
            if any(value in text for value in ("CI_JOB_TOKEN", "GITLAB_TOKEN", "/var/motebus/Config")):
                raise RunnerReleaseError(f"private build/topology input is forbidden: {path}")

    admission = load_json(root / "install-sphere-5.2.0-3.privilege-admission.json")
    if (
        admission.get("schema") != "install-sphere-privilege-admission/v1"
        or admission.get("status") != "approved"
        or admission.get("release_version") != RELEASE
        or admission.get("activation_blockers") != []
        or "OWNER_APPROVAL_REQUIRED" in json.dumps(admission)
    ):
        raise RunnerReleaseError("privilege admission is not approved and complete")
    runner = admission.get("runner", {})
    if runner.get("sha256") != sha256(root / "install-sphere-5.2.0-3"):
        raise RunnerReleaseError("install runner digest differs from admission")
    expected_operations = {
        name: sha256(root / source)
        for name, source, _, _ in ARTIFACTS
        if name in {
            "install-sphere-5.2.0-3",
            "sphere-verify-5.2.0-3",
            "sphere-result-5.2.0-3",
            "sphere-maintenance-health-5.2.0-3",
        }
    }
    for record in admission.get("routine_runners", []):
        name = Path(record.get("source_path", "")).name
        if expected_operations.get(name) != record.get("sha256"):
            raise RunnerReleaseError(f"routine runner digest differs from admission: {name}")
    public_digests = [
        sha256(root / "public/l1-capability.pub.pem"),
        sha256(root / "public/l9-capability.pub.pem"),
    ]
    admitted_digests = [item.get("public_key_sha256") for item in admission["capability_token"]["targets"]]
    if public_digests != admitted_digests or len(set(public_digests)) != 2:
        raise RunnerReleaseError("target capability public keys differ from admission or are shared")
    return admission


def stage(source: Path, output: Path) -> None:
    validate_source(source)
    if output.exists() and any(output.iterdir()):
        raise RunnerReleaseError("output directory is not empty")
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for name, source_name, targets, mode in ARTIFACTS:
        source_path = source / source_name
        target_path = output / name
        shutil.copyfile(source_path, target_path)
        os.chmod(target_path, mode)
        records.append({"name": name, "sha256": sha256(target_path), "targets": list(targets), "mode": f"{mode:04o}"})
    (output / ".artifact-map.json").write_text(
        json.dumps({"schema": "sphere-runner-artifact-map/v1", "artifacts": records}, indent=2) + "\n",
        encoding="utf-8",
    )


def finalize(output: Path, source_commit: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise RunnerReleaseError("source commit must be a full Git commit")
    artifact_map = load_json(output / ".artifact-map.json")
    records = artifact_map.get("artifacts")
    if not isinstance(records, list) or [item.get("name") for item in records] != [item[0] for item in ARTIFACTS]:
        raise RunnerReleaseError("artifact map is not exact")
    artifacts = []
    for item in records:
        path = output / item["name"]
        signature = output / (item["name"] + ".asc")
        if sha256(path) != item["sha256"] or not signature.is_file():
            raise RunnerReleaseError(f"artifact or signature is missing/changed: {item['name']}")
        artifacts.append(
            {
                "name": item["name"],
                "sha256": item["sha256"],
                "mode": item["mode"],
                "targets": item["targets"],
                "signature": signature.name,
                "signature_sha256": sha256(signature),
            }
        )
    manifest = {
        "schema": "sphere-runner-public-release/v1",
        "status": "approved",
        "tag": TAG,
        "release_version": RELEASE,
        "source_commit": source_commit,
        "signer_fingerprint": FINGERPRINT,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "artifacts": artifacts,
    }
    path = output / "runner-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def validate_dist(output: Path) -> dict:
    manifest = load_json(output / "runner-manifest.json")
    if (
        manifest.get("schema") != "sphere-runner-public-release/v1"
        or manifest.get("status") != "approved"
        or manifest.get("tag") != TAG
        or manifest.get("release_version") != RELEASE
        or manifest.get("signer_fingerprint") != FINGERPRINT
    ):
        raise RunnerReleaseError("runner manifest identity mismatch")
    records = manifest.get("artifacts")
    if not isinstance(records, list) or [item.get("name") for item in records] != [item[0] for item in ARTIFACTS]:
        raise RunnerReleaseError("runner manifest artifact order mismatch")
    for item in records:
        if not SHA_RE.fullmatch(item.get("sha256", "")) or not SHA_RE.fullmatch(item.get("signature_sha256", "")):
            raise RunnerReleaseError("runner manifest digest is invalid")
        if sha256(output / item["name"]) != item["sha256"] or sha256(output / item["signature"]) != item["signature_sha256"]:
            raise RunnerReleaseError(f"runner release asset changed: {item['name']}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate-source")
    validate_parser.add_argument("source", type=Path)
    stage_parser = subparsers.add_parser("stage")
    stage_parser.add_argument("source", type=Path)
    stage_parser.add_argument("output", type=Path)
    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("output", type=Path)
    finalize_parser.add_argument("--source-commit", required=True)
    dist_parser = subparsers.add_parser("validate-dist")
    dist_parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "validate-source":
            validate_source(args.source)
        elif args.command == "stage":
            stage(args.source, args.output)
        elif args.command == "finalize":
            finalize(args.output, args.source_commit)
        else:
            validate_dist(args.output)
    except (OSError, RunnerReleaseError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
