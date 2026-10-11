#!/usr/bin/env python3
"""Stage the reviewed main-CI Voice bundle in the existing signed Pages site."""
import argparse
import ast
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import urllib.request
import urllib.parse
import zipfile

import publish_native as native
import publish_apt as apt

PUBLIC = "https://motebus.github.io/download"
INSTALLER_PROJECT = 1341
VOICE_PROJECT = 1348
LIMIT = 64 * 1024 * 1024
PREFIX = "agpc-voice-bundle/"
VERSION = r"[0-9]+\.[0-9]+\.[0-9]+(?:[~+.-][A-Za-z0-9]+)*"


def load_json(data):
    def unique(items):
        result = {}
        for key, value in items:
            native.require(key not in result, "duplicate JSON field")
            result[key] = value
        return result
    value = json.loads(data, object_pairs_hook=unique)
    native.require(isinstance(value, dict), "JSON object required")
    return value


def validate_inputs(record):
    native.require(record.get("schema") == "agpc.voice-publication-inputs/v1", "invalid Voice inputs")
    native.require(isinstance(record.get("version"), str)
                   and re.fullmatch(VERSION, record["version"])
                   and len(record["version"]) <= 80, "invalid Voice version")
    native.require(re.fullmatch(r"[a-f0-9]{40}", record.get("source_commit", "")), "invalid source commit")
    native.require(type(record.get("ci_job")) is int and record["ci_job"] > 0, "main CI job required")
    native.require(re.fullmatch(r"[a-f0-9]{64}", record.get("archive_sha256", "")), "artifact hash required")
    native.require(type(record.get("archive_bytes")) is int
                   and 0 < record["archive_bytes"] <= LIMIT, "invalid artifact size")
    native.require(type(record.get("install_review")) is int and record["install_review"] > 0,
                   "install review identity required")
    disclosure = record.get("disclosure_review")
    native.require(isinstance(disclosure, dict) and set(disclosure) == {"project", "iid"}
                   and type(disclosure["project"]) is int
                   and disclosure["project"] in (INSTALLER_PROJECT, VOICE_PROJECT)
                   and type(disclosure["iid"]) is int and disclosure["iid"] > 0,
                   "disclosure review identity required")
    return record


def api_bytes(path, limit=LIMIT):
    token = os.environ.get("AGPC_GITLAB_READ_TOKEN")
    native.require(bool(token), "existing GitLab read credential unavailable")
    configured = os.environ.get("AGPC_GITLAB_SOURCE_URL", "")
    origin = urllib.parse.urlsplit(configured)
    native.require(origin.scheme == "https" and bool(origin.hostname) and origin.port in (None, 443)
                   and not origin.username and not origin.password and not origin.query and not origin.fragment
                   and origin.path == "/codex/codex-agpc/agpc-download-source.git",
                   "existing protected source URL contract unavailable")
    api = urllib.parse.urlunsplit((origin.scheme, origin.netloc, "/api/v4/", "", ""))
    request = urllib.request.Request(api + path, headers={"PRIVATE-TOKEN": token})
    class SameHostRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            target = urllib.parse.urlsplit(newurl)
            native.require((target.scheme, target.hostname, target.port or 443)
                           == (origin.scheme, origin.hostname, origin.port or 443),
                           "cross-host authenticated artifact redirect forbidden")
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    with urllib.request.build_opener(SameHostRedirect()).open(request, timeout=60) as response:
        data = response.read(limit + 1)
    native.require(len(data) <= limit, "GitLab response exceeds size limit")
    return data


def api_json(path):
    return load_json(api_bytes(path, 1024 * 1024))


def verify_job(project, job_id, commit, get_json=api_json):
    native.require(project in (INSTALLER_PROJECT, VOICE_PROJECT), "unexpected source project")
    native.require(type(job_id) is int and job_id > 0
                   and re.fullmatch(r"[a-f0-9]{40}", commit), "invalid source CI identity")
    job = get_json(f"projects/{project}/jobs/{job_id}")
    native.require(job.get("id") == job_id and job.get("status") == "success" and job.get("tag") is False
                   and job.get("ref") == "main" and job.get("commit", {}).get("id") == commit
                   and job.get("pipeline", {}).get("sha") == commit
                   and job.get("pipeline", {}).get("ref") == "main", "successful exact main CI required")
    pipeline_id = job.get("pipeline", {}).get("id")
    native.require(type(pipeline_id) is int and pipeline_id > 0, "source pipeline identity missing")
    pipeline = get_json(f"projects/{project}/pipelines/{pipeline_id}")
    native.require(pipeline.get("id") == pipeline_id and pipeline.get("status") == "success"
                   and pipeline.get("ref") == "main" and pipeline.get("sha") == commit,
                   "successful exact main pipeline required")


