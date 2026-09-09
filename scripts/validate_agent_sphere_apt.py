#!/usr/bin/env python3
"""Resolve only agent-sphere from the real signed index in clean Ubuntu images."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

import publish_apt


RUNTIME_PACKAGES = {"sphered", "moted", "mote-proxy", "mote-transportd", "medge", "mlink"}
UBUNTU_IMAGES = (
    ("24.04", "docker.io/library/ubuntu@sha256:561618e2c15bf2397621dd04f96926663a3b5616c189cf7e38db7e82f5c538ea"),
    ("26.04", "docker.io/library/ubuntu@sha256:678c6550cc43645e08669028bc177f50be4e7c5b8cca677067b1914d4afc7a03"),
)
SIMULATION = r'''
set -euo pipefail
. /etc/os-release
test "$ID" = ubuntu
test "$VERSION_ID" = "$1"
test "$(dpkg --print-architecture)" = amd64
gpgv --keyring /repo/medge-archive-keyring.gpg /repo/dists/stable/InRelease
cat > /etc/apt/sources.list.d/agent-sphere.sources <<'SOURCES'
Types: deb
URIs: file:/repo
Suites: stable
Components: main
Architectures: amd64
Signed-By: /repo/medge-archive-keyring.gpg
SOURCES
export LC_ALL=C
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get --simulate --no-remove install agent-sphere
'''


def validate_plan(output: str, base: dict, overlay: dict) -> dict[str, str]:
    publish_apt.require(not re.search(r"^Remv\s", output, re.MULTILINE), "Agent Sphere APT plan removes packages")
    selected = {}
    for match in re.finditer(r"^Inst\s+([a-z0-9][a-z0-9+.-]*)(?::[a-z0-9]+)?\s+(?:\[[^\]]*\]\s+)?\(([^\s)]+)",
                             output, re.MULTILINE):
        name, version = match.groups()
        publish_apt.require(name not in selected, f"duplicate APT selection: {name}")
        selected[name] = version
    approved = {package["name"]: package for package in base["packages"] + overlay["release"]["packages"]}
    required = RUNTIME_PACKAGES | {"agent-sphere"}
    publish_apt.require(required <= set(selected), "Agent Sphere APT plan is missing a required runtime dependency")
    publish_apt.require(set(selected).intersection(approved) == required,
                        "Agent Sphere APT plan selects an application or an extra aggregate component")
    forbidden = re.compile(r"^(?:agos|aport|agent-apps?|mdesk|desk|ss-webos|mote-chatd|uchat|qbix|model-node)(?:$|-)|"
                           r"^(?:codex|cx-|mcp-|ultra-mcp|mote-bridge-mcp)")
    publish_apt.require(not any(forbidden.search(name) for name in selected),
                        "Agent Sphere APT plan selects a forbidden application or retired package")
    for name in required:
        publish_apt.require(name in approved and selected[name] == approved[name]["version"],
                            f"Agent Sphere APT plan version differs from the signed pins: {name}")
    return selected


def validate_signed_index(repository: Path, site: Path) -> None:
    overlay = publish_apt.load_agent_computer_overlay(repository)
    if overlay["release"] is None:
        publish_apt.require(not (site / publish_apt.AGENT_COMPUTER_OVERLAY_FILE).exists(),
                            "disabled overlay unexpectedly appears in signed site")
        print("Agent Computer overlay is inactive; Agent Sphere APT simulation is not applicable")
        return
    key = repository / "medge-archive-keyring.gpg"
    publish_apt.require(publish_apt.sha256(key) == publish_apt.sha256(site / key.name),
                        "signed-site key differs from the reviewed archive key")
    for name in ("release-manifest.json", publish_apt.AGENT_COMPUTER_OVERLAY_FILE):
        publish_apt.run("gpgv", "--keyring", str(key.resolve()), str(site / (name + ".asc")), str(site / name))
    publish_apt.run("gpgv", "--keyring", str(key.resolve()), str(site / "dists/stable/InRelease"))
    publish_apt.require(json.loads((site / publish_apt.AGENT_COMPUTER_OVERLAY_FILE).read_text()) == overlay,
                        "signed overlay differs from reviewed pins")
    base = publish_apt.validate_manifest(json.loads((site / "release-manifest.json").read_text()))
    for version, image in UBUNTU_IMAGES:
        output = publish_apt.run("docker", "run", "--rm", "--pull=always", "--platform", "linux/amd64",
            "--log-driver", "none", "--mount", f"type=bind,src={site.resolve()},dst=/repo,readonly",
            image, "bash", "-ceu", SIMULATION, "bash", version, capture=True)
        selected = validate_plan(output, base, overlay)
        print(f"Ubuntu {version}: signed-index apt install agent-sphere resolves all six runtime dependencies; "
              f"{len(selected)} total packages including native OS dependencies; no application packages or removals")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    parser.add_argument("site", type=Path)
    args = parser.parse_args()
    try:
        validate_signed_index(args.repository, args.site)
    except (publish_apt.PublishError, subprocess.CalledProcessError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
