#!/usr/bin/env python3
"""Install the reviewed candidate on an ephemeral native GitHub Ubuntu runner."""
import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import datetime
import http.server
import threading
import uuid
import socket
import shutil
import subprocess
import tempfile
import urllib.request

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


def management_snapshot():
    result = {}
    for package in ("medge", "agpc-manager"):
        status = subprocess.run(["dpkg-query", "-W", "-f=${Status}\t${Version}", package], capture_output=True, text=True)
        if status.returncode == 0 and status.stdout.startswith("install ok installed\t"):
            conffiles = command(["dpkg-query", "-W", "-f=${Conffiles}", package])
            files = {}
            for line in conffiles.splitlines():
                if line.strip():
                    path = Path(line.split()[0])
                    file_status = subprocess.run(["sudo", "test", "-f", str(path)], check=False)
                    if file_status.returncode not in (0, 1):
                        raise RuntimeError("Cannot inspect protected conffile: " + str(path))
                    if file_status.returncode == 0:
                        files[str(path)] = command(["sudo", "sha256sum", str(path)]).split()[0]
            result[package] = {"version":status.stdout.split("\t")[1], "configuration_sha256":files}
    return result


def install_legacy_fixture(root):
    fixture = json.loads((root / "scripts/native-migration-fixture.json").read_text())
    with tempfile.TemporaryDirectory(prefix="agpc-legacy-fixture-") as folder:
        packages = []
        for name, digest in fixture["packages"].items():
            with urllib.request.urlopen(fixture["release"] + name, timeout=60) as response:
                data = response.read(256 * 1024 * 1024 + 1)
            if hashlib.sha256(data).hexdigest() != digest:
                raise RuntimeError("Legacy fixture checksum mismatch: " + name)
            path = Path(folder) / name
            path.write_bytes(data)
            packages.append(str(path))
        command(["sudo", "apt-get", "update"])
        command(["sudo", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "-y", "--no-remove", "--no-install-recommends", "install", *packages])
    marker = Path("/etc/mote/medge/medge-deb.env")
    command(["sudo", "sed", "-i", "$a# AGPC management preservation marker", str(marker)])
    before = management_snapshot()
    if set(before) != {"medge", "agpc-manager"}:
        raise RuntimeError("Legacy fixture lacks protected management packages")
    return before


def verify_standalone_mcp(catalog):
    forbidden = {"codex_mesh_inbox", "codex_mesh_send", "codex_mesh_status", "medge_mdrive", "medge_status", "tg_send"}
    if catalog["binary"] != "/usr/bin/mote-mcp-ultra" or {x["name"] for x in catalog["tools"]} & forbidden:
        raise RuntimeError("Unexpected MCP provider or legacy tool exposure")
    status = subprocess.run(["dpkg-query", "-W", "-f=${Status}", "mote-mcpd"], capture_output=True, text=True)
    if Path("/etc/codex/skills/codex-mesh/SKILL.md").exists():
        raise RuntimeError("Retired CX MCP skill remains active")
    if status.stdout.strip() == "install ok installed":
        raise RuntimeError("Legacy MCP gateway remains installed")


