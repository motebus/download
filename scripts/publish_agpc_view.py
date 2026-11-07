#!/usr/bin/env python3
"""Publish exact main-CI View bytes with archive signatures; never install them."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import struct
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPO = "motebus/download"
VERSION = "0.1.0-6"
TAG = "agpc-view-v" + VERSION
PACKAGE = "agpc-view_" + VERSION + "_amd64.deb"
ASSETS = {PACKAGE, "MANIFEST.json", "SHA256SUMS"}
FINGERPRINT = "AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0"
LIMIT = 2 * 1024 * 1024
PAYLOAD_LIMIT = 4 * 1024 * 1024
PAYLOAD = {
    "usr/bin/agpc-view", "usr/share/applications/agpc-view.desktop",
    "usr/share/icons/hicolor/scalable/apps/agpc-view.svg",
    *("usr/share/doc/agpc-view/" + name for name in (
        "README.md", "SPEC.md", "copyright", "THIRD-PARTY-NOTICES.txt", "PROVENANCE.json")),
}
SOURCE_FILES = {
    "src/agpc_view_component.py",
    *("components/agpc-view/" + name for name in (
        "Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "README.md", "SPEC.md",
        "src/keys.rs", "src/backend.rs", "src/gtk.rs", "src/main.rs", "src/local.rs", "src/mode.rs", "src/sso.rs", "assets/agpc-view.desktop",
        "assets/agpc-view.svg", "assets/style.css", "assets/copyright",
        "assets/THIRD-PARTY-NOTICES.txt", "scripts/build-deb.py", "scripts/test-package.py")),
}
DEPENDENCIES = ["agpc-key-manager (= 0.1.0-2)", "agpc-mesh (>= 3.0.0-3)", "agpc-mesh (<< 4)", "libgtk-4-1 (>= 4.8)",
                "libc6 (>= 2.39)", "libgcc-s1", "libglib2.0-0t64"]
IDENTITY = {"name": "agpc-view", "version": VERSION, "architecture": "amd64"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def read_json(data):
    require(len(data) <= LIMIT, "oversized JSON")
    return json.loads(data, object_pairs_hook=unique_pairs)


def run(*args, **kwargs):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.PIPE,
                                       timeout=60, **kwargs).strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise RuntimeError("publication command failed: " + args[0]) from None


def validate_record(record):
    require(set(record) == {"schema", "tag", "package", "version", "architecture", "source_project",
                            "source_commit", "source_ref", "pipeline_id", "job_id", "gui_job_id",
                            "pipeline_status", "producer_manifest_sha256", "candidate_tag", "assets", "notes"},
            "unexpected publication record fields")
    require(record["schema"] == "agpc-view.publication-inputs/v1"
            and record["tag"] == TAG and record["package"] == PACKAGE
            and record["version"] == VERSION and record["architecture"] == "amd64",
            "unreviewed View package identity")
    require(record["source_project"] == 1336 and record["source_ref"] == "main"
            and record["pipeline_status"] == "success", "successful canonical main producer required")
    require(re.fullmatch(r"[0-9a-f]{40}", record["source_commit"]) is not None, "exact source commit required")
    require(re.fullmatch(r"[0-9a-f]{64}", record["producer_manifest_sha256"]) is not None,
            "exact producer manifest digest required")
    require(all(type(record[k]) is int and record[k] > 0 for k in ("pipeline_id", "job_id", "gui_job_id"))
            and record["job_id"] != record["gui_job_id"], "distinct native and GUI job IDs required")
    require(record["candidate_tag"] == "candidate-" + TAG, "exact View candidate tag required")
    require(set(record["assets"]) == ASSETS, "unexpected public asset inventory")
    for name, item in record["assets"].items():
        require(set(item) == {"sha256", "bytes"}
                and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is not None
                and type(item["bytes"]) is int and 0 < item["bytes"] <= LIMIT,
                "invalid asset pin: " + name)
    require(isinstance(record["notes"], str) and 0 < len(record["notes"]) < 10000, "release notes required")
    require("gitlab" not in encoded(record).decode().lower(), "private URL/reference in public inputs")


def check_jobs(record, pipeline, native, gui):
    require(pipeline["id"] == record["pipeline_id"] and pipeline["status"] == "success"
            and pipeline["ref"] == "main" and pipeline["sha"] == record["source_commit"],
            "canonical main pipeline not successful")
    for job, key, name in ((native, "job_id", "agpc-view-native"), (gui, "gui_job_id", "agpc-view-gui-native")):
        require(job["id"] == record[key] and job["name"] == name and job["status"] == "success"
                and job["ref"] == "main" and job["commit"]["id"] == record["source_commit"]
                and job["pipeline"]["id"] == record["pipeline_id"]
                and job["pipeline"]["sha"] == record["source_commit"]
                and job["pipeline"]["ref"] == "main"
                and job.get("allow_failure") is False, "required successful main job missing: " + name)


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        before, after = urllib.parse.urlsplit(request.full_url), urllib.parse.urlsplit(newurl)
        require((before.scheme, before.netloc) == (after.scheme, after.netloc),
                "cross-origin authenticated API redirect refused")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def api_reader():
    source = urllib.parse.urlsplit(os.environ["AGPC_GITLAB_SOURCE_URL"])
    require(source.scheme == "https" and source.netloc == "gitlab.ypcloud.com"
            and source.path == "/codex/codex-agpc/agpc-download-source.git"
            and not source.query and not source.fragment, "unexpected canonical source URL")
    base = source.scheme + "://" + source.netloc + "/api/v4/projects/1336"
    opener = urllib.request.build_opener(SameOriginRedirect())
    def get(path):
        request = urllib.request.Request(base + path, headers={"PRIVATE-TOKEN": os.environ["AGPC_GITLAB_READ_TOKEN"]})
        try:
            with opener.open(request, timeout=30) as response:
                data = response.read(LIMIT + 1)
        except Exception:
            raise RuntimeError("canonical producer API request failed") from None
        require(len(data) <= LIMIT, "oversized producer response")
        return data
    return get


def fresh_main(record, get=None):
    get = get or api_reader()
    require(read_json(get("/repository/branches/main"))["commit"]["id"] == record["source_commit"],
            "source main advanced")
    check_jobs(record, read_json(get("/pipelines/" + str(record["pipeline_id"]))),
               read_json(get("/jobs/" + str(record["job_id"]))),
               read_json(get("/jobs/" + str(record["gui_job_id"]))))
    prefix = "/jobs/" + str(record["job_id"]) + "/artifacts/components/agpc-view/dist/"
    deb = get(prefix + PACKAGE)
    require(len(deb) == record["assets"][PACKAGE]["bytes"]
            and sha(deb) == record["assets"][PACKAGE]["sha256"], "original CI package differs from reviewed asset")
    original = get(prefix + "manifest.json")
    require(sha(original) == record["producer_manifest_sha256"], "original CI manifest differs")
    require(read_json(original)["sha256"] == sha(deb), "CI manifest/package mismatch")
    require(json.loads(run("gh", "api", f"repos/{REPO}/branches/main"))["commit"]["sha"]
            == os.environ["GITHUB_SHA"], "publisher main advanced")
    return original


def tar_files(package, control=False):
    directories = {"."}
    if not control:
        directories.update(parent.as_posix() for name in PAYLOAD for parent in PurePosixPath(name).parents)
    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * LIMIT, 16 * LIMIT))
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(["dpkg-deb", "--ctrl-tarfile" if control else "--fsys-tarfile", str(package)],
                                stdout=output, stderr=subprocess.DEVNULL, preexec_fn=limits, timeout=30)
        require(result.returncode == 0 and output.tell() <= 16 * LIMIT, "invalid or oversized DEB archive")
        output.seek(0)
        files, seen = {}, set()
        with tarfile.open(fileobj=output, mode="r:") as archive:
            for member in archive:
                path = PurePosixPath(member.name)
                require(not path.is_absolute() and ".." not in path.parts
                        and (member.isdir() or member.isfile()), "unsafe DEB entry")
                name = path.as_posix()
                require(name not in seen, "duplicate DEB entry")
                seen.add(name)
                require(member.uid == member.gid == 0 and not member.mode & 0o7000, "unsafe DEB ownership/mode")
                if member.isdir():
                    require(name in directories and member.mode == 0o755, "unreviewed package directory")
                else:
                    require(member.size <= PAYLOAD_LIMIT, "oversized DEB file")
                    files[name] = (archive.extractfile(member).read(), member.mode)
        return files


def validate_build(package, build, record):
    require(set(build) == {"schema", "package", "filename", "sha256", "bytes", "dependencies",
                           "files", "provenance", "release_admitted"}, "unexpected sanitized build manifest fields")
    require(build["schema"] == "agpc-view.package-manifest/v1" and build["package"] == IDENTITY
            and build["filename"] == PACKAGE and build["sha256"] == sha(package.read_bytes())
            and build["bytes"] == package.stat().st_size and build["dependencies"] == DEPENDENCIES
            and build["release_admitted"] is False, "producer package binding mismatch")
    controls = tar_files(package, control=True)
    require(set(controls) == {"control", "md5sums"}, "maintainer scripts or unexpected control payload")
    control = controls["control"][0].decode()
    for key, value in (("Package", "agpc-view"), ("Version", VERSION), ("Architecture", "amd64"),
                       ("Depends", ", ".join(DEPENDENCIES))):
        require(re.findall(r"^" + key + r": (.*)$", control, re.M) == [value], "package control mismatch: " + key)
    require(not re.search(r"^(?:Pre-Depends|Conflicts|Breaks|Replaces|Provides|Essential):", control, re.M),
            "unreviewed package relationship")
    payload = tar_files(package)
    require(set(payload) == set(build["files"]) == PAYLOAD, "unreviewed package payload inventory")
    checksums = "".join(hashlib.md5(payload[name][0]).hexdigest() + "  " + name + "\n" for name in sorted(payload))
    require(controls["md5sums"][0].decode() == checksums, "package checksum inventory mismatch")
    for name, (data, mode) in payload.items():
        expected_mode = 0o755 if name == "usr/bin/agpc-view" else 0o644
        require(mode == expected_mode and build["files"][name] == {
            "bytes": len(data), "sha256": sha(data), "mode": format(mode, "04o"), "uid": 0, "gid": 0},
            "payload binding mismatch: " + name)
    proof = read_json(payload["usr/share/doc/agpc-view/PROVENANCE.json"][0])
    require(proof == build["provenance"] and proof["schema"] == "agpc-view.build-provenance/v1"
            and proof["package"] == IDENTITY and proof["release_admitted"] is False
            and proof["runtime_ready"] is False, "embedded provenance mismatch")
    source = proof["source"]
    require(source["project"] == 1336 and source["base_commit"] == record["source_commit"]
            and source["dirty_candidate"] is False and set(source["files"]) == SOURCE_FILES
            and source["tree_sha256"] == sha(encoded(source["files"])), "clean exact source binding required")
    for item in source["files"].values():
        require(set(item) == {"sha256", "bytes"} and type(item["bytes"]) is int and item["bytes"] > 0
                and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is not None, "invalid source file pin")
    binary = payload["usr/bin/agpc-view"][0]
    require(len(binary) >= 64 and binary[:6] == b"\x7fELF\x02\x01"
            and struct.unpack_from("<H", binary, 18)[0] == 62
            and struct.unpack_from("<H", binary, 16)[0] in (2, 3)
            and proof["binary"]["sha256"] == sha(binary) and proof["binary"]["bytes"] == len(binary),
            "native ELF/binary provenance mismatch")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "agpc-view"
        path.write_bytes(binary)
        segments = run("readelf", "--program-headers", str(path))
        dynamic = run("readelf", "--dynamic", str(path))
        versions = run("readelf", "--version-info", str(path))
    needed = sorted(set(re.findall(r"\(NEEDED\).*\[([^]]+)\]", dynamic)))
    abi = proof["binary"]["abi"]
    require("[Requesting program interpreter: /lib64/ld-linux-x86-64.so.2]" in segments
            and "(RPATH)" not in dynamic and "(RUNPATH)" not in dynamic
            and needed == ["libc.so.6", "libgcc_s.so.1", "libgio-2.0.so.0", "libglib-2.0.so.0", "libgobject-2.0.so.0", "libgtk-4.so.1"]
            and abi["needed"] == needed and abi["format"] == "ELF64" and abi["machine"] == "x86-64"
            and abi["interpreter"] == "/lib64/ld-linux-x86-64.so.2", "unreviewed native ABI")
    floors = [tuple(map(int, version.split("."))) for version in re.findall(r"\bGLIBC_(\d+(?:\.\d+)+)\b", versions)]
    require(floors and max(floors) == (2, 39) and "GLIBC_PRIVATE" not in versions
            and abi["glibc_minimum"] == "2.39", "unreviewed glibc dependency")
    desktop = payload["usr/share/applications/agpc-view.desktop"][0].decode().splitlines()
    require(all(desktop.count(line) == 1 for line in (
        "Type=Application", "Exec=agpc-view", "Terminal=false", "Icon=agpc-view")), "native desktop entry mismatch")


def manifest_for(record, build):
    return {"schema": "agpc-view.release-manifest/v1", "source_project": 1336,
            "source_commit": record["source_commit"], "source_ref": "main",
            "pipeline_id": record["pipeline_id"], "job_id": record["job_id"],
            "gui_job_id": record["gui_job_id"], "tag": TAG, "package": IDENTITY,
            "sha256": build["sha256"], "bytes": build["bytes"], "build": build,
            "runtime_ready": False, "core_all_admitted": False}


def validate_bundle(stage, record, original=None):
    require({p.name for p in stage.iterdir()} == ASSETS, "unexpected candidate bundle files")
    for name, pin in record["assets"].items():
        path = stage / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == pin["bytes"]
                and sha(path.read_bytes()) == pin["sha256"], "candidate asset mismatch: " + name)
    manifest = read_json((stage / "MANIFEST.json").read_bytes())
    require(manifest == manifest_for(record, manifest["build"]), "public manifest/source binding mismatch")
    if original is not None:
        build = read_json(original)
        build.pop("native_library_resolution", None)
        require(manifest["build"] == build, "public manifest differs from original producer")
    validate_build(stage / PACKAGE, manifest["build"], record)
    expected = "".join(record["assets"][name]["sha256"] + "  " + name + "\n"
                       for name in sorted({PACKAGE, "MANIFEST.json"}))
    require((stage / "SHA256SUMS").read_text() == expected, "checksum inventory mismatch")
    from publish_apt import validate_no_gitlab_urls
    validate_no_gitlab_urls(stage)


def context():
    expected = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": REPO, "GITHUB_REF": "refs/heads/main",
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_WORKFLOW_REF": REPO + "/.github/workflows/publish-agpc-view.yml@refs/heads/main"}
    require(all(os.environ.get(k) == v for k, v in expected.items()), "unreviewed publisher context")
    require(re.fullmatch(r"[0-9a-f]{40}", os.environ.get("GITHUB_SHA", "")) is not None,
            "exact publisher revision required")


def absent_release():
    for endpoint in (f"releases/tags/{TAG}", f"git/ref/tags/{TAG}"):
        result = subprocess.run(["gh", "api", f"repos/{REPO}/{endpoint}"], text=True, capture_output=True, timeout=30)
        require(result.returncode != 0 and "HTTP 404" in result.stderr, "release/tag exists or absence unknown")


def publish():
    context()
    record = read_json((ROOT / "scripts/agpc-view-release.json").read_bytes())
    validate_record(record)
    original = fresh_main(record)
    absent_release()
    with tempfile.TemporaryDirectory(prefix="agpc-view-publication-") as directory:
        stage = Path(directory) / "bundle"
        stage.mkdir()
        for name in sorted(ASSETS):
            run("gh", "release", "download", record["candidate_tag"], "--repo", REPO,
                "--pattern", name, "--dir", str(stage))
        validate_bundle(stage, record, original)
        keyhome = Path(directory) / "gnupg"
        keyhome.mkdir(mode=0o700)
        previous = os.environ.get("GNUPGHOME")
        os.environ["GNUPGHOME"] = str(keyhome)
        try:
            fingerprint = "".join((ROOT / "medge-archive-keyring.fingerprint").read_text().split()).upper()
            require(fingerprint == FINGERPRINT, "archive fingerprint changed")
            run("gpg", "--batch", "--import", input=os.environ["MEDGE_APT_SIGNING_KEY"])
            from publish_native import sign_files
            sign_files(ROOT, stage, {"MANIFEST.json", "SHA256SUMS"})
            fresh_main(record)
            absent_release()
            notes = Path(directory) / "notes.txt"
            notes.write_text(record["notes"])
            run("gh", "release", "create", TAG, "--repo", REPO, "--target", os.environ["GITHUB_SHA"],
                "--title", "AGPC View " + VERSION + " (amd64)", "--notes-file", str(notes),
                "--latest=false", *map(str, sorted(stage.iterdir())))
        finally:
            if previous is None:
                os.environ.pop("GNUPGHOME", None)
            else:
                os.environ["GNUPGHOME"] = previous
    print("Published signed standalone " + TAG)


def prepare(args):
    pipeline, native, gui = [read_json(path.read_bytes()) for path in (args.pipeline, args.native_job, args.gui_job)]
    original = (args.bundle / "manifest.json").read_bytes()
    build = read_json(original)
    build.pop("native_library_resolution", None)
    record = {"schema": "agpc-view.publication-inputs/v1", "tag": TAG, "package": PACKAGE,
              "version": VERSION, "architecture": "amd64", "source_project": 1336,
              "source_commit": pipeline["sha"], "source_ref": "main", "pipeline_status": "success",
              "pipeline_id": pipeline["id"], "job_id": native["id"], "gui_job_id": gui["id"],
              "producer_manifest_sha256": sha(original), "candidate_tag": "candidate-" + TAG,
              "assets": {}, "notes": "Native GTK4 AGPC View " + VERSION + " for amd64, built and GUI-checked by canonical main CI. "
              "Local manages this computer and now provides CI-source inspection, validation and explicit credential synchronization. Mesh requires Account browser SSO at account.ypcloud.com and adds selected SIP and ss-webos Live key management, native provider-binding setup, import/replacement and separately gated retirement. "
              "Teal Local and violet Mesh styles follow light, dark and high-contrast themes. Native checks cover the authentication gate; successful human sign-in remains separate live evidence. "
              "Requires the signed agpc-key-manager 0.1.0-2 and Voice key owner dependency, the pinned existing Voice runtime, native Zenity authentication, an approved CI identity, AGPC Mesh >=3.0.0-3 and <4, GTK4 >=4.8 and glibc >=2.39. Provider setup and retirement require an ephemeral Admin API credential through the native prompt. WebOS activation additionally requires its reviewed owner OCI/PD promotion and existing Account system-admin role; this GUI release does not deploy that service. "
              "Run agpc-view as the desktop user. This standalone release does not change Core/All installers, "
              "enable Mesh RUN, or establish runtime readiness. Verify MANIFEST.json.asc and SHA256SUMS.asc "
              "with the established MoteBus archive key before installing.\n"}
    check_jobs(record, pipeline, native, gui)
    validate_build(args.bundle / PACKAGE, build, record)
    require(not args.output.exists() and not args.record_output.exists(), "preparation output already exists")
    manifest = encoded(manifest_for(record, build))
    package = (args.bundle / PACKAGE).read_bytes()
    files = {PACKAGE: package, "MANIFEST.json": manifest}
    files["SHA256SUMS"] = "".join(sha(data) + "  " + name + "\n" for name, data in sorted(files.items())).encode()
    record["assets"] = {name: {"sha256": sha(data), "bytes": len(data)} for name, data in files.items()}
    validate_record(record)
    args.output.mkdir(parents=True)
    for name, data in files.items():
        (args.output / name).write_bytes(data)
    validate_bundle(args.output, record, original)
    args.record_output.parent.mkdir(parents=True, exist_ok=True)
    args.record_output.write_bytes(encoded(record))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action")
    preparation = commands.add_parser("prepare", help="Prepare review inputs from original successful main CI artifacts/API receipts")
    for name in ("bundle", "pipeline", "native-job", "gui-job", "output", "record-output"):
        preparation.add_argument("--" + name, type=Path, required=True)
    commands.add_parser("publish")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args)
    else:
        publish()


if __name__ == "__main__":
    main()
