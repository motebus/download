#!/usr/bin/env python3
"""Validate approved binary bundles and construct the signed MEdge APT site."""

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
EXPECTED_PACKAGES = AGENTIC_IO_PACKAGES + ("cx-node",)
HEADLESS_PACKAGES = (
    "sphered",
    "moted",
    "aport",
    "qbix",
    "mbox",
    "motestream",
    "motessh",
    "moterdp",
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
MCHAT_ENV_PACKAGES = {
    "moted", "aport", "qbix", "mbox", "motessh", "moterdp", "desk",
}
ALLOWED_ROOT_FILES = {
    ".gitignore",
    "github-setup.sh",
    "install.sh",
    "medge-install.sh",
    "webos-install.sh",
    "cx-install.sh",
    "LICENSE",
    "README.md",
    "medge-release.env",
    "medge.sources",
    "medge-archive-keyring.fingerprint",
    "medge-archive-keyring.gpg",
}
ALLOWED_ROOT_DIRS = {".git", ".github", "scripts", "tests"}


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
    return EXPECTED_PACKAGES


def expected_env_paths(package_name: str) -> list[str]:
    if package_name == "cx-node":
        return []
    paths = [f"{package_name}-deb.env"]
    if package_name in MCHAT_ENV_PACKAGES:
        paths.append(f"{package_name}-mchat.env")
    return paths


def validate_env_inputs(package: dict) -> None:
    name = package["name"]
    env_inputs = package.get("env_inputs")
    require(isinstance(env_inputs, list), f"{name}: env_inputs must be an array")
    require(
        [item.get("path") for item in env_inputs if isinstance(item, dict)]
        == expected_env_paths(name),
        f"{name}: env_inputs must be {expected_env_paths(name)}",
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


def validate_manifest(manifest: object) -> dict:
    require(isinstance(manifest, dict), "release-manifest.json must contain an object")
    expected_keys = {
        "schema", "status", "medge_version", "suite", "component", "architecture",
        "generated_at", "previous_release_tag", "approval", "packages",
    }
    if "rollback" in manifest:
        expected_keys.add("rollback")
    require(set(manifest) == expected_keys, "public release manifest fields are invalid")
    require(
        manifest.get("schema") in {
            "medge-public-release/v4",
            "medge-public-release/v5",
            "medge-public-release/v6",
            "medge-public-release/v7",
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
        }:
            validate_env_inputs(package)
    require_no_gitlab_url_bytes(
        json.dumps(manifest, sort_keys=True).encode("utf-8"),
        "release-manifest.json",
    )
    return manifest


def verify_checksums(bundle: Path) -> None:
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


def validate_bundle(bundle: Path) -> dict:
    manifest_path = bundle / "release-manifest.json"
    require(manifest_path.is_file(), f"{bundle}: missing release-manifest.json")
    manifest = validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    verify_checksums(bundle)

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

    require(
        list(bundle.glob("medge_*_all.deb")) == [],
        "v4 bundle must not contain retired medge.deb",
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
    required_installers = ["medge-install.sh", "webos-install.sh"]
    if "cx-node" in expected_packages(manifest):
        required_installers.append("cx-install.sh")
    for name in required_installers:
        installer = bundle / name
        require(installer.is_file(), f"bundle is missing {name}")
        run("sh", "-n", str(installer))
    require(not (bundle / "install.sh").exists(), "v4 bundle must not contain install.sh")
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
    installer = root / "install.sh"
    require(installer.is_file(), "public repository is missing install.sh")
    require(installer.stat().st_mode & 0o111 != 0, "install.sh must be executable")
    run("sh", "-n", str(installer))
    for name in ("medge-install.sh", "webos-install.sh"):
        wrapper = root / name
        require(wrapper.is_file(), f"public repository is missing {name}")
        require(wrapper.stat().st_mode & 0o111 != 0, f"{name} must be executable")
        run("sh", "-n", str(wrapper))
    cx_installer = root / "cx-install.sh"
    require(cx_installer.is_file(), "public repository is missing cx-install.sh")
    require(cx_installer.stat().st_mode & 0o111 != 0, "cx-install.sh must be executable")
    run("sh", "-n", str(cx_installer))
    installer_text = installer.read_text(encoding="utf-8")
    for required_text in (
        "https://motebus.github.io/medge-release",
        "RETIRED_BASE_URL=\"https://motebus.github.io/medge-deb\"",
        fingerprint,
        "ubuntu:24.04|ubuntu:26.04)",
        "apt-get install -y $APT_PACKAGES",
        "apt-get --print-uris -y install $APT_PACKAGES",
        "apt-get remove -y --no-auto-remove $INSTALLED_RETIRED",
        "APT has broken dependencies after stale MEdge meta-package recovery",
        "dpkg --remove medge",
        "forbidden GitLab URL",
        "STOP_SYSTEM_UNITS=",
        'systemctl disable "$unit"',
        'systemctl stop "$unit"',
        'systemctl enable "$unit"',
        'systemctl start "$unit"',
        "systemctl is-active --quiet",
        'systemctl show "$unit" -p NRestarts --value',
        'sleep "$SERVICE_STABILITY_SECONDS"',
        'systemctl reset-failed "$failed_unit"',
        "/usr/libexec/ss-webos/install-desktop-shortcut",
    ):
        require(
            required_text in installer_text,
            f"install.sh is missing required contract: {required_text}",
        )
    for forbidden_text in (
        "apt-key",
        "trusted=yes",
        "/etc/hosts",
        "systemctl edit",
        "systemctl enable --now",
        "MCHAT_",
        "gitlab.",
    ):
        require(
            forbidden_text not in installer_text,
            f"install.sh contains forbidden content: {forbidden_text}",
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


def write_index(site: Path, repository_root: Path, current_manifest: dict) -> None:
    packages_dir = site / "dists/stable/main/binary-amd64"
    packages_dir.mkdir(parents=True, exist_ok=True)
    packages_text = run("apt-ftparchive", "packages", "pool", cwd=site, capture=True) + "\n"
    (packages_dir / "Packages").write_text(packages_text, encoding="utf-8")
    (packages_dir / "Packages.gz").write_bytes(
        gzip.compress(packages_text.encode("utf-8"), mtime=0)
    )

    release_options = (
        "-o", "APT::FTPArchive::Release::Origin=MoteBus",
        "-o", "APT::FTPArchive::Release::Label=MEdge",
        "-o", "APT::FTPArchive::Release::Suite=stable",
        "-o", "APT::FTPArchive::Release::Codename=stable",
        "-o", "APT::FTPArchive::Release::Architectures=amd64",
        "-o", "APT::FTPArchive::Release::Components=main",
        "-o", "APT::FTPArchive::Release::Description=MEdge binary packages",
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
    shutil.copy2(repository_root / "install.sh", site)
    shutil.copy2(repository_root / "medge-install.sh", site)
    shutil.copy2(repository_root / "webos-install.sh", site)
    shutil.copy2(repository_root / "cx-install.sh", site)
    (site / ".nojekyll").write_text("", encoding="utf-8")
    fingerprint = archive_fingerprint(repository_root)
    index = f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>MEdge Debian Repository</title>
<h1>MEdge Debian Repository</h1>
<p>Stable amd64 MEdge and CX Node binary packages.</p>
<p>Current {len(current_manifest['packages'])}-package release: <code>{current_manifest['medge_version']}</code></p>
<p>Signing fingerprint: <code>{fingerprint}</code></p>
<pre>curl -fsSLo /tmp/medge-install.sh \
https://motebus.github.io/medge-release/medge-install.sh &amp;&amp;
sudo sh /tmp/medge-install.sh</pre>
<pre>curl -fsSLo /tmp/cx-install.sh \
https://motebus.github.io/medge-release/cx-install.sh</pre>
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

    with tempfile.TemporaryDirectory(prefix="medge-public-gnupg-") as temp_name:
        env = {**os.environ, "GNUPGHOME": temp_name}
        os.chmod(temp_name, 0o700)
        run("gpg", "--batch", "--import", str(repository_root / "medge-archive-keyring.gpg"), env=env)
        run("gpg", "--batch", "--verify", str(detached), str(release), env=env)
        run("gpg", "--batch", "--verify", str(inline), env=env)


def build_site(repository_root: Path, site: Path, bundles: list[Path]) -> None:
    require(len(bundles) == 1, "build requires exactly one current public bundle")
    manifests = [validate_bundle(bundle) for bundle in bundles]
    current = manifests[0]

    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    for package in current["packages"]:
        copy_package(bundles[0] / package["asset"], site)
    write_index(site, repository_root, current)
    validate_no_gitlab_urls(site)
    sign_release(site, repository_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    tree_parser = subparsers.add_parser("validate-tree")
    tree_parser.add_argument("root", type=Path)
    bundle_parser = subparsers.add_parser("validate-bundle")
    bundle_parser.add_argument("bundle", type=Path)
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
        elif args.command == "previous-tag":
            print(validate_bundle(args.bundle)["previous_release_tag"])
        elif args.command == "build":
            build_site(args.repository_root, args.site, args.bundles)
    except (PublishError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
