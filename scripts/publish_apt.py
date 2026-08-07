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


EXPECTED_PACKAGES = (
    "sphered",
    "mgate",
    "ss-webos",
    "moted",
    "agos",
    "qbix",
    "qbix-func",
    "mote",
    "desk",
)
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
FINGERPRINT_RE = re.compile(r"^[0-9A-F]{40}$")
TAG_RE = re.compile(r"^medge-v[0-9]+\.[0-9]+\.[0-9]+-[0-9]+$")
ALLOWED_ROOT_FILES = {
    ".gitignore",
    "github-setup.sh",
    "install.sh",
    "LICENSE",
    "README.md",
    "medge-deb.env",
    "medge.sources",
    "medge-archive-keyring.fingerprint",
    "medge-archive-keyring.gpg",
}
ALLOWED_ROOT_DIRS = {".git", ".github", "scripts"}


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
    return ", ".join(
        f"{package['name']} (= {package['version']})" for package in manifest["packages"]
    )


def validate_manifest(manifest: object) -> dict:
    require(isinstance(manifest, dict), "release-manifest.json must contain an object")
    require(manifest.get("schema") == "medge-release/v1", "invalid release manifest schema")
    require(manifest.get("status") == "approved", "release manifest is not approved")
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
    require(
        isinstance(packages, list) and len(packages) == len(EXPECTED_PACKAGES),
        f"release must contain {len(EXPECTED_PACKAGES)} components",
    )
    require(
        [package.get("name") for package in packages] == list(EXPECTED_PACKAGES),
        "release component set or order is invalid",
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

    meta = bundle / f"medge_{manifest['medge_version']}_all.deb"
    require(meta.is_file(), "bundle is missing the medge meta-package")
    require(package_field(meta, "Package") == "medge", "invalid meta-package name")
    require(package_field(meta, "Architecture") == "all", "medge must be Architecture: all")
    require(package_field(meta, "Version") == manifest["medge_version"], "medge version mismatch")
    require(package_field(meta, "Depends") == expected_depends(manifest), "medge dependency closure mismatch")
    with tempfile.TemporaryDirectory(prefix="medge-control-") as temp_name:
        run("dpkg-deb", "-e", str(meta), temp_name)
        for name in ("preinst", "postinst", "prerm", "postrm", "config"):
            require(not (Path(temp_name) / name).exists(), f"medge contains forbidden {name}")

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
    installer_text = installer.read_text(encoding="utf-8")
    for required_text in (
        "https://motebus.github.io/medge-deb",
        fingerprint,
        "apt-get install -y medge",
        "STOP_SYSTEM_UNITS=",
        'systemctl disable "$unit"',
        'systemctl stop "$unit"',
        'systemctl enable "$unit"',
        'systemctl start "$unit"',
        "systemctl is-active --quiet",
        'systemctl show "$unit" -p NRestarts --value',
        'sleep "$SERVICE_STABILITY_SECONDS"',
        'systemctl reset-failed "$failed_unit"',
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
    ):
        require(
            forbidden_text not in installer_text,
            f"install.sh contains forbidden content: {forbidden_text}",
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
    (site / ".nojekyll").write_text("", encoding="utf-8")
    fingerprint = archive_fingerprint(repository_root)
    index = f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>MEdge Debian Repository</title>
<h1>MEdge Debian Repository</h1>
<p>Stable Ubuntu 24.04 amd64 binary packages.</p>
<p>Current meta-package: <code>medge {current_manifest['medge_version']}</code></p>
<p>Signing fingerprint: <code>{fingerprint}</code></p>
<pre>curl -fsSLo /tmp/medge-install.sh \
https://motebus.github.io/medge-deb/install.sh &amp;&amp;
sudo sh /tmp/medge-install.sh</pre>
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
    require(len(bundles) in {1, 2}, "build requires the current bundle and at most one previous bundle")
    manifests = [validate_bundle(bundle) for bundle in bundles]
    current = manifests[0]
    previous_tag = current["previous_release_tag"]
    require(
        (previous_tag == "" and len(bundles) == 1)
        or (previous_tag != "" and len(bundles) == 2),
        "previous release bundle does not match the current manifest",
    )
    if len(manifests) == 2:
        require(
            previous_tag == f"medge-v{manifests[1]['medge_version']}",
            "previous release version does not match previous_release_tag",
        )

    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    for package in current["packages"]:
        copy_package(bundles[0] / package["asset"], site)
    copy_package(
        bundles[0] / f"medge_{current['medge_version']}_all.deb",
        site,
    )
    write_index(site, repository_root, current)
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