def verify_review(iid, project, commit, get_json=api_json):
    native.require(project in (INSTALLER_PROJECT, VOICE_PROJECT)
                   and type(iid) is int and iid > 0, "review source identity mismatch")
    endpoint = f"projects/{project}/merge_requests/{iid}"
    review = get_json(endpoint)
    native.require(review.get("state") == "merged" and review.get("target_branch") == "main"
                   and commit in (review.get("merge_commit_sha"), review.get("squash_commit_sha")),
                   "exact merged source review required")
    approvals = get_json(endpoint + "/approvals")
    native.require(approvals.get("approved") is True and bool(approvals.get("approved_by")),
                   "source review approval missing")
    maintainer = False
    for approval in approvals["approved_by"]:
        user_id = approval.get("user", {}).get("id")
        native.require(type(user_id) is int and user_id > 0, "review approver identity missing")
        member = get_json(f"projects/{project}/members/all/{user_id}")
        if type(member.get("access_level")) is int and member["access_level"] >= 40:
            maintainer = True
    native.require(maintainer, "Maintainer source approval required")


def extract_bundle(data, destination, record):
    native.require(len(data) == record["archive_bytes"]
                   and native.digest(data) == record["archive_sha256"], "CI artifact hash/size mismatch")
    total = 0
    seen = set()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            name = member.filename
            parts = Path(name).parts
            native.require(not name.startswith("/") and ".." not in parts and "\\" not in name
                           and not (member.flag_bits & 1), "unsafe CI artifact path")
            mode = member.external_attr >> 16
            native.require(not stat.S_ISLNK(mode), "CI artifact symlink forbidden")
            if member.is_dir():
                native.require(name == PREFIX or name.startswith(PREFIX), "unexpected artifact directory")
                continue
            native.require(name.startswith(PREFIX) and name not in seen, "unexpected/duplicate CI artifact file")
            seen.add(name)
            rel = name[len(PREFIX):]
            native.require(rel in {"agpc-voice.sh", "BUILD-RECEIPT.json", "SOURCE-RELEASE.json", "SHA256SUMS"}
                           or re.fullmatch(r"packages/(agpc-voice|agpc-freeswitch-core)_[A-Za-z0-9.+:~_-]+\.deb", rel),
                           "private or unexpected artifact file")
            total += member.file_size
            native.require(0 < member.file_size <= LIMIT and total <= LIMIT, "artifact expansion exceeds limit")
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))


def embedded_runtime(script, receipt):
    marker = "AGPC_VOICE_PACKAGED_RUNTIME"
    text = script.decode("utf-8")
    native.require(text.count(marker) == 2, "standalone Voice runtime required")
    body = text.split(marker, 1)[1].split("\n", 1)[1].rsplit(marker, 1)[0]
    tree = ast.parse(body)
    payloads = [node.value for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "payload" for target in node.targets)]
    native.require(len(payloads) == 1, "one runtime payload required")
    call = payloads[0]
    native.require(isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                   and isinstance(call.func.value, ast.Name) and call.func.value.id == "base64"
                   and call.func.attr == "b64decode" and len(call.args) == 1
                   and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str),
                   "literal runtime payload required")
    compressed = base64.b64decode(call.args[0].value, validate=True)
    native.require(len(compressed) <= 1024 * 1024, "runtime payload too large")
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        decoded = stream.read(1024 * 1024 + 1)
    native.require(len(decoded) <= 1024 * 1024, "runtime expansion too large")
    sources = load_json(decoded)
    pins = receipt.get("runtime_sha256", {})
    native.require(isinstance(pins, dict) and {name + ".py" for name in sources} == set(pins),
                   "runtime module inventory differs")
    for name, source in sources.items():
        native.require(re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name) and isinstance(source, str)
                       and native.digest(source.encode()) == pins[name + ".py"], "runtime hash mismatch")
        apt.require_no_gitlab_url_bytes(source.encode(), "embedded runtime " + name)
    native.require("native_voice" in sources, "Voice runtime missing")
    gates = [node.value.value for node in ast.parse(sources["native_voice"]).body
             if isinstance(node, ast.Assign)
             and any(isinstance(target, ast.Name) and target.id == "INSTALL_CONTRACT_ADMITTED"
                     for target in node.targets)
             and isinstance(node.value, ast.Constant) and type(node.value.value) is bool]
    native.require(gates == [True], "source-owned install gate remains closed")


