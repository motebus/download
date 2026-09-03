#!/usr/bin/env python3
"""Validate approved binary bundles and construct the signed Sphere APT site."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


LEGACY_PACKAGES = (
    "sphered",
    "moted",
    "aport",
    "qbix",
    "mbox",
    "motessh",
    "desk",
    "ss-webos",
)
AGENTIC_IO_PACKAGES = (
    "sphered",
    "moted",
    "aport",
    "qbix",
    "mbox",
    "motestream",
    "motessh",
    "moterdp",
    "desk",
    "ss-webos",
)
CX_AGENTIC_IO_PACKAGES = AGENTIC_IO_PACKAGES + ("cx-node",)
EXPECTED_PACKAGES_V8 = (
    "sphere",
    "moted",
    "aport",
    "qbix",
    "mbox",
    "desk",
    "ss-webos",
)
EXPECTED_PACKAGES_V9 = (
    "sphere",
    "moted",
    "medge",
    "mlink",
    "mdesk",
    "ss-webos",
    "mote-proxy",
    "motemcp",
    "cx-pivot",
    "mote-sync",
    "mote-syncd",
)
EXPECTED_PACKAGES_V10 = (
    "sphere",
    "moted",
    "medge",
    "mlink",
    "mdesk",
    "ss-webos",
    "mote-proxy",
    "motemcp",
    "ultra-mcp-ssh",
    "mcp-run",
    "cx-pivot",
    "mote-sync",
    "mote-syncd",
)
EXPECTED_PACKAGES_V11 = EXPECTED_PACKAGES_V10 + (
    "chatd",
    "chat",
)
EXPECTED_PACKAGES_V12 = EXPECTED_PACKAGES_V10 + (
    "schatd",
    "schat",
)
EXPECTED_PACKAGES_V13 = EXPECTED_PACKAGES_V12 + (
    "codex-mesh",
)
EXPECTED_PACKAGES_V14 = tuple(
    "mote-bridge-mcp" if name == "motemcp" else name
    for name in EXPECTED_PACKAGES_V13
)
EXPECTED_PACKAGES_V15 = tuple(
    "cx-node" if name == "cx-pivot" else name
    for name in EXPECTED_PACKAGES_V14
)
INSTALLER_PROFILES_V9 = {
    "sphere.sh": EXPECTED_PACKAGES_V9,
    "sshpack.sh": (
        "sphere",
        "moted",
        "mote-proxy",
        "motemcp",
        "mote-sync",
        "mote-syncd",
    ),
    "webdesk.sh": (
        "sphere",
        "mlink",
        "mdesk",
        "ss-webos",
    ),
}
INSTALLER_PROFILES_V10 = {
    "sphere.sh": EXPECTED_PACKAGES_V10,
    "webdesk.sh": (
        "sphere",
        "mlink",
        "mdesk",
        "ss-webos",
    ),
    "sshkit.sh": (
        "sphere",
        "moted",
        "mote-proxy",
        "motemcp",
        "ultra-mcp-ssh",
        "mcp-run",
        "mote-sync",
        "mote-syncd",
    ),
}
RELEASE_SCRIPTS_V10 = (*INSTALLER_PROFILES_V10, "uninstall.sh")
INSTALLER_PROFILES_V11 = {
    "sphere.sh": EXPECTED_PACKAGES_V11,
    "webdesk.sh": INSTALLER_PROFILES_V10["webdesk.sh"],
    "sshkit.sh": INSTALLER_PROFILES_V10["sshkit.sh"] + ("chatd", "chat"),
}
RELEASE_SCRIPTS_V11 = (*INSTALLER_PROFILES_V11, "uninstall.sh")
INSTALLER_PROFILES_V12 = {
    "sphere.sh": EXPECTED_PACKAGES_V12,
    "webdesk.sh": INSTALLER_PROFILES_V10["webdesk.sh"],
    "sshkit.sh": INSTALLER_PROFILES_V10["sshkit.sh"] + ("schatd", "schat"),
}
RELEASE_SCRIPTS_V12 = (*INSTALLER_PROFILES_V12, "uninstall.sh")
INSTALLER_PROFILES_V13 = {
    "sphere.sh": EXPECTED_PACKAGES_V13,
    "webdesk.sh": INSTALLER_PROFILES_V12["webdesk.sh"],
    "sshkit.sh": INSTALLER_PROFILES_V12["sshkit.sh"],
}
RELEASE_SCRIPTS_V13 = (*INSTALLER_PROFILES_V13, "uninstall.sh")
INSTALLER_PROFILES_V14 = {
    "sphere.sh": EXPECTED_PACKAGES_V14,
    "webdesk.sh": INSTALLER_PROFILES_V13["webdesk.sh"],
    "sshkit.sh": tuple(
        "mote-bridge-mcp" if name == "motemcp" else name
        for name in INSTALLER_PROFILES_V13["sshkit.sh"]
    ),
}
RELEASE_SCRIPTS_V14 = (*INSTALLER_PROFILES_V14, "uninstall.sh")
INSTALLER_PROFILES_V15 = {
    "sphere.sh": tuple(
        name for name in EXPECTED_PACKAGES_V15 if name != "ultra-mcp-ssh"
    ),
    "webdesk.sh": INSTALLER_PROFILES_V14["webdesk.sh"],
    "sshkit.sh": INSTALLER_PROFILES_V14["sshkit.sh"],
}
RELEASE_SCRIPTS_V15 = (*INSTALLER_PROFILES_V15, "uninstall.sh")
V10_THREE_SCRIPT_RELEASES = {"5.1.0-6", "5.1.0-7", "5.1.0-8"}
HEADLESS_PACKAGES = (
    "sphere",
    "moted",
    "aport",
    "qbix",
    "mbox",
)
LEGACY_PACKAGE_SETS = {
    "3.1.0-8": (
        "sphered",
        "mgate",
        "ss-webos",
        "moted",
        "agos",
        "qbix-wasm",
        "mote",
        "desk",
    ),
}
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
FINGERPRINT_RE = re.compile(r"^[0-9A-F]{40}$")
TAG_RE = re.compile(r"^medge-v[0-9]+\.[0-9]+\.[0-9]+-[0-9]+$")
VERSION_RE = re.compile(r"^[0-9][0-9A-Za-z.+:~]*-[0-9]+$")
SOURCE_REF_RE = re.compile(r"^refs/(?:heads/main|tags/[0-9A-Za-z][0-9A-Za-z._-]*)$")
ENV_PATH_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*-(?:deb|mchat)\.env$")
GITLAB_URL_RE = re.compile(
    rb"(?:https?|ssh|git)://[^\x00-\x20\"'<>]*gitlab[^\x00-\x20\"'<>]*",
    re.IGNORECASE,
)
MCHAT_ENV_PACKAGES = {"moted", "aport", "qbix", "mbox", "desk"}
ENV_PATHS_V9 = {
    "sphere": ("sphere-deb.env",),
    "moted": ("moted-deb.env", "moted-mchat.env"),
    "medge": ("medge-deb.env", "medge-mchat.env"),
    "mlink": ("mlink-deb.env",),
    "mdesk": ("mdesk-deb.env", "mdesk-mchat.env"),
    "ss-webos": ("ss-webos-deb.env",),
    "mote-proxy": ("mote-proxy-deb.env", "mote-proxy-mchat.env"),
    "motemcp": ("motemcp-deb.env",),
    "cx-pivot": ("cx-pivot-deb.env", "cx-pivot-mchat.env"),
    "mote-sync": ("mote-sync-deb.env",),
    "mote-syncd": ("mote-sync-deb.env",),
}
ENV_PATHS_V10 = {
    **ENV_PATHS_V9,
    "ultra-mcp-ssh": ("ultra-mcp-deb.env",),
    "mcp-run": ("ultra-mcp-deb.env",),
}
ENV_PATHS_V11 = {
    **ENV_PATHS_V10,
    "chatd": ("chatd-deb.env",),
    "chat": ("chat-deb.env",),
}
ENV_PATHS_V12 = {
    **ENV_PATHS_V10,
    "schatd": ("schatd-deb.env",),
    "schat": ("schat-deb.env",),
}
ENV_PATHS_V13 = {
    **ENV_PATHS_V12,
    "codex-mesh": ("codex-mesh-deb.env",),
}
ENV_PATHS_V14 = {
    **{name: paths for name, paths in ENV_PATHS_V13.items() if name != "motemcp"},
    "mote-bridge-mcp": ("mote-bridge-mcp-deb.env",),
}
ENV_PATHS_V15 = {
    **{name: paths for name, paths in ENV_PATHS_V14.items() if name != "cx-pivot"},
    "cx-node": ("cx-node-deb.env", "cx-node-mchat.env"),
}
MOTE_TRANSPORT_SCHEMA = "mote-transport-public-release/v1"
MOTE_TRANSPORT_TAG_RE = re.compile(
    r"^mote-transport-v[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]+$"
)
MOTE_TRANSPORT_PACKAGES = (
    ("sphere", "4.0.0-1", "amd64"),
    ("moted", "3.2.0-26", "amd64"),
    ("mote-proxy", "1.3.0-35", "all"),
)
ALLOWED_ROOT_FILES = {
    ".gitignore",
    "github-setup.sh",
    "sphere.sh",
    "webdesk.sh",
    "sshkit.sh",
    "uninstall.sh",
    "LICENSE",
    "README.md",
    "medge-release.env",
    "medge.sources",
    "medge-archive-keyring.fingerprint",
    "medge-archive-keyring.gpg",
}
ALLOWED_ROOT_DIRS = {".git", ".github", "scripts", "sphere-runner", "tests"}


class PublishError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PublishError(message)


def run(
    *args: str,
    cwd: Path | None = None,
    capture: bool = False,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=True,
        input=input_text,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        env=env,
    )
    return result.stdout.strip() if capture else ""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_field(asset: Path, field: str) -> str:
    return run("dpkg-deb", "-f", str(asset), field, capture=True)


def require_no_gitlab_url_bytes(value: bytes, subject: str) -> None:
    require(GITLAB_URL_RE.search(value) is None, f"{subject}: GitLab URL is forbidden")


def validate_public_deb_content(asset: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="medge-public-deb-") as temp_name:
        extracted = Path(temp_name)
        run("dpkg-deb", "--raw-extract", str(asset), str(extracted))
        for candidate in extracted.rglob("*"):
            if candidate.is_file() and not candidate.is_symlink():
                require_no_gitlab_url_bytes(
                    candidate.read_bytes(),
                    f"{asset.name}:{candidate.relative_to(extracted)}",
                )


def validate_no_gitlab_urls(root: Path) -> None:
    for candidate in root.rglob("*"):
        if not candidate.is_file() or candidate.is_symlink() or ".git" in candidate.parts:
            continue
        if candidate.suffix == ".deb":
            validate_public_deb_content(candidate)
        else:
            require_no_gitlab_url_bytes(candidate.read_bytes(), str(candidate.relative_to(root)))


def archive_fingerprint(repository_root: Path) -> str:
    formatted = (
        repository_root / "medge-archive-keyring.fingerprint"
    ).read_text(encoding="utf-8")
    fingerprint = "".join(formatted.split()).upper()
    require(
        FINGERPRINT_RE.fullmatch(fingerprint) is not None,
        "invalid archive-key fingerprint",
    )
    return fingerprint


def expected_depends(manifest: dict) -> str:
    packages = {package["name"]: package for package in manifest["packages"]}
    return ", ".join(
        f"{name} (= {packages[name]['version']})" for name in HEADLESS_PACKAGES
    )


def expected_packages(manifest: dict) -> tuple[str, ...]:
    version = manifest.get("medge_version")
    if version in LEGACY_PACKAGE_SETS:
        return LEGACY_PACKAGE_SETS[version]
    if manifest.get("schema") in {"medge-public-release/v4", "medge-public-release/v5"}:
        return LEGACY_PACKAGES
    if manifest.get("schema") == "medge-public-release/v6":
        return AGENTIC_IO_PACKAGES
    if manifest.get("schema") == "medge-public-release/v7":
        return CX_AGENTIC_IO_PACKAGES
    if manifest.get("schema") == "medge-public-release/v8":
        return EXPECTED_PACKAGES_V8
    if manifest.get("schema") == "medge-public-release/v9":
        return EXPECTED_PACKAGES_V9
    if manifest.get("schema") == "medge-public-release/v10":
        return EXPECTED_PACKAGES_V10
    if manifest.get("schema") == "medge-public-release/v11":
        return EXPECTED_PACKAGES_V11
    if manifest.get("schema") == "medge-public-release/v12":
        return EXPECTED_PACKAGES_V12
    if manifest.get("schema") == "medge-public-release/v13":
        return EXPECTED_PACKAGES_V13
    if manifest.get("schema") == "medge-public-release/v14":
        return EXPECTED_PACKAGES_V14
    if manifest.get("schema") == "medge-public-release/v15":
        return EXPECTED_PACKAGES_V15
    raise PublishError("unsupported public release manifest schema")


def expected_env_paths(package_name: str, schema: str | None = None) -> list[str]:
    if schema == "medge-public-release/v15" and package_name in ENV_PATHS_V15:
        return list(ENV_PATHS_V15[package_name])
    if package_name == "cx-node":
        return []
    if package_name in ENV_PATHS_V14:
        return list(ENV_PATHS_V14[package_name])
    if package_name in ENV_PATHS_V12:
        return list(ENV_PATHS_V12[package_name])
    if package_name in ENV_PATHS_V11:
        return list(ENV_PATHS_V11[package_name])
    paths = [f"{package_name}-deb.env"]
    if package_name in MCHAT_ENV_PACKAGES or package_name == "mote-proxy":
        paths.append(f"{package_name}-mchat.env")
    return paths


def validate_env_inputs(package: dict, schema: str | None = None) -> None:
    name = package["name"]
    env_inputs = package.get("env_inputs")
    require(isinstance(env_inputs, list), f"{name}: env_inputs must be an array")
    require(
        [item.get("path") for item in env_inputs if isinstance(item, dict)]
        == expected_env_paths(name, schema),
        f"{name}: env_inputs must be {expected_env_paths(name, schema)}",
    )
    for item in env_inputs:
        require(isinstance(item, dict), f"{name}: env input must be an object")
        require(set(item) == {"path", "sha256"}, f"{name}: env input fields are invalid")
        require(
            isinstance(item.get("path"), str)
            and ENV_PATH_RE.fullmatch(item["path"]),
            f"{name}: env input path must be a repository-root DEB env file",
        )
        require(
            isinstance(item.get("sha256"), str)
            and HEX64_RE.fullmatch(item["sha256"]),
            f"{name}: env input sha256 must be lowercase hexadecimal",
        )


def validate_installer_records(manifest: dict) -> None:
    schema = manifest.get("schema")
    if schema not in {
        "medge-public-release/v10",
        "medge-public-release/v11",
        "medge-public-release/v12",
        "medge-public-release/v13",
        "medge-public-release/v14",
        "medge-public-release/v15",
    }:
        require("installers" not in manifest, "legacy manifest must not carry installers")
        return
    installers = manifest.get("installers")
    if installers is None and manifest.get("medge_version") == "5.1.0-5":
        return
    if schema == "medge-public-release/v15":
        expected_names = list(RELEASE_SCRIPTS_V15)
    elif schema == "medge-public-release/v14":
        expected_names = list(RELEASE_SCRIPTS_V14)
    elif schema == "medge-public-release/v13":
        expected_names = list(RELEASE_SCRIPTS_V13)
    elif schema == "medge-public-release/v12":
        expected_names = list(RELEASE_SCRIPTS_V12)
    elif schema == "medge-public-release/v11":
        expected_names = list(RELEASE_SCRIPTS_V11)
    else:
        expected_names = list(
            INSTALLER_PROFILES_V10
            if manifest.get("medge_version") in V10_THREE_SCRIPT_RELEASES
            else RELEASE_SCRIPTS_V10
        )
    require(isinstance(installers, list), "current installers must be an array")
    require(
        [item.get("name") for item in installers if isinstance(item, dict)]
        == expected_names,
        f"installer order must be {expected_names}",
    )
    for item in installers:
        require(isinstance(item, dict), "installer record must be an object")
        require(set(item) == {"name", "sha256"}, "installer record fields are invalid")
        require(
            isinstance(item.get("sha256"), str) and HEX64_RE.fullmatch(item["sha256"]),
            f"{item.get('name', '<unknown>')}: invalid installer sha256",
        )


def validate_manifest(manifest: object) -> dict:
    require(isinstance(manifest, dict), "release-manifest.json must contain an object")
    expected_keys = {
        "schema", "status", "medge_version", "suite", "component", "architecture",
        "generated_at", "previous_release_tag", "approval", "packages",
    }
    if "rollback" in manifest:
        expected_keys.add("rollback")
    if "installers" in manifest:
        expected_keys.add("installers")
    require(set(manifest) == expected_keys, "public release manifest fields are invalid")
    require(
        manifest.get("schema") in {
            "medge-public-release/v4",
            "medge-public-release/v5",
            "medge-public-release/v6",
            "medge-public-release/v7",
            "medge-public-release/v8",
            "medge-public-release/v9",
            "medge-public-release/v10",
            "medge-public-release/v11",
            "medge-public-release/v12",
            "medge-public-release/v13",
            "medge-public-release/v14",
            "medge-public-release/v15",
        },
        "invalid public release manifest schema",
    )
    require(manifest.get("status") == "approved", "release manifest is not approved")
    require(
        isinstance(manifest.get("medge_version"), str)
        and VERSION_RE.fullmatch(manifest["medge_version"]),
        "invalid medge_version",
    )
    require(manifest.get("suite") == "stable", "only stable suite is allowed")
    require(manifest.get("component") == "main", "only main component is allowed")
    require(manifest.get("architecture") == "amd64", "only amd64 is allowed")
    validate_installer_records(manifest)
    approval = manifest.get("approval")
    require(
        isinstance(approval, dict)
        and all(isinstance(approval.get(key), str) and approval[key] for key in ("id", "approved_by", "approved_at")),
        "approved release requires complete approval evidence",
    )
    previous = manifest.get("previous_release_tag")
    require(
        previous == "" or (isinstance(previous, str) and TAG_RE.fullmatch(previous)),
        "invalid previous_release_tag",
    )
    packages = manifest.get("packages")
    expected = expected_packages(manifest)
    require(
        isinstance(packages, list) and len(packages) == len(expected),
        f"release must contain {len(expected)} components",
    )
    require(
        [package.get("name") for package in packages] == list(expected),
        "release component set or order is invalid",
    )
    for package in packages:
        name = package["name"]
        package_fields = {
            "name", "version", "architecture", "asset", "source_commit",
            "source_ref", "sha256",
        }
        if manifest["schema"] in {
            "medge-public-release/v5",
            "medge-public-release/v6",
            "medge-public-release/v7",
            "medge-public-release/v8",
            "medge-public-release/v9",
            "medge-public-release/v10",
            "medge-public-release/v11",
            "medge-public-release/v12",
            "medge-public-release/v13",
            "medge-public-release/v14",
            "medge-public-release/v15",
        }:
            package_fields.add("env_inputs")
        require(
            set(package) == package_fields,
            f"{name}: public package fields are invalid",
        )
        require(isinstance(package["version"], str) and VERSION_RE.fullmatch(package["version"]), f"{name}: invalid version")
        require(package["architecture"] in {"amd64", "all"}, f"{name}: invalid architecture")
        require(package["asset"] == f"{name}_{package['version']}_{package['architecture']}.deb", f"{name}: invalid asset")
        require(re.fullmatch(r"[0-9a-f]{40}", package["source_commit"]) is not None, f"{name}: invalid source_commit")
        require(SOURCE_REF_RE.fullmatch(package["source_ref"]) is not None, f"{name}: invalid source_ref")
        require(HEX64_RE.fullmatch(package["sha256"]) is not None, f"{name}: invalid sha256")
        if manifest["schema"] in {
            "medge-public-release/v5",
            "medge-public-release/v6",
            "medge-public-release/v7",
            "medge-public-release/v8",
            "medge-public-release/v9",
            "medge-public-release/v10",
            "medge-public-release/v11",
            "medge-public-release/v12",
            "medge-public-release/v13",
            "medge-public-release/v14",
            "medge-public-release/v15",
        }:
            validate_env_inputs(package, manifest["schema"])
    require_no_gitlab_url_bytes(
        json.dumps(manifest, sort_keys=True).encode("utf-8"),
        "release-manifest.json",
    )
    return manifest


def verify_checksums(bundle: Path) -> set[str]:
    checksum_file = bundle / "SHA256SUMS"
    require(checksum_file.is_file(), "bundle is missing SHA256SUMS")
    seen: set[str] = set()
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        digest, separator, name = line.partition("  ")
        require(separator == "  " and HEX64_RE.fullmatch(digest), "invalid SHA256SUMS entry")
        require("/" not in name and name not in seen, f"invalid checksum target: {name}")
        seen.add(name)
        target = bundle / name
        require(target.is_file(), f"checksum target is missing: {name}")
        require(sha256(target) == digest, f"checksum mismatch: {name}")
    return seen


def validate_transport_manifest(manifest: object) -> dict:
    require(isinstance(manifest, dict), "release-manifest.json must contain an object")
    require(
        set(manifest) == {
            "schema", "tag", "status", "generated_at", "source_ref",
            "source_commit", "distribution", "approval", "packages", "installer",
        },
        "Mote Transport manifest fields are invalid",
    )
    require(manifest.get("schema") == MOTE_TRANSPORT_SCHEMA, "invalid Mote Transport schema")
    require(
        isinstance(manifest.get("tag"), str)
        and MOTE_TRANSPORT_TAG_RE.fullmatch(manifest["tag"]),
        "invalid Mote Transport release tag",
    )
    require(manifest.get("status") == "approved", "Mote Transport release is not approved")
    require(
        isinstance(manifest.get("generated_at"), str) and manifest["generated_at"],
        "Mote Transport generated_at is required",
    )
    require(manifest.get("source_ref") == "refs/heads/main", "Mote Transport source must be main")
    require(
        isinstance(manifest.get("source_commit"), str)
        and re.fullmatch(r"[0-9a-f]{40}", manifest["source_commit"]),
        "invalid Mote Transport source commit",
    )
    require(
        manifest.get("distribution") == "github-release-assets",
        "invalid Mote Transport distribution",
    )
    approval = manifest.get("approval")
    require(
        isinstance(approval, dict)
        and set(approval) == {"approved_by", "approved_at", "request"}
        and all(isinstance(approval[key], str) and approval[key] for key in approval),
        "Mote Transport approval evidence is incomplete",
    )
    installer = manifest.get("installer")
    require(
        isinstance(installer, dict)
        and set(installer) == {"asset", "sha256"}
        and installer.get("asset") == "install-mote-transport.sh"
        and isinstance(installer.get("sha256"), str)
        and HEX64_RE.fullmatch(installer["sha256"]),
        "invalid Mote Transport installer record",
    )
    packages = manifest.get("packages")
    require(
        isinstance(packages, list) and len(packages) == len(MOTE_TRANSPORT_PACKAGES),
        "Mote Transport must contain exactly three packages",
    )
    for package, (name, version, architecture) in zip(packages, MOTE_TRANSPORT_PACKAGES):
        require(isinstance(package, dict), "Mote Transport package record must be an object")
        require(
            set(package) == {
                "name", "version", "architecture", "asset", "sha256",
                "source_ref", "source_commit", "pipeline_id", "env_inputs",
            },
            f"{name}: Mote Transport package fields are invalid",
        )
        require(
            (package["name"], package["version"], package["architecture"])
            == (name, version, architecture),
            f"{name}: Mote Transport package identity is invalid",
        )
        require(
            package["asset"] == f"{name}_{version}_{architecture}.deb",
            f"{name}: Mote Transport asset name is invalid",
        )
        require(
            isinstance(package["sha256"], str) and HEX64_RE.fullmatch(package["sha256"]),
            f"{name}: invalid Mote Transport package checksum",
        )
        require(package["source_ref"] == "refs/heads/main", f"{name}: source must be main")
        require(
            isinstance(package["source_commit"], str)
            and re.fullmatch(r"[0-9a-f]{40}", package["source_commit"]),
            f"{name}: invalid source commit",
        )
        require(
            isinstance(package["pipeline_id"], int) and package["pipeline_id"] > 0,
            f"{name}: invalid pipeline id",
        )
        validate_env_inputs(package)
    require_no_gitlab_url_bytes(
        json.dumps(manifest, sort_keys=True).encode("utf-8"),
        "Mote Transport release-manifest.json",
    )
    return manifest


def validate_transport_bundle(bundle: Path) -> dict:
    manifest_path = bundle / "release-manifest.json"
    require(manifest_path.is_file(), f"{bundle}: missing release-manifest.json")
    manifest = validate_transport_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    checksum_targets = verify_checksums(bundle)
    expected_targets = {
        "release-manifest.json",
        manifest["installer"]["asset"],
        *(package["asset"] for package in manifest["packages"]),
    }
    require(checksum_targets == expected_targets, "Mote Transport checksum targets are invalid")
    require(
        sha256(bundle / manifest["installer"]["asset"]) == manifest["installer"]["sha256"],
        "Mote Transport installer checksum mismatch",
    )
    run("bash", "-n", str(bundle / manifest["installer"]["asset"]))
    for package in manifest["packages"]:
        asset = bundle / package["asset"]
        require(asset.is_file(), f"missing Mote Transport package: {asset.name}")
        require(sha256(asset) == package["sha256"], f"checksum mismatch: {asset.name}")
        require(package_field(asset, "Package") == package["name"], f"package mismatch: {asset.name}")
        require(package_field(asset, "Version") == package["version"], f"version mismatch: {asset.name}")
        require(
            package_field(asset, "Architecture") == package["architecture"],
            f"architecture mismatch: {asset.name}",
        )
    actual_files = {path.name for path in bundle.iterdir() if path.is_file()}
    require(
        actual_files == expected_targets | {"SHA256SUMS"},
        "Mote Transport bundle contains unexpected files",
    )
    validate_no_gitlab_urls(bundle)
    return manifest


def validate_bundle(bundle: Path) -> dict:
    manifest_path = bundle / "release-manifest.json"
    require(manifest_path.is_file(), f"{bundle}: missing release-manifest.json")
    manifest = validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    checksum_targets = verify_checksums(bundle)

    for package in manifest["packages"]:
        asset = bundle / package["asset"]
        require(asset.is_file(), f"missing package asset: {package['asset']}")
        require(sha256(asset) == package["sha256"], f"digest mismatch: {asset.name}")
        require(package_field(asset, "Package") == package["name"], f"package mismatch: {asset.name}")
        require(package_field(asset, "Version") == package["version"], f"version mismatch: {asset.name}")
        require(
            package_field(asset, "Architecture") == package["architecture"],
            f"architecture mismatch: {asset.name}",
        )

    retired_meta = bundle / f"medge_{manifest['medge_version']}_all.deb"
    require(
        not retired_meta.exists(),
        "current bundle must not contain retired medge.deb",
    )

    forbidden = [
        path.name
        for path in bundle.iterdir()
        if path.is_file()
        and (
            path.name.endswith(".dsc")
            or ".orig.tar." in path.name
            or ".debian.tar." in path.name
        )
    ]
    require(forbidden == [], f"source packages are forbidden: {forbidden}")
    validate_no_gitlab_urls(bundle)
    if manifest["schema"] in {
        "medge-public-release/v9",
        "medge-public-release/v10",
        "medge-public-release/v11",
        "medge-public-release/v12",
        "medge-public-release/v13",
        "medge-public-release/v14",
        "medge-public-release/v15",
    }:
        if manifest["schema"] == "medge-public-release/v15":
            release_scripts = RELEASE_SCRIPTS_V15
        elif manifest["schema"] == "medge-public-release/v14":
            release_scripts = RELEASE_SCRIPTS_V14
        elif manifest["schema"] == "medge-public-release/v13":
            release_scripts = RELEASE_SCRIPTS_V13
        elif manifest["schema"] == "medge-public-release/v12":
            release_scripts = RELEASE_SCRIPTS_V12
        elif manifest["schema"] == "medge-public-release/v11":
            release_scripts = RELEASE_SCRIPTS_V11
        elif manifest["schema"] == "medge-public-release/v10":
            release_scripts = RELEASE_SCRIPTS_V10
        else:
            release_scripts = INSTALLER_PROFILES_V9
        if manifest.get("medge_version") in V10_THREE_SCRIPT_RELEASES:
            release_scripts = tuple(INSTALLER_PROFILES_V10)
        for installer_name in release_scripts:
            installer = bundle / installer_name
            require(installer.is_file(), f"current bundle is missing {installer_name}")
            require(
                installer.stat().st_mode & 0o111 != 0,
                f"{installer_name} must be executable",
            )
            run("bash", "-n", str(installer))
            installer_record = next(
                (
                    item for item in manifest.get("installers", [])
                    if item.get("name") == installer_name
                ),
                None,
            )
            if installer_record is not None:
                require(
                    sha256(installer) == installer_record["sha256"],
                    f"installer digest mismatch: {installer_name}",
                )
        expected_targets = {
            "release-manifest.json",
            *release_scripts,
            *(package["asset"] for package in manifest["packages"]),
        }
        require(checksum_targets == expected_targets, "current checksum targets are invalid")
        actual_files = {path.name for path in bundle.iterdir() if path.is_file()}
        require(
            actual_files == expected_targets | {"SHA256SUMS"},
            "current bundle contains unexpected files",
        )
        for retired_name in (
            "install-sphere.sh",
            "install-mote-transport.sh",
            "install-medge-all.sh",
            "medge-install.sh",
            "install.sh",
        ):
            require(not (bundle / retired_name).exists(), f"current bundle contains retired {retired_name}")
    else:
        required_installers = [
            "install-mote-transport.sh",
            "medge-install.sh",
            "mdesk-install.sh",
            "ss-webos-install.sh",
            "mote-proxy-install.sh",
            "motemcp-install.sh",
        ]
        for name in required_installers:
            installer = bundle / name
            require(installer.is_file(), f"bundle is missing {name}")
            run("sh", "-n", str(installer))
        require(not (bundle / "install.sh").exists(), "legacy bundle must not contain install.sh")
    return manifest


def validate_tree(root: Path) -> None:
    unexpected = [
        path.name
        for path in root.iterdir()
        if path.name not in ALLOWED_ROOT_FILES and path.name not in ALLOWED_ROOT_DIRS
    ]
    require(unexpected == [], f"unexpected public repository paths: {sorted(unexpected)}")
    tracked_forbidden = [
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and (
            path.suffix == ".deb"
            or path.suffix == ".dsc"
            or ".orig.tar." in path.name
            or ".debian.tar." in path.name
        )
    ]
    require(tracked_forbidden == [], f"binary/source package leaked into Git tree: {tracked_forbidden}")
    validate_no_gitlab_urls(root)
    fingerprint = archive_fingerprint(root)
    public_keys = run(
        "gpg",
        "--batch",
        "--show-keys",
        "--with-colons",
        str(root / "medge-archive-keyring.gpg"),
        capture=True,
    )
    require(
        f"fpr:::::::::{fingerprint}:" in public_keys,
        "public archive key does not match fingerprint",
    )
    for installer_name in RELEASE_SCRIPTS_V15:
        installer = root / installer_name
        require(installer.is_file(), f"public repository is missing {installer_name}")
        require(
            installer.stat().st_mode & 0o111 != 0,
            f"{installer_name} must be executable",
        )
        run("bash", "-n", str(installer))
    actual_shell_entries = {
        path.name for path in root.iterdir()
        if path.is_file()
        and path.name.endswith(".sh")
        and path.name != "github-setup.sh"
    }
    require(
        actual_shell_entries == set(RELEASE_SCRIPTS_V15),
        "public repository must contain exactly the approved release scripts",
    )
    publish_workflow = (root / ".github/workflows/publish-apt.yml").read_text(
        encoding="utf-8"
    )
    require(
        "chmod 0755 release-input/current/sphere.sh" in publish_workflow
        and "release-input/current/webdesk.sh" in publish_workflow
        and "release-input/current/sshkit.sh" in publish_workflow
        and "release-input/current/uninstall.sh" in publish_workflow,
        "publish workflow must restore all release-asset installer modes",
    )
    for installer_name in INSTALLER_PROFILES_V15:
        installer_text = (root / installer_name).read_text(encoding="utf-8")
        for required_text in (
            "medge-public-release/v15",
            fingerprint,
            "release-manifest.json.asc",
            "gpgv --keyring",
            'apt-get --allow-downgrades --print-uris -y install "${PACKAGE_ARGS[@]}"',
            'apt-get install -y --allow-downgrades "${PACKAGE_ARGS[@]}"',
        ):
            require(
                required_text in installer_text,
                f"{installer_name} is missing required contract: {required_text}",
            )
        for forbidden_text in (
            "apt-key",
            "trusted=yes",
            "/etc/hosts",
            "systemctl edit",
            "systemctl enable --now",
            "MCHAT_",
            "gitlab.",
            'elif [[ -n "$SCRIPT_SOURCE" ]]',
        ):
            require(
                forbidden_text not in installer_text,
                f"{installer_name} contains forbidden content: {forbidden_text}",
            )

    installer_text = (root / "sshkit.sh").read_text(encoding="utf-8")
    for required_text in (
        "verify_mote_proxy_ssh_setup",
        "/etc/ssh/ssh_config.d/50-mote-proxy.conf",
        "/usr/libexec/mote-proxy/ssh-proxy",
        "/usr/bin/ssh -G -F /etc/ssh/ssh_config",
        "sphere-installer-proxy-check.mote",
        "automatic *.mote SSH proxy setup is active",
        "verify_sphere_post_install",
        "/usr/sbin/sphere post-install",
        "Sphere essential post-install health checks failed",
    ):
        require(
            required_text in installer_text,
            f"sshkit.sh is missing automatic SSH proxy verification: {required_text}",
        )
    require(
        "~/.ssh/config" not in installer_text,
        "sshkit.sh must not write user SSH configuration",
    )

    sphere_text = (root / "sphere.sh").read_text(encoding="utf-8")
    for excluded_text in (
        "verify_mote_proxy_ssh_setup",
        "verify_sphere_post_install",
        "/usr/sbin/sphere post-install",
        "sphere-installer-proxy-check.mote",
    ):
        require(
            excluded_text not in sphere_text,
            f"sphere.sh must remain install-only: {excluded_text}",
        )

    webdesk_text = (root / "webdesk.sh").read_text(encoding="utf-8")
    require(
        "verify_mote_proxy_ssh_setup" not in webdesk_text
        and "sphere-installer-proxy-check.mote" not in webdesk_text,
        "webdesk.sh must not acquire an SSH proxy setup responsibility",
    )

    uninstall_text = (root / "uninstall.sh").read_text(encoding="utf-8")
    for required_text in (
        "medge-public-release/v15",
        fingerprint,
        "release-manifest.json.asc",
        "gpgv --keyring",
        "apt-get --simulate purge",
        'apt-get purge -y "${PURGE_ARGS[@]}"',
        "purge plan would remove packages outside Sphere",
        "/etc/ssh/ssh_config.d/50-mote-proxy.conf",
        "package-owned SSH proxy profile",
        "refusing removal",
        "remove_managed_ssh_proxy_profile",
    ):
        require(
            required_text in uninstall_text,
            f"uninstall.sh is missing required contract: {required_text}",
        )
    for forbidden_text in (
        "apt-get autoremove",
        "apt-get remove",
        "rm -rf",
        "/home/",
        "~/.ssh",
        "MCHAT_",
        "medge-home.mote",
        "gitlab.",
        'elif [[ -n "$SCRIPT_SOURCE" ]]',
    ):
        require(
            forbidden_text not in uninstall_text,
            f"uninstall.sh contains forbidden content: {forbidden_text}",
        )

    compatibility = root / "scripts/validate-ubuntu-compatibility.sh"
    require(compatibility.is_file(), "public repository is missing Ubuntu compatibility validation")
    require(
        compatibility.stat().st_mode & 0o111 != 0,
        "Ubuntu compatibility validation must be executable",
    )
    run("bash", "-n", str(compatibility))
    compatibility_text = compatibility.read_text(encoding="utf-8")
    for release in ("24.04", "26.04"):
        require(
            f"run_target {release}" in compatibility_text,
            f"Ubuntu {release} compatibility target is missing",
        )
    require(
        len(re.findall(r"docker\.io/library/ubuntu@sha256:[0-9a-f]{64}", compatibility_text)) == 2,
        "Ubuntu compatibility images must be digest-pinned",
    )


def copy_package(asset: Path, site: Path) -> None:
    package = package_field(asset, "Package")
    first = package[0] if not package.startswith("lib") else package[:4]
    destination_dir = site / "pool/main" / first / package
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / asset.name
    if destination.exists():
        require(sha256(destination) == sha256(asset), f"conflicting duplicate asset: {asset.name}")
    else:
        shutil.copy2(asset, destination)


def write_index(
    site: Path,
    repository_root: Path,
    current_manifest: dict,
    current_bundle: Path,
) -> None:
    packages_dir = site / "dists/stable/main/binary-amd64"
    packages_dir.mkdir(parents=True, exist_ok=True)
    packages_text = run("apt-ftparchive", "packages", "pool", cwd=site, capture=True) + "\n"
    (packages_dir / "Packages").write_text(packages_text, encoding="utf-8")
    (packages_dir / "Packages.gz").write_bytes(
        gzip.compress(packages_text.encode("utf-8"), mtime=0)
    )

    release_options = (
        "-o", "APT::FTPArchive::Release::Origin=MoteBus",
        "-o", "APT::FTPArchive::Release::Label=Sphere",
        "-o", "APT::FTPArchive::Release::Suite=stable",
        "-o", "APT::FTPArchive::Release::Codename=stable",
        "-o", "APT::FTPArchive::Release::Architectures=amd64",
        "-o", "APT::FTPArchive::Release::Components=main",
        "-o", "APT::FTPArchive::Release::Description=Install Sphere binary packages",
    )
    release_text = run(
        "apt-ftparchive",
        *release_options,
        "release",
        "dists/stable",
        cwd=site,
        capture=True,
    ) + "\n"
    release_path = site / "dists/stable/Release"
    release_path.write_text(release_text, encoding="utf-8")

    shutil.copy2(repository_root / "medge-archive-keyring.gpg", site)
    shutil.copy2(repository_root / "medge.sources", site)
    if current_manifest.get("schema") == "medge-public-release/v15":
        release_scripts = RELEASE_SCRIPTS_V15
    elif current_manifest.get("schema") == "medge-public-release/v14":
        release_scripts = RELEASE_SCRIPTS_V14
    elif current_manifest.get("schema") == "medge-public-release/v13":
        release_scripts = RELEASE_SCRIPTS_V13
    elif current_manifest.get("schema") == "medge-public-release/v12":
        release_scripts = RELEASE_SCRIPTS_V12
    elif current_manifest.get("schema") == "medge-public-release/v11":
        release_scripts = RELEASE_SCRIPTS_V11
    elif current_manifest.get("medge_version") in V10_THREE_SCRIPT_RELEASES:
        release_scripts = tuple(INSTALLER_PROFILES_V10)
    else:
        release_scripts = RELEASE_SCRIPTS_V10
    for installer_name in release_scripts:
        shutil.copy2(current_bundle / installer_name, site)
    shutil.copy2(current_bundle / "release-manifest.json", site)
    (site / ".nojekyll").write_text("", encoding="utf-8")
    fingerprint = archive_fingerprint(repository_root)
    index = f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>Install Sphere Debian Repository</title>
<h1>Install Sphere Debian Repository</h1>
<p>Stable amd64 Sphere and Mote Transport Debian packages.</p>
<p>Current {len(current_manifest['packages'])}-package release: <code>{current_manifest['medge_version']}</code></p>
<p>Signing fingerprint: <code>{fingerprint}</code></p>
<pre>curl -fsSLo /tmp/sphere.sh \
https://motebus.github.io/download/sphere.sh &amp;&amp;
curl -fsSLo /tmp/release-manifest.json \
https://motebus.github.io/download/release-manifest.json &amp;&amp;
curl -fsSLo /tmp/release-manifest.json.asc \
https://motebus.github.io/download/release-manifest.json.asc &amp;&amp;
sudo bash /tmp/sphere.sh</pre>
<p>Profiles: <code>sphere.sh</code> (15 of 16; excludes ultra-mcp-ssh), <code>webdesk.sh</code>
(sphere + ss-webos + mdesk + mlink), and <code>sshkit.sh</code>
(Mote Transport prerequisites). <code>uninstall.sh</code> performs bounded,
signed cleanup of the Sphere package boundary.</p>
</html>
"""
    (site / "index.html").write_text(index, encoding="utf-8")


