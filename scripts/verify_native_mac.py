#!/usr/bin/env python3
"""Execute only the pinned public controller on a native Darwin ARM64 runner."""
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import tempfile
from publish_native import fetch_release, macos_executable, require

ROOT = Path(__file__).resolve().parents[1]


def main():
    require(platform.system() == "Darwin" and platform.machine() == "arm64", "native macOS ARM64 runner required")
    pins = json.loads((ROOT / "scripts/native-pages.json").read_text())
    manifest = json.loads(fetch_release(pins["tag"], "MANIFEST.json", pins["manifest_sha256"]))
    require(manifest["tag"] == pins["tag"] and manifest["assets"] == pins["assets"]
            and manifest["payload_sha256"] == pins["payload_sha256"], "release provenance mismatch")
    name = f"agpc-mac-arm64-{manifest['version']}.tar.gz"
    data = fetch_release(pins["tag"], name, pins["assets"][name]["sha256"])
    binary = macos_executable(data, pins["payload_sha256"]["macos"]["arm64"])
    with tempfile.TemporaryDirectory(prefix="agpc-mac-acceptance-") as directory:
        root = Path(directory)
        executable = root / "agpc"
        executable.write_bytes(binary)
        executable.chmod(0o755)
        home = root / "home"
        home.mkdir(mode=0o700)
        environment = {"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
        def run(args, code=0):
            result = subprocess.run([str(executable), *args], env=environment, capture_output=True, text=True, timeout=20)
            require(result.returncode == code, f"unexpected exit for {args[0]}: {result.returncode}: {result.stderr}")
            return result
        require(run(["version"]).stdout.strip() == manifest["sources"]["macos"]["commit"], "source version mismatch")
        require("Apple Silicon" in run(["help"]).stdout, "controller help unavailable")
        compose = run(["sphere", "compose"]).stdout
        require(compose.count("platform: linux/amd64") == 2 and "127.0.0.1:6262:6262" in compose,
                "Sphere architecture / loopback boundary mismatch")
        config = root / "private-config.json"
        args = ["--config", str(config)]
        run([*args, "init"])
        original = config.read_bytes()
        require(stat.S_IMODE(config.stat().st_mode) == 0o600, "private config permissions mismatch")
        require(json.loads(original)["services"] == [], "init must not invent native owner artifacts")
        run([*args, "init"], 1)
        require(config.read_bytes() == original, "repeat init changed existing configuration")
        require("missing native owner component" in run([*args, "start"], 1).stderr,
                "full startup must fail before Docker when native owners are absent")
        report = json.loads(run([*args, "doctor"], 1).stdout)
        require(report["ready"] is False and bool(report["pending"]), "missing acceptance must not report Ready")
        marker = root / "unrestricted-exec-must-not-run"
        run(["exec", "/usr/bin/touch", str(marker)], 1)
        require(not marker.exists(), "unrestricted command execution must remain unavailable")
    evidence = {"schema": "agpc.macos-controller-acceptance/v1", "platform": platform.platform(),
                "cpu": platform.machine(), "release": pins["tag"],
                "source_commit": manifest["sources"]["macos"]["commit"],
                "executable_sha256": pins["payload_sha256"]["macos"]["arm64"],
                "native_cli_verified": True, "private_init_verified": True,
                "missing_owner_start_rejected": True, "unrestricted_exec_rejected": True, "full_runtime_ready": False,
                "pending": ["native owner artifacts", "Docker Desktop Sphere VM", "launchd lifecycle", "protocol/security/peer acceptance"]}
    output = ROOT / ".cache/native-mac-acceptance"
    output.mkdir(parents=True, exist_ok=True)
    (output / "controller.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write("Verified the released controller executes on macOS ARM64: version, help, pinned Compose, private configuration and rejection of missing native owners. Full native stack and Docker Desktop VM acceptance remain pending.\n")


if __name__ == "__main__":
    main()
