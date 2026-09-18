"""Reject tampering before macOS preview publication/signing."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
import test_publish_apt as fixtures

p = fixtures.publish_apt
ROOT = Path(__file__).parents[1]

class MacPublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in p.AGENT_INSTALLER_FILES:
            shutil.copy2(ROOT / name, self.root)

    def test_record_matches_assets(self):
        self.assertEqual(p.validate_mac_installer(self.root)["status"], "preflight-only")

    def test_tampered_and_missing_script_rejected(self):
        script = self.root / "agpc-mac.sh"
        script.write_text(script.read_text() + "# tampered\n")
        with self.assertRaisesRegex(p.PublishError, "digest mismatch"):
            p.validate_mac_installer(self.root)
        script.unlink()
        with self.assertRaisesRegex(p.PublishError, "missing regular"):
            p.validate_mac_installer(self.root)
        script.symlink_to(ROOT / "agpc-mac.sh")
        with self.assertRaisesRegex(p.PublishError, "missing regular"):
            p.validate_mac_installer(self.root)

    def test_staged_metadata_drift_rejected_before_key_access(self):
        site = self.root / "site"
        site.mkdir()
        for name in p.AGENT_INSTALLER_FILES:
            shutil.copy2(self.root / name, site)
        record_path = site / "agpc.mac.source.json"
        record = json.loads(record_path.read_text())
        record["tag"] = "agpc-mac-v0.1.0-preview.2"
        record_path.write_text(json.dumps(record))
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(p.PublishError, "staged macOS source differs"):
                p.sign_release(site, self.root)

    def test_stable_tag_and_false_ready_status_rejected(self):
        path = self.root / "agpc.mac.source.json"
        original = json.loads(path.read_text())
        for change in ({"tag": "agpc-mac-v0.1.0"}, {"status": "ready"},
                       {"source_commit": "main"}, {"assets": {"../evil": "0" * 64}}):
            path.write_text(json.dumps(dict(original, **change)))
            with self.assertRaises(p.PublishError):
                p.validate_mac_installer(self.root)
