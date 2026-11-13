#!/usr/bin/env python3
"""Publish signed AGPC installer entrypoints on Pages."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

import publish_native as native

MAC_READY = "agpc-ready-mac.sh"
MAC_READY_RECORD = "agpc-ready-mac.source.json"
MAC_READY_TAG = "agpc-ready-v0.1.0-preview.3"
MAC_READY_SHA256 = "c860b48e5c2f76a8adac865201300e43896d3102da5835d4274d6a99120b5b4d"
MAC_READY_FILES = {MAC_READY, MAC_READY_RECORD}


def verify_signature(keyring, site, name):
    subprocess.run(
        ["gpgv", "--keyring", str(keyring.resolve()), str(site / (name + ".asc")), str(site / name)],
        check=True,
    )


def ready_platform_aliases(site, keyring, before):
    verify_signature(keyring, site, "agpc-native-SHA256SUMS")
    verify_signature(keyring, site, "agpc-mac.sh")
    checksums = (site / "agpc-native-SHA256SUMS").read_text().splitlines()
    native.require(
        f'{before["agpc.exe"]}  agpc.exe' in checksums,
        "Windows executable differs from the signed checksum",
    )
    aliases = {"agpc-ready-win.exe": "agpc.exe"}
    if MAC_READY_RECORD in before:
        verify_signature(keyring, site, MAC_READY)
        verify_signature(keyring, site, MAC_READY_RECORD)
        record = json.loads((site / MAC_READY_RECORD).read_text())
        native.require(record["asset"] == MAC_READY and record["sha256"] == before[MAC_READY],
                       "Mac Ready source record does not match the deployed script")
    else:
        aliases.update({MAC_READY: "agpc-mac.sh", MAC_READY + ".asc": "agpc-mac.sh.asc"})
    return aliases


def stage_mac_ready(root, site, revision):
    before = native.snapshot(site)
    script = root / "scripts" / MAC_READY
    native.require(script.is_file() and not script.is_symlink(), "Mac Ready script missing")
    native.require(native.file_digest(script) == MAC_READY_SHA256, "Mac Ready script digest mismatch")
    shutil.copy2(script, site / MAC_READY)
    record = {
        "schema": "agpc.mac-ready-installer/v1",
        "repository": native.REPOSITORY,
        "tag": MAC_READY_TAG,
        "source_commit": revision,
        "asset": MAC_READY,
        "sha256": MAC_READY_SHA256,
        "scope": "clean-install-preview-for-apple-silicon-macs",
        "controller_tag": "agpc-native-v0.1.0-preview.21",
    }
    (site / MAC_READY_RECORD).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    native.sign_files(root, site, MAC_READY_FILES)
    native.verify_preservation(before, native.snapshot(site),
                               MAC_READY_FILES | {name + ".asc" for name in MAC_READY_FILES})


def publish_mac_ready_release(root, site, dist, revision):
    assets = sorted(MAC_READY_FILES | {name + ".asc" for name in MAC_READY_FILES})
    dist.mkdir()
    for name in assets:
        shutil.copy2(site / name, dist / name)
    (dist / "SHA256SUMS").write_text(
        "".join(f"{native.file_digest(dist / name)}  {name}\n" for name in assets),
        encoding="utf-8",
    )
    native.sign_files(root, dist, {"SHA256SUMS"})
    assets += ["SHA256SUMS", "SHA256SUMS.asc"]
    notes = (
        "Single-file installer preview for Apple Silicon Macs. It verifies the existing "
        "preview.21 controller and the signed Darwin ARM64 B-channel proxy, then "
        "provisions an Ubuntu amd64 Sphere guest with mbStack and DC in UTM. "
        "Requires a Mac administrator and the deployment upstreams. Accepted on a "
        "clean macOS 26.4 VM through installation, reboot, automatic Sphere and proxy "
        "startup, and strict B-channel SSH to L5. The proxy is an ad hoc signed development "
        "build. Verify downloads with SHA256SUMS and the MEdge archive key."
    )
    gh_release = ["gh", "release"]
    releases = native.gh_json(f"repos/{native.REPOSITORY}/releases?per_page=100")
    native.require(all(item["tag_name"] != MAC_READY_TAG for item in releases),
                   "Mac Ready release already exists")
    tag = subprocess.run(["gh", "api", f"repos/{native.REPOSITORY}/git/ref/tags/{MAC_READY_TAG}"],
                         capture_output=True, text=True)
    native.require(tag.returncode != 0 and "HTTP 404" in tag.stderr,
                   "Mac Ready tag exists or could not be checked")
    subprocess.run([*gh_release, "create", MAC_READY_TAG, "--target", revision,
                    "--title", "AGPC Ready for macOS v0.1.0 Preview 3",
                    "--notes", notes, "--draft", "--prerelease", "--latest=false",
                    *(str(dist / name) for name in assets)], check=True)
    readback = dist / "readback"
    subprocess.run([*gh_release, "download", MAC_READY_TAG, "--pattern", "*",
                    "--dir", str(readback)], check=True)
    native.require({p.name for p in readback.iterdir()} == set(assets), "Unexpected release assets")
    for name in assets:
        native.require(native.file_digest(readback / name) == native.file_digest(dist / name),
                       f"Release readback digest mismatch for {name}")
    subprocess.run([*gh_release, "edit", MAC_READY_TAG, "--draft=false", "--latest=false"], check=True)


def update_ready_index(site):
    index = site / "index.html"
    updated = index.read_bytes()
    for old, new in (
        (b"agpc.sh", b"agpc-ready.sh"),
        (b"agpc.source.json", b"agpc-ready.source.json"),
        (b"agpc-all.sh", b"agpc-full.sh"),
        (b"agpc-all.source.json", b"agpc-full.source.json"),
        (b"<td>Standard</td>", b"<td>Ready (Ubuntu)</td>"),
        (b"The same Core system and AGPC View GUI", b"Core with AGPC View GUI"),
        (b"Standard installation", b"Ready installation"),
        (b"Standard preserves", b"Ready preserves"),
        (b"<br>Standard:", b"<br>Ready:"),
        (b"agpc.exe", b"agpc-ready-win.exe"),
    ):
        updated = updated.replace(old, new)
    if b'<td>Ready (Windows)</td>' not in updated:
        rows = (
            b'<tr><td>Ready (Windows)</td><td><a href="agpc-ready-win.exe">agpc-ready-win.exe</a></td>'
            b'<td>x86-64 outbound-access preview</td></tr>\n'
            b'<tr><td>Ready (macOS)</td><td><a href="agpc-ready-mac.sh">agpc-ready-mac.sh</a></td>'
            b'<td>Apple Silicon controller preview</td></tr>\n'
        )
        updated = updated.replace(b"</table>", rows + b"</table>", 1)
    native.require(all(f'href="{name}"'.encode() in updated
                       for name in ("agpc-ready.sh", "agpc-ready-win.exe", "agpc-ready-mac.sh")),
                   "Ready platform links missing from download page")
    native.require((site / "agpc-full.sh").is_file(), "Full installer missing from download site")
    index.write_bytes(updated)


def stage_alias(root, site, entrypoint):
    stem, profile = ("agpc", "standard") if entrypoint == "ready" else ("agpc-all", "full")
    installer = stem + ".sh"
    receipt = stem + ".source.json"
    aliases = {
        f"agpc-{entrypoint}{suffix}": stem + suffix
        for suffix in (".sh", ".sh.asc", ".source.json", ".source.json.asc")
    }
    before = native.snapshot(site)
    keyring = root / "medge-archive-keyring.gpg"
    for name in (installer, receipt):
        verify_signature(keyring, site, name)

    source = json.loads((site / receipt).read_text())
    native.require(
        source["repository"] == native.REPOSITORY
        and source["profile"] == profile
        and source["asset"] == installer
        and source["sha256"] == before[installer],
        "the signed source record must describe the selected deployed installer",
    )

    if entrypoint == "ready":
        aliases.update(ready_platform_aliases(site, keyring, before))
    for alias, canonical in aliases.items():
        shutil.copy2(site / canonical, site / alias)
    changed = set(aliases)
    if entrypoint == "ready":
        update_ready_index(site)
        changed.add("index.html")
    after = native.snapshot(site)
    native.verify_preservation(before, after, changed)
    native.require(
        all(after[alias] == before[canonical] for alias, canonical in aliases.items()),
        "installer alias differs from the signed original",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("site", type=Path)
    parser.add_argument("--entrypoint", choices=("full", "ready", "mac-ready"), default="full")
    parser.add_argument("--release-dist", type=Path)
    args = parser.parse_args()
    if (args.entrypoint == "mac-ready") != (args.release_dist is not None):
        parser.error("--release-dist must be used with mac-ready")
    base = native.restore_current(args.site)
    if args.entrypoint == "mac-ready":
        revision = os.environ["GITHUB_SHA"]
        stage_mac_ready(args.root, args.site, revision)
    else:
        stage_alias(args.root, args.site, args.entrypoint)
    native.require(native.current_pages() == base, "Pages deployment changed before promotion")
    if args.entrypoint == "mac-ready":
        publish_mac_ready_release(args.root, args.site, args.release_dist, revision)


if __name__ == "__main__":
    main()