def sign_release(site: Path, repository_root: Path) -> None:
    passphrase = os.environ.get("MEDGE_APT_SIGNING_PASSPHRASE")
    require(passphrase is not None and passphrase != "", "signing passphrase is unavailable")
    fingerprint = archive_fingerprint(repository_root)
    secret_keys = run("gpg", "--batch", "--with-colons", "--list-secret-keys", fingerprint, capture=True)
    require(f"fpr:::::::::{fingerprint}:" in secret_keys, "expected private signing key is unavailable")
    release = site / "dists/stable/Release"
    detached = site / "dists/stable/Release.gpg"
    inline = site / "dists/stable/InRelease"
    manifest = site / "release-manifest.json"
    manifest_signature = site / "release-manifest.json.asc"
    common = (
        "gpg",
        "--batch",
        "--yes",
        "--pinentry-mode",
        "loopback",
        "--passphrase-fd",
        "0",
        "--local-user",
        fingerprint,
        "--digest-algo",
        "SHA256",
    )
    run(*common, "--armor", "--detach-sign", "--output", str(detached), str(release), input_text=passphrase + "\n")
    run(*common, "--armor", "--clearsign", "--output", str(inline), str(release), input_text=passphrase + "\n")
    run(
        *common,
        "--armor",
        "--detach-sign",
        "--output",
        str(manifest_signature),
        str(manifest),
        input_text=passphrase + "\n",
    )

    with tempfile.TemporaryDirectory(prefix="medge-public-gnupg-") as temp_name:
        env = {**os.environ, "GNUPGHOME": temp_name}
        os.chmod(temp_name, 0o700)
        run("gpg", "--batch", "--import", str(repository_root / "medge-archive-keyring.gpg"), env=env)
        run("gpg", "--batch", "--verify", str(detached), str(release), env=env)
        run("gpg", "--batch", "--verify", str(inline), env=env)
        run("gpg", "--batch", "--verify", str(manifest_signature), str(manifest), env=env)


