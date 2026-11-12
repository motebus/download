#!/usr/bin/env python3
"""Publish an alias of the signed full installer from the current Pages site."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

import publish_native as native

ALIASES = {
    "agpc-full.sh": "agpc-all.sh",
    "agpc-full.sh.asc": "agpc-all.sh.asc",
    "agpc-full.source.json": "agpc-all.source.json",
    "agpc-full.source.json.asc": "agpc-all.source.json.asc",
}


def stage_alias(root, site):
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

    for alias, canonical in ALIASES.items():
        shutil.copy2(site / canonical, site / alias)
    after = native.snapshot(site)
    native.verify_preservation(before, after, ALIASES)
    native.require(
        all(after[alias] == before[canonical] for alias, canonical in ALIASES.items()),
        "full installer alias differs from the signed original",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("site", type=Path)
    args = parser.parse_args()
    base = native.restore_current(args.site)
    stage_alias(args.root, args.site)
    native.require(native.current_pages() == base, "Pages deployment changed before promotion")


if __name__ == "__main__":
    main()
