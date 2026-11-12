#!/usr/bin/env python3
"""Publish signed AGPC installer entrypoints on Pages."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

import publish_native as native

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
        subprocess.run(
            ["gpgv", "--keyring", str(keyring.resolve()), str(site / (name + ".asc")), str(site / name)],
            check=True,
        )

    source = json.loads((site / receipt).read_text())
    native.require(
        source["repository"] == native.REPOSITORY
        and source["profile"] == profile
        and source["asset"] == installer
        and source["sha256"] == before[installer],
        "the signed source record must describe the selected deployed installer",
    )

    for alias, canonical in aliases.items():
        shutil.copy2(site / canonical, site / alias)
    changed = set(aliases)
    if entrypoint == "ready":
        index = site / "index.html"
        updated = index.read_bytes()
        for old, new in (
            (b"agpc.sh", b"agpc-ready.sh"),
            (b"agpc.source.json", b"agpc-ready.source.json"),
            (b"agpc-all.sh", b"agpc-full.sh"),
            (b"agpc-all.source.json", b"agpc-full.source.json"),
            (b"<td>Standard</td>", b"<td>Ready</td>"),
            (b"The same Core system and AGPC View GUI", b"Core with AGPC View GUI"),
            (b"Standard installation", b"Ready installation"),
            (b"Standard preserves", b"Ready preserves"),
            (b"<br>Standard:", b"<br>Ready:"),
        ):
            updated = updated.replace(old, new)
        native.require(b'href="agpc-ready.sh"' in updated, "Ready installer link missing from download page")
        native.require((site / "agpc-full.sh").is_file(), "Full installer missing from download site")
        index.write_bytes(updated)
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
    parser.add_argument("--entrypoint", choices=("full", "ready"), default="full")
    args = parser.parse_args()
    base = native.restore_current(args.site)
    stage_alias(args.root, args.site, args.entrypoint)
    native.require(native.current_pages() == base, "Pages deployment changed before promotion")


if __name__ == "__main__":
    main()