def validate_bundle(bundle, inputs, get_json=api_json, get_bytes=api_bytes):
    validate_inputs(inputs)
    verify_job(INSTALLER_PROJECT, inputs["ci_job"], inputs["source_commit"], get_json)
    verify_review(inputs["install_review"], INSTALLER_PROJECT, inputs["source_commit"], get_json)
    receipt = load_json((bundle / "BUILD-RECEIPT.json").read_bytes())
    native.require(receipt.get("schema") == "agpc.voice-standalone-build/v1"
                   and receipt.get("mode") == "release-staging"
                   and receipt.get("source_commit") == inputs["source_commit"], "exact release staging required")
    for key in ("source_admitted", "committed_runtime_verified", "runtime_package_binding_verified"):
        native.require(receipt.get(key) is True, "release admission missing: " + key)
    native.require(receipt.get("ready") is False, "runtime readiness is not publisher admission")
    sources = load_json((bundle / "SOURCE-RELEASE.json").read_bytes())
    native.require(set(sources) == {"schema", "voice_commit", "voice_ci_job", "voice_review"}
                   and sources["schema"] == "agpc.voice-component-main-ci/v1", "invalid component source record")
    verify_job(VOICE_PROJECT, sources["voice_ci_job"], sources["voice_commit"], get_json)
    verify_review(sources["voice_review"], VOICE_PROJECT, sources["voice_commit"], get_json)
    review_project = inputs["disclosure_review"]["project"]
    verify_review(inputs["disclosure_review"]["iid"], review_project,
                  inputs["source_commit"] if review_project == INSTALLER_PROJECT else sources["voice_commit"], get_json)
    script = (bundle / "agpc-voice.sh").read_bytes()
    native.require(native.digest(script) == receipt.get("installer_sha256"), "installer hash mismatch")
    embedded_runtime(script, receipt)
    packages = receipt.get("package_pins")
    native.require(isinstance(packages, list) and len(packages) == 2
                   and all(isinstance(pin, dict) for pin in packages)
                   and {pin.get("name") for pin in packages} == {"agpc-voice", "agpc-freeswitch-core"},
                   "full package pair required")
    expected = {"agpc-voice.sh", "BUILD-RECEIPT.json", "SOURCE-RELEASE.json", "SHA256SUMS"}
    public_packages = []
    for pin in packages:
        for key in ("name", "version", "architecture"):
            native.require(isinstance(pin.get(key), str)
                           and re.fullmatch(r"[A-Za-z0-9.+:~_-]+", pin[key]), "invalid package identity")
        filename = "{name}_{version}_{architecture}.deb".format(**pin)
        rel = "packages/" + filename
        path = bundle / rel
        url = PUBLIC + "/agpc-voice/" + inputs["version"] + "/" + rel
        native.require(pin.get("url") == url, "installer package URL is not bound to this publication")
        native.require(path.is_file() and native.file_digest(path) == pin.get("sha256"), "package hash mismatch")
        for field, key in [("Package", "name"), ("Version", "version"),
                           ("Architecture", "architecture"), ("Depends", "depends")]:
            value = subprocess.check_output(["dpkg-deb", "-f", str(path), field], text=True).strip()
            native.require(value == pin.get(key), "package metadata mismatch: " + field)
        if pin["name"] == "agpc-voice":
            native.require(pin["version"] == inputs["version"], "Voice package/publication version mismatch")
            component_path = "components/agpc-voice/dist/" + urllib.parse.quote(filename, safe="")
            component = get_bytes(f"projects/{VOICE_PROJECT}/jobs/{sources['voice_ci_job']}/artifacts/" + component_path)
            native.require(native.digest(component) == pin["sha256"]
                           and component == path.read_bytes(), "Voice package differs from component main CI artifact")
        expected.add(rel)
        public_packages.append({key: pin[key] for key in ("name", "version", "architecture", "depends", "sha256", "url")})
    actual = {path.relative_to(bundle).as_posix() for path in bundle.rglob("*") if path.is_file()}
    native.require(not any(path.is_symlink() for path in bundle.rglob("*")) and actual == expected,
                   "bundle contains unexpected or missing files")
    sums = {}
    for line in (bundle / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        native.require(name not in sums and re.fullmatch(r"[a-f0-9]{64}", digest), "invalid bundle checksum list")
        sums[name] = digest
    native.require(set(sums) == expected - {"SHA256SUMS", "SOURCE-RELEASE.json"}
                   and all(native.file_digest(bundle / name) == digest for name, digest in sums.items()),
                   "bundle checksum inventory mismatch")
    return receipt, sources, public_packages


def verify_signature(root, site, name):
    subprocess.run(["gpgv", "--keyring", str((root / "medge-archive-keyring.gpg").resolve()),
                    str(site / (name + ".asc")), str(site / name)], check=True)


def overlay(root, site, inputs, bundle, evidence, base=None, get_json=api_json, get_bytes=api_bytes):
    receipt, sources, packages = validate_bundle(bundle, inputs, get_json, get_bytes)
    before = native.snapshot(site)
    previous = site / "agpc-voice.source.json"
    if previous.exists():
        old = load_json(previous.read_bytes())
        native.require(old.get("schema") == "agpc.voice-install-source/v1"
                       and re.fullmatch(VERSION, old.get("version", "")), "unrecognized previous Voice record")
        native.require(subprocess.run(["dpkg", "--compare-versions", inputs["version"], "ge", old["version"]]).returncode == 0,
                       "Voice publication downgrade forbidden")
    source_record = {
        "schema": "agpc.voice-install-source/v1", "version": inputs["version"],
        "source": {"project": INSTALLER_PROJECT,
                   "ref": "main", "commit": inputs["source_commit"], "ci_job": inputs["ci_job"]},
        "voice_source": {"project": VOICE_PROJECT,
                         "ref": "main", "commit": sources["voice_commit"], "ci_job": sources["voice_ci_job"],
                         "review": sources["voice_review"]},
        "install_review": inputs["install_review"], "disclosure_review": inputs["disclosure_review"],
        "artifact_sha256": inputs["archive_sha256"], "installer_sha256": receipt["installer_sha256"],
        "packages": packages, "install_contract_admitted": True, "runtime_ready": False,
    }
    prefix = "agpc-voice/" + inputs["version"] + "/"
    files = {prefix + "agpc-voice.sh": (bundle / "agpc-voice.sh").read_bytes(),
             prefix + "agpc-voice.source.json": (json.dumps(source_record, indent=2, sort_keys=True) + "\n").encode(),
             prefix + "BUILD-RECEIPT.json": (bundle / "BUILD-RECEIPT.json").read_bytes()}
    for pin in packages:
        name = "packages/{name}_{version}_{architecture}.deb".format(**pin)
        files[prefix + name] = (bundle / name).read_bytes()
    for name, data in files.items():
        target = site / name
        if target.exists():
            native.require(target.read_bytes() == data and (site / (name + ".asc")).is_file(),
                           "versioned Voice content is immutable")
    new = set()
    for name, data in files.items():
        target = site / name
        if target.exists():
            verify_signature(root, site, name)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o755 if name.endswith(".sh") else 0o644)
            new.add(name)
    native.sign_files(root, site, new)
    for name in ("agpc-voice.sh", "agpc-voice.source.json"):
        for suffix in ("", ".asc"):
            (site / (name + suffix)).write_bytes((site / (prefix + name + suffix)).read_bytes())
        (site / name).chmod(0o755 if name.endswith(".sh") else 0o644)
    allowed = set(files) | {name + ".asc" for name in files} | {
        "agpc-voice.sh", "agpc-voice.sh.asc", "agpc-voice.source.json", "agpc-voice.source.json.asc"}
    after = native.snapshot(site)
    native.verify_preservation(before, after, allowed)
    evidence.write_text(json.dumps({"schema": "agpc.voice-publication-evidence/v1", "base": base,
                                   "source": source_record, "preserved_files": len(set(before) - allowed),
                                   "published_sha256": {name: after[name] for name in sorted(allowed)}},
                                  indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("site", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    inputs = validate_inputs(load_json((args.root / "scripts/agpc-voice-publication.json").read_bytes()))
    with tempfile.TemporaryDirectory(prefix="agpc-voice-publication-") as temporary:
        bundle = Path(temporary) / "bundle"
        bundle.mkdir()
        verify_job(INSTALLER_PROJECT, inputs["ci_job"], inputs["source_commit"])
        extract_bundle(api_bytes(f"projects/{INSTALLER_PROJECT}/jobs/{inputs['ci_job']}/artifacts"), bundle, inputs)
        validate_bundle(bundle, inputs)
        base = native.restore_current(args.site)
        overlay(args.root, args.site, inputs, bundle, args.evidence, base)
        native.require(native.current_pages() == base, "Pages deployment changed while staging")


if __name__ == "__main__":
    main()
