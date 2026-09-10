#!/usr/bin/env python3
"""Resolve Core and install the complete signed AGPC cohort in isolated Ubuntu images."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

import publish_apt


# Historical v1 remains independently resolvable; v4 expands the core boundary.
RUNTIME_PACKAGES = {"sphered", "moted", "mote-proxy", "mote-transportd", "medge", "mlink"}
CURRENT_RUNTIME_PACKAGES = set(publish_apt.AGENT_SPHERE_COMPONENTS)
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
FULL_SIMULATION = SIMULATION.removesuffix("apt-get --simulate --no-remove install agent-sphere\n") + r'''
# Native maintainer hooks run in this disposable container; services stay stopped.
cat > /usr/sbin/policy-rc.d <<'POLICY'
#!/bin/sh
exit 101
POLICY
chmod 0755 /usr/sbin/policy-rc.d
# Only the exact, independently SHA/control-verified upstream desktop package is
# seeded. Never seed a runtime dependency to make the four-package solve pass.
apt-get --no-install-recommends --no-remove -y install "/prerequisites/$2"
printf 'Prerequisite obsidian %s\n' "$(dpkg-query -W -f='${Version}' obsidian)"
apt-get --simulate --no-remove install agent-sphere agent-ultra sphere-manager agent-apps
apt-get --no-remove -y install agent-sphere agent-ultra sphere-manager agent-apps
test -z "$(dpkg --audit)"
dpkg-query -W -f='InstalledAGPC\t${binary:Package}\t${Version}\t${db:Status-Abbrev}\n'
'''


def validate_plan(output: str, base: dict, overlay: dict, *, full: bool = False) -> dict[str, str]:
    publish_apt.require(not re.search(r"^Remv\s", output, re.MULTILINE), "Agent Sphere APT plan removes packages")
    selected = {}
    for match in re.finditer(r"^Inst\s+([a-z0-9][a-z0-9+.-]*)(?::[a-z0-9]+)?\s+(?:\[[^\]]*\]\s+)?\(([^\s)]+)",
                             output, re.MULTILINE):
        name, version = match.groups()
        publish_apt.require(name not in selected, f"duplicate APT selection: {name}")
        selected[name] = version
    approved = {package["name"]: package for package in base["packages"] + publish_apt.overlay_packages(overlay)}
    runtime = CURRENT_RUNTIME_PACKAGES if overlay["schema"] == publish_apt.AGENT_COMPUTER_FULL_SCHEMA else RUNTIME_PACKAGES
    required = set(publish_apt.AGENT_COMPUTER_REDISTRIBUTABLE) if full else runtime | {"agent-sphere"}
    publish_apt.require(required <= set(selected), "Agent Sphere APT plan is missing a required runtime dependency")
    publish_apt.require(set(selected).intersection(approved) == required,
                        "Agent Sphere APT plan selects an application or an extra aggregate component")
    forbidden = (re.compile(r"^(?:aport|qbix)(?:$|-)")
                 if overlay["schema"] == publish_apt.AGENT_COMPUTER_FULL_SCHEMA else
                 re.compile(r"^(?:agos|aport|agent-apps?|mdesk|desk|ss-webos|mote-chatd|uchat|qbix|model)(?:$|-)|"
                            r"^(?:codex|cx-|mcp-|ultra-mcp|mote-bridge-mcp|mote-mcpd|obsidian)"))
    publish_apt.require(not any(forbidden.search(name) for name in selected),
                        "Agent Sphere APT plan selects a retired application package")
    publish_apt.require(not set(selected).intersection(publish_apt.AGENT_COMPUTER_RETIRED),
                        "APT plan selects a retired runtime or retention package")
    if full:
        external = overlay["release"]["external_prerequisites"][0]
        observations = re.findall(r"^Prerequisite obsidian (\S+)$", output, re.MULTILINE)
        publish_apt.require(observations == [external["version"]] and "obsidian" not in selected,
                            "full APT plan requires the exact official Obsidian prerequisite, already installed")
    for name in required:
        publish_apt.require(name in approved and selected[name] == approved[name]["version"],
                            f"Agent Sphere APT plan version differs from the signed pins: {name}")
    return selected



def validate_installed_cohort(output: str, overlay: dict) -> dict[str, str]:
    expected = {p["name"]: p["version"] for p in overlay["release"]["packages"]
                + overlay["release"]["external_prerequisites"]}
    installed = {}
    for line in output.splitlines():
        if not line.startswith("InstalledAGPC\t"):
            continue
        parts = line.split("\t")
        publish_apt.require(len(parts) == 4, "malformed installed package observation")
        _, name, version, status = parts
        name = name.split(":", 1)[0]
        # DPKG can report unknown/not-installed relationship names without versions.
        # This fresh-container observation checks installation state only; the
        # bootstrap separately checks legacy files and ownership before migration.
        if name in publish_apt.AGENT_COMPUTER_RETIRED and version == "" and status.strip() == "un":
            continue
        if name in expected or name in publish_apt.AGENT_COMPUTER_RETIRED:
            publish_apt.require(name not in installed, "duplicate installed package observation")
            publish_apt.require(status.strip() == "ii", "canonical package is not fully configured: " + name)
            installed[name] = version
    publish_apt.require(installed == expected,
                        "joint APT installation differs from the exact 26 canonical package pins")
    return installed


def validate_full_index_pins(site: Path, overlay: dict) -> None:
    records = {}
    for paragraph in (site / "dists/stable/main/binary-amd64/Packages").read_text().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in paragraph.splitlines() if ": " in line and not line.startswith(" "))
        if "Package" in fields:
            key = (fields["Package"], fields["Version"], fields["Architecture"])
            publish_apt.require(key not in records, "duplicate signed APT package identity")
            records[key] = fields
    publish_apt.require(not any(key[0] == "obsidian" for key in records), "Obsidian must not be redistributed in APT")
    for package in publish_apt.overlay_packages(overlay):
        key = (package["name"], package["version"], package["architecture"])
        record = records.get(key, {})
        name = package["name"]
        filename = f"pool/main/{name[0]}/{name}/{package['asset']}"
        publish_apt.require(record.get("SHA256") == package["sha256"] and record.get("Filename") == filename,
                            f"signed index differs from approved package pins: {name}")
        publish_apt.require(publish_apt.sha256(site / filename) == package["sha256"],
                            f"signed site payload differs from approved pins: {name}")


def validate_signed_index(repository: Path, site: Path, prerequisites: Path | None = None) -> None:
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
    full = overlay["schema"] == publish_apt.AGENT_COMPUTER_FULL_SCHEMA
    if full:
        publish_apt.require(prerequisites is not None, "full overlay requires separately verified upstream prerequisites")
        publish_apt.validate_agent_computer_prerequisites(overlay, prerequisites)
        validate_full_index_pins(site, overlay)
        legacy = site / "legacy" / ("medge-v" + base["medge_version"])
        for directory, name in ((site, "uninstall.sh"), (legacy, "release-manifest.json")):
            publish_apt.run("gpgv", "--keyring", str(key.resolve()),
                            str(directory / (name + ".asc")), str(directory / name))
        publish_apt.require((site / "uninstall.sh").read_bytes() == (repository / "uninstall.sh").read_bytes(),
                            "signed root uninstall preflight differs from reviewed source")
        publish_apt.require((legacy / "release-manifest.json").read_bytes() == (site / "release-manifest.json").read_bytes(),
                            "archived legacy manifest differs from immutable base")
        expected = next(x["sha256"] for x in base["installers"] if x["name"] == "uninstall.sh")
        publish_apt.require(publish_apt.sha256(legacy / "uninstall.sh") == expected
                            and publish_apt.sha256(site / "uninstall.sh") != expected,
                            "legacy callers must reject changed root uninstaller bytes")
    for version, image in UBUNTU_IMAGES:
        output = publish_apt.run("docker", "run", "--rm", "--pull=always", "--platform", "linux/amd64",
            "--log-driver", "none", "--mount", f"type=bind,src={site.resolve()},dst=/repo,readonly",
            image, "bash", "-ceu", SIMULATION, "bash", version, capture=True)
        selected = validate_plan(output, base, overlay)
        print(f"Ubuntu {version}: signed-index apt install agent-sphere resolves the reviewed core runtime dependencies; "
              f"{len(selected)} total packages including native OS dependencies; no excluded components or removals")
        if full:
            output = publish_apt.run("docker", "run", "--rm", "--pull=always", "--platform", "linux/amd64",
                "--log-driver", "none", "--mount", f"type=bind,src={site.resolve()},dst=/repo,readonly",
                "--mount", f"type=bind,src={prerequisites.resolve()},dst=/prerequisites,readonly",
                image, "bash", "-ceu", FULL_SIMULATION, "bash", version,
                overlay["release"]["external_prerequisites"][0]["asset"], capture=True)
            selected = validate_plan(output, base, overlay, full=True)
            validate_installed_cohort(output, overlay)
            print(f"Ubuntu {version}: signed-index apt install agent-sphere agent-ultra sphere-manager agent-apps resolves canonical26 "
                  "with the exact official Obsidian prerequisite; all 26 packages installed and configured by native APT/DPKG; "
                  "no retired runtimes, retention guards or removals; service/owner readiness is separate")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    parser.add_argument("site", type=Path)
    parser.add_argument("--external-prerequisites", type=Path)
    args = parser.parse_args()
    try:
        validate_signed_index(args.repository, args.site, args.external_prerequisites)
    except (publish_apt.PublishError, subprocess.CalledProcessError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
