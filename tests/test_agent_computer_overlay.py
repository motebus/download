from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import test_publish_apt as fixtures


publish_apt = fixtures.publish_apt


class AgentComputerOverlayTest(unittest.TestCase):
    def make_overlay(self, root: Path) -> tuple[Path, dict]:
        bundle = root / "overlay"
        bundle.mkdir()
        packages = []
        for name, architecture in publish_apt.AGENT_COMPUTER_OVERLAY_PACKAGES:
            version = "0.1.0-1" if name == "agent-sphere" else "2.0.0-5"
            asset = fixtures.PublicAptTest().make_deb(
                root / "build", package=name, version=version, architecture=architecture,
            )
            shutil.copy2(asset, bundle)
            packages.append({"name": name, "version": version, "architecture": architecture,
                             "asset": asset.name, "sha256": publish_apt.sha256(asset)})
        config = {"schema": publish_apt.AGENT_COMPUTER_OVERLAY_SCHEMA, "release": {
            "repository": "motebus/agent-sphere-deb", "tag": "v0.1.0-1", "packages": packages}}
        self.write_config(root, config)
        return bundle, config

    def write_config(self, root: Path, config: dict) -> None:
        (root / publish_apt.AGENT_COMPUTER_OVERLAY_FILE).write_text(json.dumps(config) + "\n")

    def test_disabled_overlay_does_not_download_or_accept_hidden_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_config(root, {"schema": publish_apt.AGENT_COMPUTER_OVERLAY_SCHEMA, "release": None})
            with mock.patch.object(publish_apt, "run") as run:
                publish_apt.download_agent_computer_overlay(root, root / "overlay")
                run.assert_not_called()
            (root / "overlay").mkdir()
            (root / "overlay/unapproved.deb").write_bytes(b"not admitted")
            with self.assertRaisesRegex(publish_apt.PublishError, "disabled.*must not contain"):
                publish_apt.validate_agent_computer_overlay(root, root / "overlay")

    def test_exact_overlay_identity_and_payload_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, config = self.make_overlay(root)
            self.assertEqual(publish_apt.validate_agent_computer_overlay(root, bundle), config)
            # Even a newly approved digest cannot hide incorrect Debian control metadata.
            asset = bundle / config["release"]["packages"][0]["asset"]
            wrong = fixtures.PublicAptTest().make_deb(root / "wrong", package="agent-app")
            shutil.copyfile(wrong, asset)
            config["release"]["packages"][0]["sha256"] = publish_apt.sha256(asset)
            self.write_config(root, config)
            with self.assertRaisesRegex(publish_apt.PublishError, "overlay Package mismatch"):
                publish_apt.validate_agent_computer_overlay(root, bundle)

    def test_overlay_rejects_source_scope_names_architecture_and_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, original = self.make_overlay(root)
            mutations = [
                lambda c: c["release"].update(repository="motebus/unapproved"),
                lambda c: c["release"].update(tag="latest"),
                lambda c: c["release"].update(tag="v0.1.0-2"),
                lambda c: c["release"]["packages"].reverse(),
                lambda c: c["release"]["packages"][0].update(name="agent-app"),
                lambda c: c["release"]["packages"][0].update(name="agent-apps"),
                lambda c: c["release"]["packages"][1].update(name="agos"),
                lambda c: c["release"]["packages"][0].update(architecture="amd64"),
                lambda c: c["release"]["packages"][0].update(asset="../escape.deb"),
                lambda c: c["release"]["packages"][0].update(sha256="unverified"),
                lambda c: c["release"]["packages"].append(copy.deepcopy(c["release"]["packages"][0])),
                lambda c: c.update(allow_other_sources=True),
            ]
            for mutation in mutations:
                config = copy.deepcopy(original)
                mutation(config)
                self.write_config(root, config)
                with self.subTest(config=config), self.assertRaises(publish_apt.PublishError):
                    publish_apt.load_agent_computer_overlay(root)

    def test_overlay_requires_every_pinned_asset_and_rejects_tamper_symlinks_and_extras(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, config = self.make_overlay(root)
            asset = bundle / config["release"]["packages"][0]["asset"]
            original = asset.read_bytes()
            asset.write_bytes(original + b"changed")
            with self.assertRaisesRegex(publish_apt.PublishError, "overlay digest mismatch"):
                publish_apt.validate_agent_computer_overlay(root, bundle)
            asset.unlink()
            with self.assertRaisesRegex(publish_apt.PublishError, "exactly the approved assets"):
                publish_apt.validate_agent_computer_overlay(root, bundle)
            external = root / "external.deb"
            external.write_bytes(original)
            asset.symlink_to(external)
            with self.assertRaisesRegex(publish_apt.PublishError, "not a regular file"):
                publish_apt.validate_agent_computer_overlay(root, bundle)
            asset.unlink()
            asset.write_bytes(original)
            (bundle / "agent-app.deb").write_bytes(b"unapproved")
            with self.assertRaisesRegex(publish_apt.PublishError, "exactly the approved assets"):
                publish_apt.validate_agent_computer_overlay(root, bundle)

    def test_active_overlay_cannot_be_silently_omitted_on_next_base_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_overlay(root)
            for missing in (None, root / "not-downloaded"):
                with self.assertRaisesRegex(publish_apt.PublishError, "requires its downloaded bundle"):
                    publish_apt.validate_agent_computer_overlay(root, missing)

    def test_download_uses_only_exact_published_repo_tag_and_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, config = self.make_overlay(root)
            destination = root / "download"
            original_run = publish_apt.run
            commands = []

            def run(*args: str, **kwargs: object) -> str:
                if args[0] != "gh":
                    return original_run(*args, **kwargs)
                commands.append(args)
                self.assertIn("motebus/agent-sphere-deb", args)
                self.assertIn("v0.1.0-1", args)
                if args[2] == "view":
                    return json.dumps({"tagName": "v0.1.0-1", "isDraft": False,
                                       "assets": [{"name": p["asset"]} for p in config["release"]["packages"]]})
                for package in config["release"]["packages"]:
                    self.assertIn(package["asset"], args)
                    shutil.copy2(source / package["asset"], destination)
                return ""

            with mock.patch.object(publish_apt, "run", side_effect=run):
                publish_apt.download_agent_computer_overlay(root, destination)
            self.assertEqual([command[2] for command in commands], ["view", "download"])
            self.assertEqual(publish_apt.validate_agent_computer_overlay(root, destination), config)

    def test_draft_release_cannot_reach_download_or_signing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_overlay(root)
            with mock.patch.object(publish_apt, "run", return_value=json.dumps({
                "tagName": "v0.1.0-1", "isDraft": True, "assets": []})) as run:
                with self.assertRaisesRegex(publish_apt.PublishError, "exact published release"):
                    publish_apt.download_agent_computer_overlay(root, root / "download")
                self.assertEqual(run.call_count, 1)

    def test_overlay_is_in_apt_index_while_v18_manifest_and_installers_stay_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            overlay, config = self.make_overlay(root)
            bundle = root / "base"
            bundle.mkdir()
            manifest = fixtures.PublicAptTest().manifest("medge-public-release/v18")
            for package in manifest["packages"]:
                asset = fixtures.PublicAptTest().make_deb(root / "base-build", package=package["name"],
                    version=package["version"], architecture=package["architecture"])
                shutil.copy2(asset, bundle)
                package["sha256"] = publish_apt.sha256(asset)
            for installer in manifest["installers"]:
                script = bundle / installer["name"]
                script.write_text("#!/bin/bash\nset -euo pipefail\n")
                script.chmod(0o755)
                installer["sha256"] = publish_apt.sha256(script)
            manifest_path = bundle / "release-manifest.json"
            manifest_path.write_text(json.dumps(manifest))
            checksums = "".join(f"{publish_apt.sha256(path)}  {path.name}\n" for path in sorted(bundle.iterdir()))
            (bundle / "SHA256SUMS").write_text(checksums)
            repo = Path(__file__).parents[1]
            for name in ("medge-archive-keyring.gpg", "medge-archive-keyring.fingerprint", "medge.sources",
                         *publish_apt.AGENT_INSTALLER_FILES):
                shutil.copy2(repo / name, root)
            site = root / "site"
            with mock.patch.object(publish_apt, "sign_release") as sign:
                publish_apt.build_site(root, site, [bundle], overlay)
                sign.assert_called_once_with(site, root)
            packages_text = (site / "dists/stable/main/binary-amd64/Packages").read_text()
            names = [line.removeprefix("Package: ") for line in packages_text.splitlines() if line.startswith("Package: ")]
            self.assertCountEqual(names, [p["name"] for p in manifest["packages"]]
                                  + [p["name"] for p in config["release"]["packages"]])
            self.assertEqual(len(names), 19)
            self.assertEqual((site / "release-manifest.json").read_bytes(), manifest_path.read_bytes())
            self.assertEqual(json.loads((site / publish_apt.AGENT_COMPUTER_OVERLAY_FILE).read_text()), config)
            self.assertIn("apt install agent-sphere", (site / "index.html").read_text())
            self.assertIn("agent-apps", (site / "index.html").read_text())
            self.assertNotIn("<code>agent-app</code>", (site / "index.html").read_text())
            for name in publish_apt.AGENT_INSTALLER_FILES:
                self.assertEqual((site / name).read_bytes(), (repo / name).read_bytes())
                self.assertIn(f'href="{name}"', (site / "index.html").read_text())
            for installer in manifest["installers"]:
                self.assertEqual((site / installer["name"]).read_bytes(), (bundle / installer["name"]).read_bytes())
            self.assertEqual(len(publish_apt.EXPECTED_PACKAGES_V18), 17)
            self.assertNotIn("agent-sphere", publish_apt.INSTALLER_PROFILES_V18["sphere.sh"])
            self.assertNotIn("mote-transportd", publish_apt.INSTALLER_PROFILES_V19["sphere.sh"])


if __name__ == "__main__":
    unittest.main()
