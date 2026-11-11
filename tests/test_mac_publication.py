"""Reject tampering before macOS preview publication/signing."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
from test_native_pages import native
import publish_apt as p
ROOT = Path(__file__).parents[1]

class MacPublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in (*p.AGENT_INSTALLER_FILES, "medge-archive-keyring.gpg", "medge-archive-keyring.fingerprint"):
            shutil.copy2(ROOT / name, self.root)

    def test_record_matches_assets(self):
        self.assertEqual(p.validate_mac_installer(self.root)["status"], "arm64-controller-preview")

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
        record["source"]["job_id"] += 1
        record_path.write_text(json.dumps(record))
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(p.PublishError, "staged macOS source differs"):
                p.sign_release(site, self.root)

    def test_stable_tag_and_false_ready_status_rejected(self):
        path = self.root / "agpc.mac.source.json"
        original = json.loads(path.read_text())
        for change in ({"release": "https://github.com/motebus/download/releases/tag/agpc-native-v0.1.0"},
                       {"status": "ready"}, {"controller_sha256": "invalid"},
                       {"archive": {"name": "../evil", "sha256": "0" * 64}}):
            path.write_text(json.dumps(dict(original, **change)))
            with self.assertRaises(p.PublishError):
                p.validate_mac_installer(self.root)

    def test_installer_overlay_preserves_controller_and_unrelated_files(self):
        site = self.root / "site"
        site.mkdir()
        for name, data in (("agpc", b"controller"), ("agpc.asc", b"controller signature"),
                           ("index.html", b"index"), ("agpc-mac.sh", b"old bootstrap")):
            (site / name).write_bytes(data)
        record = p.validate_mac_installer(self.root)
        before = native.snapshot(site)
        with self.assertRaisesRegex(ValueError, "deployed Mac controller differs"):
            native.overlay_mac_installer(self.root, site, self.root / "evidence.json")
        self.assertEqual(native.snapshot(site), before)

        def sign(root, target, names):
            self.assertEqual(names, set(p.MAC_INSTALLER_FILES))
            for name in names:
                (target / (name + ".asc")).write_bytes(b"fixture signature")

        record["controller_sha256"] = native.digest(b"controller")
        manifest = {"tag": record["release"].rsplit("/", 1)[1], "prerelease": True,
                    "sources": {"macos": record["source"]},
                    "payload_sha256": {"macos": {"arm64": record["controller_sha256"]}},
                    "assets": {record["archive"]["name"]: {"sha256": record["archive"]["sha256"]}}}
        with mock.patch.object(p, "validate_mac_installer", return_value=record), \
                mock.patch.object(native, "fetch_release", return_value=json.dumps(manifest)), \
                mock.patch.object(native, "sign_files", side_effect=sign):
            native.overlay_mac_installer(self.root, site, self.root / "evidence.json")
        self.assertEqual((site / "agpc").read_bytes(), b"controller")
        self.assertEqual((site / "agpc.asc").read_bytes(), b"controller signature")
        self.assertEqual((site / "index.html").read_bytes(), b"index")
        self.assertEqual((site / "agpc-mac.sh").read_bytes(), (self.root / "agpc-mac.sh").read_bytes())
