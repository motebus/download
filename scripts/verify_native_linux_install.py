#!/usr/bin/env python3
"""Install the reviewed candidate on an ephemeral native GitHub Ubuntu runner."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

import publish_native


def command(args, expected=0):
    result = subprocess.run(args, text=True, capture_output=True, timeout=1800, check=False)
    if result.returncode != expected:
        print(result.stdout[-6000:])
        print(result.stderr[-6000:])
        raise RuntimeError(f"Command failed: {args[0]} (exit {result.returncode}, expected {expected})")
    return result.stdout


def containers():
    from native_install_policy import RUNTIME_PACKAGE
    output = command(["dpkg-query", "-W", "-f=${binary:Package} ${db:Status-Abbrev}\n"])
    return sorted(line.split()[0] for line in output.splitlines()
                  if len(line.split()) == 2 and line.split()[1] == "ii"
                  and RUNTIME_PACKAGE.fullmatch(line.split()[0].split(":")[0]))


def codex_state(path=Path("/usr/local/bin/codex")):
    if not path.exists() and not path.is_symlink():
        return {"kind": "absent"}
    metadata = path.lstat()
    return {"kind": "symlink" if path.is_symlink() else "file",
            "target": str(path.readlink()) if path.is_symlink() else None,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
            "uid": metadata.st_uid, "gid": metadata.st_gid,
            "mode": metadata.st_mode, "mtime_ns": metadata.st_mtime_ns}


def verify_codex_untouched(before, receipt):
    if "codex" in receipt or codex_state() != before:
        raise RuntimeError("AGPC installation must not install or change Codex")
    if (Path(receipt["runtime"]) / "codex").exists():
        raise RuntimeError("AGPC runtime generation contains a bundled Codex installation")


def main():
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux"
            or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
            or platform.machine() != "x86_64" or Path("/proc/1/comm").read_text().strip() != "systemd"):
        raise RuntimeError("This destructive installation check requires an ephemeral native GitHub Linux runner")
    root = Path(__file__).resolve().parents[1]
    output = root / ".cache/native-linux-acceptance"
    output.mkdir(parents=True, exist_ok=True)
    pins, provenance, files = publish_native.assemble(root)
    script = output / "agpc.sh"
    script.write_bytes(files["agpc.sh"])
    apps_script = output / "agpc-apps.sh"
    apps_script.write_bytes(files["agpc-apps.sh"])
    apps_plan = json.loads(command(["bash", str(apps_script), "install", "--dry-run", "--json"]))
    if {p["name"] for p in apps_plan["packages"]} != {"mdesk", "mlink", "ss-webos"}:
        raise RuntimeError("Unexpected application package plan")
    # Hosted development images make /usr/local/bin writable for tool setup.
    # Model a normal Ubuntu installation directory in this disposable runner;
    # retain the installer guard against user-writable privileged entrypoints.
    initial_bin_permissions = command(["stat", "-c", "%u:%g %a", "/usr/local/bin"]).strip()
    command(["sudo", "chown", "root:root", "/usr/local/bin"])
    command(["sudo", "chmod", "0755", "/usr/local/bin"])
    before = containers()
    codex_before = codex_state()
    plan = json.loads(command(["bash", str(script), "install", "--dry-run", "--json"]))
    if plan["architecture"] != "x86_64" or len(plan["packages"]) != 12 or plan["ready"] or "codex" in plan:
        raise RuntimeError("Unexpected installer plan")
    command(["sudo", "bash", str(script), "install"])
    receipt_path = Path("/usr/local/lib/agpc-native/install.json")
    first = json.loads(receipt_path.read_text())
    if first["state"] != "installed" or first["ready"] or first["packages"] != plan["packages"]:
        raise RuntimeError("Installation did not produce the expected receipt")
    verify_codex_untouched(codex_before, first)
    info = json.loads(command(["/usr/local/bin/agpc", "info", "--json"]))
    status = json.loads(command(["/usr/local/bin/agpc", "status", "--json"], expected=1))
    if info["ready"] or status["ready"] or status["state"] != "not-ready":
        raise RuntimeError("Installation incorrectly claimed AGPC readiness")
    if any(unit["state"] == "missing" for unit in status["services"]):
        raise RuntimeError("Native systemd registration missing")
    mcp = json.loads(command(["/usr/local/bin/agpc", "mcp", "list", "--json"]))
    command(["sudo", "/usr/sbin/sshd", "-t"])
    config = Path("/etc/mote/sphered/sphered-deb.env")
    command(["sudo", "sed", "-i", "$a# Native installer CI preservation marker", str(config)])
    expected_config = hashlib.sha256(config.read_bytes()).hexdigest()
    command(["sudo", "bash", str(script), "install"])
    second = json.loads(receipt_path.read_text())
    if second["state"] != "installed" or second["ready"]:
        raise RuntimeError("Reinstallation failed")
    if hashlib.sha256(config.read_bytes()).hexdigest() != expected_config:
        raise RuntimeError("Reinstallation changed an existing conffile")
    # Core-only installation owns uChat and does not install optional applications.
    if not {"uchat", "uchatd"} <= {p["name"] for p in plan["packages"]}:
        raise RuntimeError("uChat must remain in the core")
    core_receipt = receipt_path.read_bytes()
    command(["sudo", "bash", str(apps_script), "install"])
    apps_receipt_path = Path("/usr/local/lib/agpc-native/apps-install.json")
    apps_receipt = json.loads(apps_receipt_path.read_text())
    if apps_receipt["state"] != "installed" or apps_receipt["ready"] or apps_receipt["packages"] != apps_plan["packages"]:
        raise RuntimeError("Application installation receipt mismatch")
    for package in apps_plan["packages"]:
        installed = command(["dpkg-query", "-W", "-f=${Status}\t${Version}", package["name"]])
        if installed != "install ok installed\t" + package["version"]:
            raise RuntimeError("Application package version mismatch")
    for executable in ("/usr/bin/mdesk", "/usr/bin/mlink", "/usr/sbin/mlinkd",
                       "/usr/lib/ss-webos/node/bin/node",
                       "/usr/lib/ss-webos/runtime/node_modules/electron/dist/electron"):
        with open(executable, "rb") as stream:
            header = stream.read(20)
        if header[:6] != b"\x7fELF\x02\x01" or int.from_bytes(header[18:20], "little") != 62:
            raise RuntimeError("Application executable is not native x86-64: " + executable)
    apps_node = command(["/usr/lib/ss-webos/node/bin/node", "--version"]).strip()
    for unit in ("mdesk.service", "mlink.service", "ss-webosd.service"):
        command(["systemctl", "cat", unit])
    apps_config = Path("/etc/mote/ss-webos/ss-webos-deb.env")
    command(["sudo", "sed", "-i", "$a# Native apps installer CI preservation marker", str(apps_config)])
    expected_apps_config = hashlib.sha256(apps_config.read_bytes()).hexdigest()
    command(["sudo", "bash", str(apps_script), "install"])
    if json.loads(apps_receipt_path.read_text())["state"] != "installed":
        raise RuntimeError("Application reinstallation failed")
    if hashlib.sha256(apps_config.read_bytes()).hexdigest() != expected_apps_config:
        raise RuntimeError("Application reinstallation changed an existing conffile")
    if receipt_path.read_bytes() != core_receipt:
        raise RuntimeError("Application installer changed the core receipt")
    verify_codex_untouched(codex_before, second)
    if containers() != before:
        raise RuntimeError("Installation changed container runtime packages")
    result = {"schema": "agpc.native-linux-install-acceptance/v1", "release": pins["tag"],
              "entrypoint_sha256": provenance["files"]["agpc.sh"]["sha256"],
              "apps_entrypoint_sha256": provenance["files"]["agpc-apps.sh"]["sha256"],
              "apps_installation": "passed", "apps_reinstallation": "passed",
              "apps_conffile_preserved": True, "apps_receipt": apps_receipt,
              "apps_native_elf_checks": "passed", "ss_webos_node_version": apps_node,
              "os": platform.freedesktop_os_release(), "architecture": platform.machine(),
              "installation": "passed", "reinstallation": "passed", "conffile_preserved": True,
              "container_packages_unchanged": True, "codex_installed_by_agpc": False,
              "existing_codex_unchanged": True, "codex_before": codex_before,
              "runner_initial_bin_permissions": initial_bin_permissions,
              "runner_bin_permissions": "0:0 755",
              "mcp_discovery": mcp, "status": status,
              "ready": False, "arm64": "deferred", "windows_installation": "blocked: native runtime bundle unavailable"}
    (output / "evidence.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("release", "installation", "reinstallation", "codex_installed_by_agpc", "ready")}, indent=2))


if __name__ == "__main__":
    main()
