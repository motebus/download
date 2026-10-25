#!/usr/bin/env python3
"""Publish only the reviewed standalone SS-WebOS artifact; no installer changes."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
REPO = "motebus/download"
TAG = "agpc-ss-webos-v2.0.0-16"
PACKAGE = "ss-webos_2.0.0-16_amd64.deb"


def run(*args, **kwargs):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, **kwargs).strip()
    except subprocess.CalledProcessError:
        raise RuntimeError("publication command failed: " + args[0]) from None


def fresh_main(record):
    source = os.environ["AGPC_GITLAB_SOURCE_URL"]
    assert source.endswith("/agpc-download-source.git"), "unexpected source URL"
    source = source.removesuffix("/agpc-download-source.git") + "/codex-linux/agpc-core-deb.git"
    print("::add-mask::" + source, flush=True)
    auth = base64.b64encode((os.environ["AGPC_GITLAB_READ_USER"] + ":" + os.environ["AGPC_GITLAB_READ_TOKEN"]).encode()).decode()
    print("::add-mask::" + auth, flush=True)
    assert run("git", "-c", "http.extraHeader=Authorization: Basic " + auth,
               "ls-remote", source, "refs/heads/main").split()[0] == record["source_commit"], "source main advanced"
    parsed = urllib.parse.urlsplit(source)
    api = f"{parsed.scheme}://{parsed.netloc}/api/v4/projects/1336"
    def get(path):
        request = urllib.request.Request(api + path, headers={"PRIVATE-TOKEN": os.environ["AGPC_GITLAB_READ_TOKEN"]})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    pipeline = get(f"/pipelines/{record['pipeline_id']}")
    job = get(f"/jobs/{record['job_id']}")
    assert pipeline["status"] == "success" and pipeline["ref"] == "main" and pipeline["sha"] == record["source_commit"]
    assert job["status"] == "success" and job["name"] == "ss-webos-native" and job["pipeline"]["id"] == record["pipeline_id"]
    assert job["commit"]["id"] == record["source_commit"]
    assert json.loads(run("gh", "api", f"repos/{REPO}/branches/main"))["commit"]["sha"] == os.environ["GITHUB_SHA"], "publisher main advanced"


def main():
    assert os.environ["GITHUB_REPOSITORY"] == REPO
    assert os.environ["GITHUB_REF"] == "refs/heads/main"
    record = json.loads((ROOT / "scripts/ss-webos-release.json").read_text())
    assert record["tag"] == TAG and record["package"] == PACKAGE
    assert record["source_ref"] == "main" and record["pipeline_status"] == "success"
    assert record["architecture"] == "amd64" and record["version"] == "2.0.0-16"
    fresh_main(record)
    for endpoint in (f"releases/tags/{TAG}", f"git/ref/tags/{TAG}"):
        result = subprocess.run(["gh", "api", f"repos/{REPO}/{endpoint}"], text=True, capture_output=True)
        assert result.returncode != 0 and "HTTP 404" in result.stderr, "release/tag exists or absence unknown"
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        for name, digest in record["assets"].items():
            assert name in (PACKAGE, "MANIFEST.json", "SHA256SUMS")
            run("gh", "release", "download", record["candidate_tag"], "--repo", REPO, "--pattern", name, "--dir", directory)
            assert hashlib.sha256((stage / name).read_bytes()).hexdigest() == digest, "asset digest mismatch: " + name
        assert set(record["assets"]) == {PACKAGE, "MANIFEST.json", "SHA256SUMS"}
        manifest = json.loads((stage / "MANIFEST.json").read_text())
        assert manifest["source_commit"] == record["source_commit"]
        assert manifest["pipeline_id"] == record["pipeline_id"] and manifest["job_id"] == record["job_id"]
        assert manifest["sha256"] == record["assets"][PACKAGE]
        assert run("dpkg-deb", "-f", str(stage / PACKAGE), "Package") == "ss-webos"
        assert run("dpkg-deb", "-f", str(stage / PACKAGE), "Version") == "2.0.0-16"
        assert run("dpkg-deb", "-f", str(stage / PACKAGE), "Architecture") == "amd64"
        assert (stage / "SHA256SUMS").read_text() == record["assets"][PACKAGE] + "  " + PACKAGE + "\n"
        from publish_apt import validate_no_gitlab_urls
        validate_no_gitlab_urls(stage)
        keyhome = stage / "gnupg"
        keyhome.mkdir(mode=0o700)
        os.environ["GNUPGHOME"] = str(keyhome)
        run("gpg", "--batch", "--import", input=os.environ["MEDGE_APT_SIGNING_KEY"])
        fingerprint = "".join((ROOT / "medge-archive-keyring.fingerprint").read_text().split()).upper()
        assert fingerprint == "AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0"
        assets = [stage / name for name in record["assets"]]
        for name in ("MANIFEST.json", "SHA256SUMS"):
            signature = stage / (name + ".asc")
            run("gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase-fd", "0",
                "--local-user", fingerprint, "--digest-algo", "SHA256", "--armor", "--detach-sign",
                "--output", str(signature), str(stage / name), input=os.environ["MEDGE_APT_SIGNING_PASSPHRASE"] + "\n")
            run("gpgv", "--keyring", str(ROOT / "medge-archive-keyring.gpg"), str(signature), str(stage / name))
            assets.append(signature)
        fresh_main(record)
        notes = stage / "notes.txt"
        notes.write_text(record["notes"])
        run("gh", "release", "create", TAG, "--repo", REPO, "--target", os.environ["GITHUB_SHA"],
            "--title", "SS-WebOS 2.0.0-16 (amd64)", "--notes-file", str(notes), "--latest=false", *map(str, assets))
        print("Published signed standalone " + TAG)


if __name__ == "__main__":
    main()
