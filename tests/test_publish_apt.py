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
    def manifest(self) -> dict:
        packages = []
        for index, name in enumerate(publish_apt.EXPECTED_PACKAGES, start=1):
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
        return {
            "schema": "medge-public-release/v4",
            "status": "approved",
            "medge_version": "3.2.0-1",
            "suite": "stable",
            "component": "main",
            "architecture": "amd64",
            "generated_at": now,
            "previous_release_tag": "medge-v3.1.0-15",
            "approval": {"id": "approval-9", "approved_by": "owner", "approved_at": now},
            "packages": packages,
        }

    def make_deb(self, root: Path, homepage: str = "") -> Path:
        package_root = root / "package"
        (package_root / "DEBIAN").mkdir(parents=True)
        fields = [
            "Package: test-public",
            "Version: 1.0.0-1",
            "Architecture: amd64",
            "Maintainer: Test <test@example.invalid>",
        ]
        if homepage:
            fields.append(f"Homepage: {homepage}")
        fields.extend(("Description: public package", ""))
        (package_root / "DEBIAN/control").write_text("\n".join(fields), encoding="utf-8")
        asset = root / "test-public_1.0.0-1_amd64.deb"
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
            asset = self.make_deb(Path(temp_name), "https://github.com/motebus/medge-deb")
            publish_apt.validate_public_deb_content(asset)
            self.assertEqual(len(hashlib.sha256(asset.read_bytes()).hexdigest()), 64)


if __name__ == "__main__":
    unittest.main()