def verify_browser(receipt, output):
    browser = receipt["browser"]
    user = pwd.getpwuid(os.getuid()).pw_name
    if browser.get("installed") is not True or browser["setup_user"] != user or browser["remote_ready"]:
        raise RuntimeError("P Channel was not set up for the normal installing user")
    doctor = json.loads(command(["/usr/local/bin/agpc", "browser", "doctor"]))
    if doctor.get("installed") is not True or doctor["engine_version"] != "1.63.0":
        raise RuntimeError("Installed P engine failed its diagnostic")
    if browser.get("mode") != "headless" or browser.get("mode_selection") != "agent":
        raise RuntimeError("Installer omitted Agent mode defaults")
    if doctor.get("defaults", {}).get("mode") != "headless" or doctor.get("modes") != ["headless", "headed"]:
        raise RuntimeError("Browser mode defaults missing from installed engine")
    # Virtual display belongs only to this disposable CI runner, not AGPC install.
    if not shutil.which("xvfb-run"):
        raise RuntimeError("Headed acceptance requires the CI virtual display")
    class Fixture(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'<input id="name"><button id="commit" onclick="document.querySelector(\'#done\').textContent=document.querySelector(\'#name\').value">Save</button><p id="done">waiting</p>'
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers(); self.wfile.write(body)
        def log_message(self, *_):
            pass
    server = http.server.HTTPServer(("127.0.0.1", 0), Fixture)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        origin = f"http://127.0.0.1:{server.server_port}"
        with tempfile.TemporaryDirectory(prefix="agpc-p-acceptance-") as directory:
            policy, request = Path(directory) / "policy.json", Path(directory) / "request.json"
            policy.write_text(json.dumps({"schema": "agpc.browser.policy/v2", "id": "native-install-ci", "subject": user,
                "expires_at": (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=3)).isoformat(),
                "chrome_path": browser["chrome_path"], "allowed_origins": [origin],
                "allowed_actions": ["navigate", "fill", "click", "verify"], "timeout_ms": 60000}))
            policy.chmod(0o600)
            for mode in ("headless", "headed"):
                request.write_text(json.dumps({"schema": "agpc.browser.request/v2", "id": "native-ci-" + uuid.uuid4().hex,
                    "agent_id": "ci-agent", "task_id": "native-install", "intent": {"observe": mode == "headed"},
                    "steps": [{"action": "navigate", "url": origin + "/"}, {"action": "fill", "selector": "#name", "value": "p-channel-ci"},
                        {"action": "click", "selector": "#commit"}, {"action": "verify", "selector": "#done", "text": "p-channel-ci"}]}))
                plan = json.loads(command(["/usr/local/bin/agpc", "browser", "plan", str(policy), str(request)]))
                if plan["mode"] != mode or plan["selected_by"] != "agent" or plan["execution"] != "plan-only":
                    raise RuntimeError("Agent did not select the expected mode")
                args = ["/usr/local/bin/agpc", "browser", "run", str(policy), str(request)]
                if mode == "headed":
                    args = ["xvfb-run", "--auto-servernum", *args]
                result = json.loads(command(args))
                if result["status"] != "completed" or not result["verified"] or result["remote_ready"]:
                    raise RuntimeError("Installed native P browser operation was not verified")
                if result["session"]["mode"] != mode or result["session"]["profile"] != "isolated-agent" or result["mode_decision"] != plan:
                    raise RuntimeError("Mode/session evidence did not match the Agent plan")
                (output / f"browser-{mode}-execution.json").write_text(json.dumps(result, indent=2) + "\n")
    finally:
        server.shutdown(); server.server_close(); worker.join()


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
    # Hosted runner tool setup also makes /usr/share world-writable. Record it
    # before installation and model ordinary Ubuntu ownership, retaining the
    # provider's rejection of untrusted package/configuration ancestors.
    initial_share_permissions = command(["stat", "-c", "%u:%g %a", "/usr/share"]).strip()
    command(["sudo", "chown", "root:root", "/usr/share"])
    command(["sudo", "chmod", "0755", "/usr/share"])
    before = containers()
    codex_before = codex_state()
    migration = os.environ.get("AGPC_TEST_LEGACY_MIGRATION") == "1"
    protected_before = install_legacy_fixture(root) if migration else management_snapshot()
    plan = json.loads(command(["bash", str(script), "install", "--dry-run", "--json"]))
    if plan["architecture"] != "x86_64" or len(plan["packages"]) != 12 or plan["ready"] or "codex" in plan:
        raise RuntimeError("Unexpected installer plan")
    command(["sudo", "bash", str(script), "install"])
    receipt_path = Path("/usr/local/lib/agpc-native/install.json")
    first = json.loads(receipt_path.read_text())
    if first["state"] != "installed" or first["ready"] or first["packages"] != plan["packages"]:
        raise RuntimeError("Installation did not produce the expected receipt")
    verify_codex_untouched(codex_before, first)
    verify_browser(first, output)
    info = json.loads(command(["/usr/local/bin/agpc", "info", "--json"]))
    status = json.loads(command(["/usr/local/bin/agpc", "status", "--json"], expected=1))
    if info["ready"] or status["ready"] or status["state"] != "not-ready":
        raise RuntimeError("Installation incorrectly claimed AGPC readiness")
    if any(unit["state"] == "missing" for unit in status["services"]):
        raise RuntimeError("Native systemd registration missing")
    # Report only package permissions/loader diagnostics, never configuration contents.
    for target in ("/usr/bin/mote-mcp-ultra", "/usr/lib/mote-mcp/providers/ultra/libmote_mcp_ultra.so",
                   "/usr/share/mote-mcp/providers/ultra/manifest.json", "/etc/mote-mcp-ultra/policy.json"):
        print(command(["namei", "-l", target]), flush=True)
    print(command(["/usr/bin/mote-mcp-ultra", "doctor"]), flush=True)
    mcp = json.loads(command(["/usr/local/bin/agpc", "mcp", "list", "--json"]))
    verify_standalone_mcp(mcp)
    for package in ("freerdp3-x11", "remmina", "remmina-plugin-rdp"):
        state = command(["dpkg-query", "-W", "-f=${Status}", package]).strip()
        if state != "install ok installed":
            raise RuntimeError(f"RDP client package missing: {package}")
    command(["test", "-x", "/usr/bin/xfreerdp3"])
    if plan["rdp_client"]["default"] != "xfreerdp3":
        raise RuntimeError("FreeRDP is not the default installed client")
    desktop = json.loads(command(["/usr/local/bin/agpc", "desktop", "--json"]))
    if desktop["desktop"] != "xrdp" or desktop["client"] != "freerdp" or desktop["connection_opened"]:
        raise RuntimeError("Unexpected desktop preference defaults")
    command(["test", "-x", "/usr/bin/remmina"])
    plugin_paths = [p for p in command(["dpkg-query", "-L", "remmina-plugin-rdp"]).splitlines()
                    if p.endswith("remmina-plugin-rdp.so")]
    if len(plugin_paths) != 1:
        raise RuntimeError("RDP client plugin missing or ambiguous")
    for binary in ("/usr/bin/xfreerdp3", "/usr/bin/remmina", plugin_paths[0]):
        header = Path(binary).read_bytes()[:20]
        if header[:6] != b"\x7fELF\x02\x01" or int.from_bytes(header[18:20], "little") != 62:
            raise RuntimeError("RDP client/plugin is not native x86-64 ELF")
    host = first["rdp_host"]
    if host["host"] != "127.0.0.1" or host["security"] != "tls" or not host["enabled"]:
        raise RuntimeError("Invalid RDP host installation receipt")
    for unit in ("xrdp.service", "xrdp-sesman.service"):
        command(["systemctl", "is-active", "--quiet", unit])
    command(["systemctl", "is-enabled", "--quiet", "xrdp.service"])
    sockets = command(["ss", "-H", "-ltn", "sport", "=", f":{host['port']}"])
    if [line.split()[3] for line in sockets.splitlines()] != [f"127.0.0.1:{host['port']}"]:
        raise RuntimeError("RDP host is not restricted to loopback")
    if management_snapshot() != protected_before:
        raise RuntimeError("Management packages or configuration changed")
    command(["sudo", "/usr/sbin/sshd", "-t"])
    config = Path("/etc/mote/sphered/sphered-deb.env")
    command(["sudo", "sed", "-i", "$a# Native installer CI preservation marker", str(config)])
    expected_config = hashlib.sha256(config.read_bytes()).hexdigest()
    with socket.socket() as port_probe:
        port_probe.bind(("127.0.0.1", 0))
        custom_rdp_port = port_probe.getsockname()[1]
    rdp_configuration = Path("/etc/xrdp/xrdp.ini")
    command(["sudo", "sed", "-i", f"s#^port=tcp://127[.]0[.]0[.]1:{host['port']}$#port=tcp://127.0.0.1:{custom_rdp_port}#", str(rdp_configuration)])
    command(["sudo", "sed", "-i", "$a# AGPC RDP conffile preservation marker", str(rdp_configuration)])
    expected_rdp_configuration = hashlib.sha256(rdp_configuration.read_bytes()).hexdigest()
    command(["sudo", "bash", str(script), "install"])
    second = json.loads(receipt_path.read_text())
    if second["rdp_host"]["port"] != custom_rdp_port:
        raise RuntimeError("Installer ignored the configured RDP port")
    if hashlib.sha256(rdp_configuration.read_bytes()).hexdigest() != expected_rdp_configuration:
        raise RuntimeError("RDP reinstallation changed unrelated server configuration")
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
    if management_snapshot() != protected_before:
        raise RuntimeError("Management packages changed during reinstallation or app installation")
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
              "runner_initial_share_permissions": initial_share_permissions,
              "runner_share_permissions": "0:0 755",
              "mcp_discovery": mcp, "status": status, "legacy_migration": migration,
              "management_preserved": True, "management_before": protected_before,
              "ready": False, "arm64": "deferred", "windows_installation": "blocked: native runtime bundle unavailable"}
    (output / "evidence.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("release", "installation", "reinstallation", "codex_installed_by_agpc", "ready")}, indent=2))


if __name__ == "__main__":
    main()