def build_site(repository_root: Path, site: Path, bundles: list[Path]) -> None:
    require(len(bundles) == 1, "build requires exactly one current public bundle")
    manifests = [validate_bundle(bundle) for bundle in bundles]
    current = manifests[0]

    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    for package in current["packages"]:
        copy_package(bundles[0] / package["asset"], site)
    write_index(site, repository_root, current, bundles[0])
    validate_no_gitlab_urls(site)
    sign_release(site, repository_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    tree_parser = subparsers.add_parser("validate-tree")
    tree_parser.add_argument("root", type=Path)
    bundle_parser = subparsers.add_parser("validate-bundle")
    bundle_parser.add_argument("bundle", type=Path)
    transport_bundle_parser = subparsers.add_parser("validate-transport-bundle")
    transport_bundle_parser.add_argument("bundle", type=Path)
    previous_parser = subparsers.add_parser("previous-tag")
    previous_parser.add_argument("bundle", type=Path)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("repository_root", type=Path)
    build_parser.add_argument("site", type=Path)
    build_parser.add_argument("bundles", nargs="+", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "validate-tree":
            validate_tree(args.root)
        elif args.command == "validate-bundle":
            validate_bundle(args.bundle)
        elif args.command == "validate-transport-bundle":
            validate_transport_bundle(args.bundle)
        elif args.command == "previous-tag":
            print(validate_bundle(args.bundle)["previous_release_tag"])
        elif args.command == "build":
            build_site(args.repository_root, args.site, args.bundles)
    except (PublishError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
