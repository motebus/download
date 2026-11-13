#!/usr/bin/env python3
"""Add the reviewed SmartScreen package to the current signed APT site."""
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import publish_apt as apt
import publish_native as native

TAG = "agent-computer-v0.3.0-54"
NAME = "ss-webos"
VERSION = "2.0.0-12+l5dev1"
ASSET = f"{NAME}_{VERSION}_amd64.deb"
DIGEST = "94ff44219876d98b5a5489b67aeb26d26047747dd87fcb82d3c6bb0813d8aded"
POOL_PATH = f"pool/main/s/{NAME}/{ASSET}"
DIST = Path("dists/stable")
INDEX = DIST / "main/binary-amd64/Packages"
SIGNED_PATHS = {str(p) for p in (INDEX, INDEX.with_suffix(".gz"),
                DIST / "Release", DIST / "InRelease", DIST / "Release.gpg")}


def signed_index(site, key):
    release = subprocess.check_output(
        ["gpgv", "--keyring", str(key), "--output", "-", str(site / DIST / "InRelease")],
        text=True,
    )
    sha256 = release.split("\nSHA256:\n", 1)[1].split("\nSHA512:", 1)[0]
    for path in (INDEX, INDEX.with_suffix(".gz")):
        entry = [line.split() for line in sha256.splitlines()
                 if line.split()[-1:] == [path.relative_to(DIST).as_posix()]]
        native.require(len(entry) == 1 and entry[0][0] == native.file_digest(site / path),
                       f"index does not match its signed release: {path}")
    return release


def add_package(site, asset):
    apt.require(apt.sha256(asset) == DIGEST, "unexpected SmartScreen artifact digest")
    for field, value in (("Package", NAME), ("Version", VERSION), ("Architecture", "amd64")):
        apt.require(apt.package_field(asset, field) == value, f"unexpected {field}")
    index = site / INDEX
    old = index.read_bytes()
    control = subprocess.check_output(["dpkg-deb", "--field", str(asset)]).rstrip()
    stanza = control + (f"\nFilename: {POOL_PATH}\nSize: {asset.stat().st_size}"
                        f"\nSHA256: {DIGEST}\n\n").encode()
    apt.require(stanza.count(b"Package: ") == 1 and f"SHA256: {DIGEST}\n".encode() in stanza
                and f"Filename: {POOL_PATH}\n".encode() in stanza, "invalid generated package stanza")
    entries = [p for p in old.split(b"\n\n")
               if b"Package: ss-webos\n" in p + b"\n"
               and f"Version: {VERSION}\n".encode() in p + b"\n"]
    apt.require(not entries or entries == [stanza.strip()], "conflicting existing SmartScreen entry")
    if not entries:
        index.write_bytes(old.rstrip(b"\n") + b"\n\n" + stanza)
    index.with_suffix(".gz").write_bytes(gzip.compress(index.read_bytes(), mtime=0))


def main(root, site):
    apt.require(os.environ.get("GITHUB_REPOSITORY") == "motebus/download"
                and os.environ.get("GITHUB_REF") == "refs/heads/main", "protected main required")
    base = native.restore_current(site)
    before = native.snapshot(site)
    key = root / "medge-archive-keyring.gpg"
    apt.require((site / key.name).read_bytes() == key.read_bytes(), "unexpected archive key")
    prior_release = signed_index(site, key)
    with tempfile.TemporaryDirectory() as folder:
        subprocess.run(["gh", "release", "download", TAG, "--repo", "motebus/download",
                        "--pattern", ASSET, "--dir", folder], check=True)
        asset = Path(folder) / ASSET
        apt.require(apt.sha256(asset) == DIGEST, "unexpected release asset digest")
        apt.validate_deb_archive_permissions(asset)
        apt.validate_no_gitlab_urls(Path(folder))
        apt.copy_package(asset, site)
        add_package(site, asset)
    fields = dict(line.split(": ", 1) for line in prior_release.splitlines() if ": " in line)
    args = [arg for field in ("Origin", "Label", "Suite", "Codename", "Architectures",
                              "Components", "Description")
            for arg in ("-o", f"APT::FTPArchive::Release::{field}={fields[field]}")]
    release = site / DIST / "Release"
    release.write_bytes(subprocess.check_output(
        ["apt-ftparchive", *args, "release", str(DIST)], cwd=site))
    passphrase = os.environ["MEDGE_APT_SIGNING_PASSPHRASE"]
    common = ["gpg", "--batch", "--yes", "--pinentry-mode", "loopback",
              "--passphrase-fd", "0", "--local-user", apt.archive_fingerprint(root),
              "--digest-algo", "SHA256", "--armor"]
    for path, operation in (("InRelease", "--clearsign"), ("Release.gpg", "--detach-sign")):
        subprocess.run([*common, operation, "--output", str(site / DIST / path), str(release)],
                       input=passphrase + "\n", text=True, check=True)
    signed_index(site, key)
    after = native.snapshot(site)
    native.verify_preservation(before, after, SIGNED_PATHS | {POOL_PATH})
    native.require(native.current_pages() == base, "Pages base changed during promotion")
    print(json.dumps({"base": base, "package": ASSET, "sha256": DIGEST,
                      "changed": sorted(p for p in after if before.get(p) != after[p])}))


if __name__ == "__main__":
    main(Path(__file__).resolve().parents[1], Path(sys.argv[1]).resolve())
