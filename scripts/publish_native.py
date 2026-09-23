#!/usr/bin/env python3
"""Publish pinned native entrypoints while preserving the existing APT site."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile

REPOSITORY = "motebus/download"
LIMIT = 64 * 1024 * 1024
SITE_LIMIT = 1000000000
NATIVE_FILES = {"agpc", "agpc.sh", "agpc-apps.sh", "agpc.exe", "agpc-arm64.exe", "agpc.source.json", "agpc-native-SHA256SUMS"}
CHANGED_PATHS = NATIVE_FILES | {name + ".asc" for name in NATIVE_FILES} | {"index.html"}
LINUX_BACKEND = {"agpc_linux.py", "codex_health.py", "native_rpc.py", "mcp_catalog.py", "native_install.py", "native_apps.py", "desktop_preferences.py", "rdp_client.py", "browser_cli.py", "browser_install.py", "browser/browser.cjs", "browser/package.json", "browser/package-lock.json"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def gh_json(path):
    return json.loads(subprocess.run(["gh", "api", path], capture_output=True, check=True).stdout)


def snapshot(site):
    result = {}
    for path in site.rglob("*"):
        require(not path.is_symlink(), "site symlinks are forbidden")
        if path.is_file():
            result[path.relative_to(site).as_posix()] = file_digest(path)
    return result


def verify_preservation(before, after):
    require({k: v for k, v in before.items() if k not in CHANGED_PATHS}
            == {k: v for k, v in after.items() if k not in CHANGED_PATHS},
            "publication changed an unrelated site file")


def current_pages():
    deployments = gh_json(f"repos/{REPOSITORY}/deployments?environment=github-pages&per_page=10")
    for deployment in deployments:
        statuses = gh_json(deployment["statuses_url"])
        if not statuses or statuses[0]["state"] != "success":
            continue
        match = re.fullmatch(r"https://github.com/motebus/download/actions/runs/(\d+)/job/\d+", statuses[0]["target_url"])
        require(match is not None, "current Pages deployment has no approved Actions run")
        run_id = int(match[1])
        run = gh_json(f"repos/{REPOSITORY}/actions/runs/{run_id}")
        require(run["conclusion"] == "success" and run["head_branch"] == "main", "Pages base must come from successful main CI")
        artifacts = gh_json(f"repos/{REPOSITORY}/actions/runs/{run_id}/artifacts")["artifacts"]
        matches = [a for a in artifacts if a["name"] == "github-pages" and not a["expired"]]
        require(len(matches) == 1, "current Pages artifact missing or expired; republish the approved site first")
        artifact = matches[0]
        require(re.fullmatch(r"sha256:[a-f0-9]{64}", artifact.get("digest", "")) is not None, "Pages artifact digest unavailable")
        require(0 < artifact["size_in_bytes"] < SITE_LIMIT, "Pages artifact size invalid")
        return {"deployment_id": deployment["id"], "run_id": run_id,
                "artifact_id": artifact["id"], "artifact_sha256": artifact["digest"][7:]}
    raise ValueError("no current successful Pages deployment")


def extract_site(archive_path, destination):
    require(not destination.exists(), "Pages restore destination must not exist")
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        require(len(entries) == 1 and entries[0].filename == "artifact.tar"
                and entries[0].file_size < SITE_LIMIT, "unexpected Pages artifact archive")
        with archive.open(entries[0]) as stream, tarfile.open(fileobj=stream, mode="r|*") as tar:
            destination.mkdir(parents=True)
            seen = set()
            size = 0
            for member in tar:
                path = PurePosixPath(member.name)
                require(not path.is_absolute() and ".." not in path.parts, "unsafe Pages path")
                require(member.isdir() or member.isfile(), "Pages links and special files are forbidden")
                if member.isdir():
                    continue
                name = path.as_posix()
                require(name not in seen, "duplicate Pages file")
                seen.add(name)
                size += member.size
                require(size < SITE_LIMIT, "expanded Pages artifact exceeds limit")
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)


def restore_current(site):
    record = current_pages()
    with tempfile.TemporaryDirectory(prefix="agpc-pages-base-") as folder:
        archive = Path(folder) / "site.zip"
        with archive.open("wb") as output:
            subprocess.run(["gh", "api", f"repos/{REPOSITORY}/actions/artifacts/{record['artifact_id']}/zip"], stdout=output, check=True)
        require(file_digest(archive) == record["artifact_sha256"], "Pages base archive digest mismatch")
        extract_site(archive, site)
    require(current_pages() == record, "Pages deployment changed during restore")
    return record


def fetch_release(tag, name, expected_hash):
    require(re.fullmatch(r"(?:agpc-native-v\d+\.\d+\.\d+-preview\.\d+|agpc-windows-v\d+\.\d+\.\d+-host-access-preview\.\d+)", tag) is not None, "exact preview tag required")
    require(re.fullmatch(r"[A-Za-z0-9_.-]+", name) is not None, "invalid release asset")
    url = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"
    with urllib.request.urlopen(url, timeout=120) as response:
        require(response.url.startswith("https://"), "release download must use HTTPS")
        data = response.read(LIMIT + 1)
    require(len(data) <= LIMIT and digest(data) == expected_hash, "native release asset digest mismatch")
    return data


def linux_sources(data, hashes):
    expected = {"agpc-linux/README.txt"} | {"agpc-linux/" + name for name in hashes}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        entries = archive.getmembers()
        require(len(entries) == len(expected) and {m.name for m in entries} == expected, "Linux asset inventory mismatch")
        require(all(m.isfile() for m in entries) and sum(m.size for m in entries) < LIMIT, "unsafe Linux asset")
        files = {m.name.removeprefix("agpc-linux/"): archive.extractfile(m).read() for m in entries}
    for name, expected_hash in hashes.items():
        require(digest(files[name]) == expected_hash, "Linux runtime payload changed")
    return {name.removeprefix("src/"): data for name, data in files.items() if name.startswith("src/")}


def standalone_linux(files, entrypoint="agpc.sh"):
    require(entrypoint in ("agpc.sh", "agpc-apps.sh"), "unapproved Linux entrypoint")
    module = "agpc_linux.py" if entrypoint == "agpc.sh" else "native_apps.py"
    require(set(files) == LINUX_BACKEND, "unexpected Linux backend modules")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            item = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, data)
    payload = output.getvalue()
    # A heredoc works both as a downloaded script and with bash reading a pipe.
    # The allowlisted runtime files are extracted verbatim into a private
    # temporary directory; normal return, errors and SystemExit all clean it up.
    return f'''#!/usr/bin/env bash
set -euo pipefail
# AGPC Native. No arguments select Ubuntu x86-64 installation.
# Requires native Linux, Bash and Python 3.10+; use explicit status for diagnostics.
exec python3 - "$@" <<'PY_AGPC_NATIVE'
import base64, hashlib, io, pathlib, runpy, sys, tempfile, zipfile
if sys.version_info < (3, 10):
    raise SystemExit("AGPC Native requires Python 3.10 or newer")
payload = base64.b64decode({base64.b64encode(payload).decode()!r}, validate=True)
if hashlib.sha256(payload).hexdigest() != {digest(payload)!r}:
    raise SystemExit("AGPC Native embedded payload checksum mismatch")
with tempfile.TemporaryDirectory(prefix="agpc-native-") as directory:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if len(archive.namelist()) != {len(files)} or set(archive.namelist()) != set({sorted(files)!r}):
            raise SystemExit("AGPC Native embedded file inventory mismatch")
        for name in archive.namelist():
            pathlib.Path(directory, name).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(directory, name).write_bytes(archive.read(name))
    sys.dont_write_bytecode = True
    sys.path.insert(0, directory)
    sys.argv[0] = {entrypoint!r}
    runpy.run_path(str(pathlib.Path(directory, {module!r})), run_name="__main__")
PY_AGPC_NATIVE
'''.encode()


def windows_executable(data, expected_hash, machine):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        require(len(entries) == 2 and {m.filename for m in entries} == {"agpc.exe", "README.txt"}, "Windows asset inventory mismatch")
        require(all(not stat.S_ISLNK(m.external_attr >> 16) for m in entries)
                and sum(m.file_size for m in entries) < LIMIT, "unsafe Windows archive")
        executable = archive.read("agpc.exe")
    return validate_windows_executable(executable, expected_hash, machine)


def validate_windows_executable(executable, expected_hash, machine):
    require(digest(executable) == expected_hash and executable[:2] == b"MZ" and len(executable) > 96, "Windows executable digest/header mismatch")
    offset = struct.unpack_from("<I", executable, 60)[0]
    require(offset < len(executable) - 96 and executable[offset:offset + 4] == b"PE\0\0"
            and struct.unpack_from("<H", executable, offset + 4)[0] == machine,
            "Windows executable CPU mismatch")
    return executable


def macos_executable(data, expected_hash):
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        entries = archive.getmembers()
        require(len(entries) == 2 and {m.name for m in entries} == {"agpc", "README.txt"}, "macOS asset inventory mismatch")
        require(all(m.isfile() for m in entries) and sum(m.size for m in entries) < LIMIT, "unsafe macOS archive")
        require(archive.getmember("agpc").mode == 0o755, "macOS executable mode mismatch")
        executable = archive.extractfile("agpc").read()
    require(digest(executable) == expected_hash, "macOS executable digest mismatch")
    require(len(executable) >= 32 and executable[:4] == b"\xcf\xfa\xed\xfe", "Mach-O 64-bit executable required")
    cpu, subtype, kind, commands, command_bytes = struct.unpack_from("<IIIII", executable, 4)
    require(cpu == 0x0100000C and kind == 2, "native ARM64 Mach-O executable required")
    require(commands > 0 and commands * 8 <= command_bytes <= len(executable) - 32, "invalid Mach-O load commands")
    return executable


def windows_host_preview(pin):
    require(set(pin) == {"tag", "manifest_sha256", "sha256", "bytes"}, "invalid Windows preview pin")
    require(re.fullmatch(r"agpc-windows-v\d+\.\d+\.\d+-host-access-preview\.\d+", pin["tag"]) is not None, "invalid Windows host tag")
    manifest = json.loads(fetch_release(pin["tag"], "MANIFEST.json", pin["manifest_sha256"]))
    require(manifest["schema"] == "agpc.windows-public-preview/v1"
            and manifest["platform"] == "windows" and manifest["architecture"] == "x86_64"
            and pin["tag"] == "agpc-windows-v" + manifest["version"]
            and manifest["artifact"] == {"name": "agpc.exe", "bytes": pin["bytes"], "sha256": pin["sha256"]},
            "Windows host manifest mismatch")
    executable = fetch_release(pin["tag"], "agpc.exe", pin["sha256"])
    require(len(executable) == pin["bytes"], "Windows host size mismatch")
    return validate_windows_executable(executable, pin["sha256"], 0x8664), manifest


def assemble(root):
    pins = json.loads((root / "scripts/native-pages.json").read_text())
    require(pins["schema"] == "agpc.native-pages-inputs/v1" and pins["repository"] == REPOSITORY, "unapproved native Pages source")
    manifest_bytes = fetch_release(pins["tag"], "MANIFEST.json", pins["manifest_sha256"])
    manifest = json.loads(manifest_bytes)
    require(manifest["tag"] == pins["tag"] and manifest["prerelease"] is True
            and manifest["assets"] == pins["assets"] and manifest["payload_sha256"] == pins["payload_sha256"], "native release provenance mismatch")
    version = manifest["version"]
    archives = {name: fetch_release(pins["tag"], name, item["sha256"]) for name, item in pins["assets"].items()}
    linux = linux_sources(archives[f"agpc-linux-{version}.tar.gz"], pins["payload_sha256"]["linux"])
    files = {name: standalone_linux(linux, name) for name in ("agpc.sh", "agpc-apps.sh")}
    for cpu, machine, name in [("x86_64", 0x8664, "agpc.exe"), ("arm64", 0xAA64, "agpc-arm64.exe")]:
        files[name] = windows_executable(archives[f"agpc-win-{cpu}-{version}.zip"], pins["payload_sha256"]["windows"][cpu], machine)
    files["agpc"] = macos_executable(archives[f"agpc-mac-arm64-{version}.tar.gz"], pins["payload_sha256"]["macos"]["arm64"])
    windows_host = None
    if "windows_x86_64" in pins:
        files["agpc.exe"], windows_host = windows_host_preview(pins["windows_x86_64"])
    record = {"schema": "agpc.native-pages/v1", "version": version,
              "release": f"https://github.com/{REPOSITORY}/releases/tag/{pins['tag']}",
              "manifest_sha256": pins["manifest_sha256"], "windows_authenticode_signed": False,
              "macos_developer_id_signed": False, "macos_notarized": False, "macos_runtime_ready": False,
              "linux_backend_sha256": pins["payload_sha256"]["linux"],
              "files": {name: {"sha256": digest(data), "bytes": len(data), "cpu": "arm64,x86_64" if name == "agpc.sh" else "arm64" if name in ("agpc", "agpc-arm64.exe") else "x86_64"} for name, data in files.items()}}
    if windows_host is not None:
        record["windows_x86_64"] = {"release": f"https://github.com/{REPOSITORY}/releases/tag/{pins['windows_x86_64']['tag']}",
                                    "manifest_sha256": pins["windows_x86_64"]["manifest_sha256"], "manifest": windows_host}
    files["agpc.source.json"] = (json.dumps(record, indent=2) + "\n").encode()
    files["agpc-native-SHA256SUMS"] = "".join(f"{digest(data)}  {name}\n" for name, data in sorted(files.items())).encode()
    return pins, record, files


def sign_files(root, site):
    passphrase = os.environ.get("MEDGE_APT_SIGNING_PASSPHRASE")
    require(bool(passphrase), "archive signing passphrase unavailable")
    fingerprint = (root / "medge-archive-keyring.fingerprint").read_text().strip()
    # The tracked fingerprint includes the same whitespace accepted by GPG.
    fingerprint = "".join(fingerprint.split())
    require(re.fullmatch(r"[A-F0-9]{40}", fingerprint) is not None, "invalid archive key fingerprint")
    for name in sorted(NATIVE_FILES):
        subprocess.run(["gpg", "--batch", "--yes", "--pinentry-mode", "loopback", "--passphrase-fd", "0",
                        "--local-user", fingerprint, "--digest-algo", "SHA256", "--armor", "--detach-sign",
                        "--output", str(site / (name + ".asc")), str(site / name)], input=passphrase + "\n", text=True, check=True)
        subprocess.run(["gpgv", "--keyring", str((root / "medge-archive-keyring.gpg").resolve()),
                        str(site / (name + ".asc")), str(site / name)], check=True)


def overlay(root, site, evidence_path, base=None):
    before = snapshot(site)
    pins, record, files = assemble(root)
    require(before.get("agent-sphere-apps.sh") == pins["debian_installer_sha256"], "existing Debian installer differs from reviewed baseline")
    for name, data in files.items():
        (site / name).write_bytes(data)
        (site / name).chmod(0o755 if name == "agpc" or name.endswith((".sh", ".exe")) else 0o644)
    (site / "index.html").write_bytes((root / "scripts/native-index.html").read_bytes())
    sign_files(root, site)
    after = snapshot(site)
    verify_preservation(before, after)
    result = {"schema": "agpc.native-pages-evidence/v1", "base": base,
              "native": record, "changed_paths": sorted(k for k in after if before.get(k) != after[k]),
              "preserved_files": len(set(before) - CHANGED_PATHS),
              "preserved_inventory_sha256": digest(json.dumps({k: v for k, v in before.items() if k not in CHANGED_PATHS}, sort_keys=True).encode()),
              "published_sha256": {name: after[name] for name in sorted(CHANGED_PATHS)}}
    evidence_path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"native": record["version"], "preserved_files": result["preserved_files"], "changed_paths": result["changed_paths"]}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["restore-and-overlay", "overlay"])
    parser.add_argument("root", type=Path)
    parser.add_argument("site", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    base = restore_current(args.site) if args.command == "restore-and-overlay" else None
    overlay(args.root, args.site, args.evidence, base)
    if base:
        require(current_pages() == base, "Pages deployment changed before promotion")


if __name__ == "__main__":
    main()
