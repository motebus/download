from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import test_publish_apt as fixtures


publish_apt = fixtures.publish_apt
REPOSITORY = Path(__file__).parents[1]


class AgentAppsInstallerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in publish_apt.AGENT_INSTALLER_FILES:
            shutil.copy2(REPOSITORY / name, self.root)
        self.installer = self.root / publish_apt.AGENT_APPS_INSTALLER
        self.source = self.root / publish_apt.AGENT_APPS_INSTALLER_SOURCE

    def test_snapshot_matches_the_reviewed_v0204_release(self) -> None:
        record = publish_apt.validate_agent_apps_installer(self.root)
        self.assertEqual(record["repository"], "motebus/agent-sphere-deb")
        self.assertEqual(record["tag"], "v0.2.0-4")
        self.assertEqual(record["source_commit"], "ffd247044c9721282134dacd01935185aa6ff493")
        self.assertEqual(record["sha256"],
                         "99d64206bee3a1e195e86f39ba9551cb370925e743d908cbd05a8081d6ae78ba")

    def test_missing_or_symlinked_input_fails(self) -> None:
        for path in (self.installer, self.source):
            with self.subTest(path=path.name):
                content = path.read_bytes()
                mode = path.stat().st_mode
                path.unlink()
                with self.assertRaisesRegex(publish_apt.PublishError, "missing regular"):
                    publish_apt.validate_agent_apps_installer(self.root)
                path.symlink_to(REPOSITORY / path.name)
                with self.assertRaisesRegex(publish_apt.PublishError, "missing regular"):
                    publish_apt.validate_agent_apps_installer(self.root)
                path.unlink()
                path.write_bytes(content)
                path.chmod(mode)

    def test_tampered_or_nonexecutable_script_fails(self) -> None:
        content = self.installer.read_bytes()
        self.installer.write_bytes(content + b"# modified\n")
        with self.assertRaisesRegex(publish_apt.PublishError, "digest mismatch"):
            publish_apt.validate_agent_apps_installer(self.root)
        self.installer.write_bytes(content)
        self.installer.chmod(0o644)
        with self.assertRaisesRegex(publish_apt.PublishError, "must be executable"):
            publish_apt.validate_agent_apps_installer(self.root)

    def test_compatibility_aliases_must_be_regular_and_byte_identical(self) -> None:
        for name in publish_apt.AGENT_INSTALLER_ALIASES:
            alias = self.root / name
            original = alias.read_bytes()
            mode = alias.stat().st_mode
            with self.subTest(alias=name):
                alias.write_bytes(original + b"changed")
                with self.assertRaisesRegex(publish_apt.PublishError, "alias differs"):
                    publish_apt.validate_agent_apps_installer(self.root)
                alias.unlink()
                alias.symlink_to(REPOSITORY / name)
                with self.assertRaisesRegex(publish_apt.PublishError, "missing regular installer alias"):
                    publish_apt.validate_agent_apps_installer(self.root)
                alias.unlink()
                alias.write_bytes(original)
                alias.chmod(mode)
        alias = self.root / publish_apt.AGENT_INSTALLER_ALIASES[0]
        alias.chmod(0o644)
        with self.assertRaisesRegex(publish_apt.PublishError, "alias must be executable"):
            publish_apt.validate_agent_apps_installer(self.root)

    def test_invalid_shell_fails_even_when_its_digest_is_updated(self) -> None:
        self.installer.write_text("#!/bin/bash\nif then\n")
        record = json.loads(self.source.read_text())
        record["sha256"] = publish_apt.sha256(self.installer)
        self.source.write_text(json.dumps(record))
        with self.assertRaises(subprocess.CalledProcessError):
            publish_apt.validate_agent_apps_installer(self.root)

    def test_source_scope_and_identity_cannot_drift(self) -> None:
        original = json.loads(self.source.read_text())
        changes = [
            {"repository": "motebus/other"}, {"tag": "latest"},
            {"asset": "../agent-sphere-apps.sh"}, {"source_commit": "main"},
            {"sha256": "unverified"}, {"schema": "unknown"}, {"download": True},
        ]
        for change in changes:
            with self.subTest(change=change):
                altered = copy.deepcopy(original)
                altered.update(change)
                self.source.write_text(json.dumps(altered))
                with self.assertRaises(publish_apt.PublishError):
                    publish_apt.validate_agent_apps_installer(self.root)

    def test_missing_snapshot_stops_build_before_replacing_site(self) -> None:
        self.installer.unlink()
        site = self.root / "site"
        site.mkdir()
        marker = site / "existing"
        marker.write_text("preserved")
        with mock.patch.object(publish_apt, "sign_release") as sign:
            with self.assertRaisesRegex(publish_apt.PublishError, "missing regular"):
                publish_apt.build_site(self.root, site, [self.root / "bundle"])
            sign.assert_not_called()
        self.assertEqual(marker.read_text(), "preserved")

    def test_staged_record_drift_fails_before_accessing_signing_key(self) -> None:
        site = self.root / "site"
        site.mkdir()
        for name in publish_apt.AGENT_INSTALLER_FILES:
            shutil.copy2(self.root / name, site)
        staged_source = site / self.source.name
        record = json.loads(staged_source.read_text())
        record["tag"] = "v0.1.0-3"
        staged_source.write_text(json.dumps(record))
        (site / publish_apt.AGENT_INSTALLER_ALIASES[1]).write_bytes(staged_source.read_bytes())
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(publish_apt.PublishError, "differs from the reviewed record"):
                publish_apt.sign_release(site, self.root)


if __name__ == "__main__":
    unittest.main()
