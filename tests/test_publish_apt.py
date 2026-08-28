from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


MODULE_PATH = Path(__file__).parents[1] / "scripts/publish_apt.py"
SPEC = importlib.util.spec_from_file_location("publish_apt", MODULE_PATH)
assert SPEC and SPEC.loader
publish_apt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publish_apt)


class PublicAptTest(unittest.TestCase):
    def manifest(self, schema: str = "medge-public-release/v8") -> dict:
        package_names = (
            publish_apt.LEGACY_PACKAGES
            if schema in {"medge-public-release/v4", "medge-public-release/v5"}
            else (
                publish_apt.AGENTIC_IO_PACKAGES
                if schema == "medge-public-release/v6"
                else (
                    publish_apt.CX_AGENTIC_IO_PACKAGES
                    if schema == "medge-public-release/v7"
                    else publish_apt.EXPECTED_PACKAGES
                )
            )
        )
        packages = []
        for index, name in enumerate(package_names, start=1):
            version = f"1.0.0-{index}"
            packages.append(
                {
                    "name": name,
                    "version": version,
                    "architecture": "amd64",
                    "asset": f"{name}_{version}_amd64.deb",
                    "source_commit": f"{index:x}" * 40,
                    "source_ref": "refs/heads/main",
                    "sha256": f"{index:x}" * 64,
                }
            )
        now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        manifest = {
            "schema": schema,
            "status": "approved",
            "medge_version": "5.0.0-1" if schema == "medge-public-release/v8" else "4.2.0-1",
            "suite": "stable",
            "component": "main",
            "architecture": "amd64",
            "generated_at": now,
            "previous_release_tag": "medge-v3.1.0-15",
            "approval": {"id": "approval-9", "approved_by": "owner", "approved_at": now},
            "packages": packages,
        }
        if schema in {
            "medge-public-release/v5",
            "medge-public-release/v6",
            "medge-public-release/v7",
            "medge-public-release/v8",
        }:
            for package in manifest["packages"]:
                package["env_inputs"] = [
                    {"path": path, "sha256": package["sha256"]}
                    for path in publish_apt.expected_env_paths(package["name"])
                ]
        return manifest

    def make_deb(
        self,
        root: Path,
        homepage: str = "",
        package: str = "test-public",
        version: str = "1.0.0-1",
        architecture: str = "amd64",
    ) -> Path:
        package_root = root / f"package-{package}"
        (package_root / "DEBIAN").mkdir(parents=True)
        fields = [
            f"Package: {package}",
            f"Version: {version}",
            f"Architecture: {architecture}",
            "Maintainer: Test <test@example.invalid>",
        ]
        if homepage:
            fields.append(f"Homepage: {homepage}")
        fields.extend(("Description: public package", ""))
        (package_root / "DEBIAN/control").write_text("\n".join(fields), encoding="utf-8")
        asset = root / f"{package}_{version}_{architecture}.deb"
        subprocess.run(
            ["dpkg-deb", "--build", "--root-owner-group", str(package_root), str(asset)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        return asset

    def test_public_manifest_has_no_private_url_fields(self) -> None:
        manifest = self.manifest()
        self.assertEqual(publish_apt.validate_manifest(manifest), manifest)
        self.assertNotIn("gitlab", json.dumps(manifest).lower())
        forbidden_url = "https://" + "gitlab" + ".example.invalid/job/1"
        manifest["packages"][0]["artifact_url"] = forbidden_url
        with self.assertRaisesRegex(publish_apt.PublishError, "fields are invalid"):
            publish_apt.validate_manifest(manifest)

    def test_v5_manifest_requires_exact_git_env_provenance(self) -> None:
        manifest = self.manifest("medge-public-release/v5")
        self.assertEqual(publish_apt.validate_manifest(manifest), manifest)

        del manifest["packages"][0]["env_inputs"]
        with self.assertRaisesRegex(publish_apt.PublishError, "fields are invalid"):
            publish_apt.validate_manifest(manifest)

        manifest = self.manifest("medge-public-release/v5")
        manifest["packages"][1]["env_inputs"].reverse()
        with self.assertRaisesRegex(publish_apt.PublishError, "env_inputs must be"):
            publish_apt.validate_manifest(manifest)

    def test_v6_manifest_has_exact_agentic_io_package_set(self) -> None:
        manifest = self.manifest("medge-public-release/v6")
        self.assertEqual(
            [package["name"] for package in manifest["packages"]],
            list(publish_apt.AGENTIC_IO_PACKAGES),
        )
        self.assertEqual(publish_apt.validate_manifest(manifest), manifest)

    def test_v7_manifest_keeps_historical_cx_node_set(self) -> None:
        manifest = self.manifest("medge-public-release/v7")
        self.assertEqual(
            [package["name"] for package in manifest["packages"]],
            list(publish_apt.CX_AGENTIC_IO_PACKAGES),
        )
        cx_node = manifest["packages"][-1]
        self.assertEqual(cx_node["name"], "cx-node")
        self.assertEqual(cx_node["env_inputs"], [])
        self.assertEqual(publish_apt.validate_manifest(manifest), manifest)

    def test_v8_manifest_has_only_compliant_medge_packages(self) -> None:
        manifest = self.manifest("medge-public-release/v8")
        self.assertEqual(
            [package["name"] for package in manifest["packages"]],
            ["sphere", "moted", "aport", "qbix", "mbox", "desk", "ss-webos"],
        )
        self.assertEqual(publish_apt.validate_manifest(manifest), manifest)

    def test_v5_manifest_keeps_historical_eight_package_set(self) -> None:
        manifest = self.manifest("medge-public-release/v5")
        self.assertEqual(
            [package["name"] for package in manifest["packages"]],
            list(publish_apt.LEGACY_PACKAGES),
        )
        self.assertEqual(publish_apt.validate_manifest(manifest), manifest)

    def test_deb_with_gitlab_url_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            asset = self.make_deb(
                Path(temp_name),
                "https://" + "gitlab" + ".example.invalid/private/package",
            )
            with self.assertRaisesRegex(publish_apt.PublishError, "GitLab URL is forbidden"):
                publish_apt.validate_public_deb_content(asset)

    def test_deb_without_gitlab_url_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            asset = self.make_deb(Path(temp_name), "https://github.com/motebus/medge-release")
            publish_apt.validate_public_deb_content(asset)
            self.assertEqual(len(hashlib.sha256(asset.read_bytes()).hexdigest()), 64)

    def test_mote_transport_bundle_is_exact_and_digest_pinned(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            bundle = Path(temp_name)
            packages = []
            for index, (name, version, architecture) in enumerate(
                publish_apt.MOTE_TRANSPORT_PACKAGES, start=1
            ):
                asset = self.make_deb(
                    bundle,
                    package=name,
                    version=version,
                    architecture=architecture,
                )
                packages.append(
                    {
                        "name": name,
                        "version": version,
                        "architecture": architecture,
                        "asset": asset.name,
                        "sha256": publish_apt.sha256(asset),
                        "source_ref": "refs/heads/main",
                        "source_commit": f"{index:x}" * 40,
                        "pipeline_id": index,
                        "env_inputs": [
                            {"path": path, "sha256": f"{index:x}" * 64}
                            for path in publish_apt.expected_env_paths(name)
                        ],
                    }
                )
            installer = bundle / "install-mote-transport.sh"
            installer.write_text("#!/usr/bin/env bash\nset -euo pipefail\n", encoding="utf-8")
            manifest = {
                "schema": publish_apt.MOTE_TRANSPORT_SCHEMA,
                "tag": "mote-transport-v2026.08.28-1",
                "status": "approved",
                "generated_at": "2026-08-28T12:00:00Z",
                "source_ref": "refs/heads/main",
                "source_commit": "a" * 40,
                "distribution": "github-release-assets",
                "approval": {
                    "approved_by": "repository-owner",
                    "approved_at": "2026-08-28T12:00:00Z",
                    "request": "push install to github",
                },
                "packages": packages,
                "installer": {
                    "asset": installer.name,
                    "sha256": publish_apt.sha256(installer),
                },
            }
            manifest_path = bundle / "release-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            checksum_targets = [
                *(bundle / package["asset"] for package in packages),
                installer,
                manifest_path,
            ]
            (bundle / "SHA256SUMS").write_text(
                "".join(
                    f"{publish_apt.sha256(path)}  {path.name}\n"
                    for path in checksum_targets
                ),
                encoding="utf-8",
            )
            self.assertEqual(publish_apt.validate_transport_bundle(bundle), manifest)

            manifest["packages"][1]["version"] = "3.2.0-25"
            with self.assertRaisesRegex(
                publish_apt.PublishError, "Mote Transport package identity is invalid"
            ):
                publish_apt.validate_transport_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
