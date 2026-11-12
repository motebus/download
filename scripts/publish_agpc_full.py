#!/usr/bin/env python3
"""Publish the signed full installer under its public names on Pages."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

import publish_native as native

def stage_alias(root, site, entrypoint):
    aliases = {
        f"agpc-{entrypoint}{suffix}": f"agpc-all{suffix}"
        for suffix in (".sh", ".sh.asc", ".source.json", ".source.json.asc")
    }
    before = native.snapshot(site)
    keyring = root / "medge-archive-keyring.gpg"
    for name in ("agpc-all.sh", "agpc-all.source.json"):
        subprocess.run(
            ["gpgv", "--keyring", str(keyring.resolve()), str(site / (name + ".asc")), str(site / name)],
            check=True,
        )

    source = json.loads((site / "agpc-all.source.json").read_text())
    native.require(
        source["repository"] == native.REPOSITORY
        and source["profile"] == "full"
        and source["asset"] == "agpc-all.sh"
        and source["sha256"] == before["agpc-all.sh"],
        "the signed source record must describe the deployed full installer",
    )

    for alias, canonical in aliases.items():
        shutil.copy2(site / canonical, site / alias)
    changed = set(aliases)
    if entrypoint == "ready":
        index = site / "index.html"
        updated = index.read_bytes().replace(b"agpc-all.sh", b"agpc-ready.sh").replace(
            b"agpc-all.source.json", b"agpc-ready.source.json"
        )
        native.require(b'href="agpc-ready.sh"' in updated, "full installer link missing from download page")
        index.write_bytes(updated)
        changed.add("index.html")
    after = native.snapshot(site)
    native.verify_preservation(before, after, changed)
    native.require(
        all(after[alias] == before[canonical] for alias, canonical in aliases.items()),
        "full installer alias differs from the signed original",
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
