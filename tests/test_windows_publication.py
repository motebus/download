"""Windows scripts follow the existing archive signing/publication contract."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
import test_publish_apt as fixtures

p = fixtures.publish_apt
ROOT = Path(__file__).parents[1]

class WindowsPublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in p.AGENT_INSTALLER_FILES:
            shutil.copy2(ROOT / name, self.root)
        self.source = self.root / p.WINDOWS_INSTALLER_SOURCE

    def test_all_scripts_match_source_record(self):
        record = p.validate_windows_installer(self.root)
        self.assertEqual(record["tag"], "agpc-windows-v0.1.1")
        self.assertEqual(set(record["assets"]), {"agpc-win.ps1", "agpc.ps1", "agpc-win-uninstall.ps1", "agpc-unistall.ps1"})

    def test_missing_symlinked_or_tampered_assets_fail(self):
        for name in p.WINDOWS_INSTALLERS:
            path = self.root / name
            original = path.read_bytes()
            with self.subTest(name=name):
                path.write_bytes(original + b"\n# changed")
                with self.assertRaisesRegex(p.PublishError, "digest mismatch"):
                    p.validate_windows_installer(self.root)
                path.unlink()
                with self.assertRaisesRegex(p.PublishError, "missing regular"):
                    p.validate_windows_installer(self.root)
                path.symlink_to(ROOT / name)
                with self.assertRaisesRegex(p.PublishError, "missing regular"):
                    p.validate_windows_installer(self.root)
                path.unlink()
                path.write_bytes(original)

    def test_source_identity_and_asset_names_are_checked(self):
        record = json.loads(self.source.read_text())
        for change in ({"schema": "unknown"}, {"repository": "motebus/other"},
                       {"tag": "latest"}, {"source_commit": "main"},
                       {"assets": {"../agpc.ps1": "0" * 64}},
                       {"assets": dict.fromkeys(p.WINDOWS_INSTALLERS, "invalid")}):
            with self.subTest(change=change):
                altered = copy.deepcopy(record)
                altered.update(change)
                self.source.write_text(json.dumps(altered))
                with self.assertRaises(p.PublishError):
                    p.validate_windows_installer(self.root)

    def test_staged_metadata_drift_stops_before_key_access(self):
        site = self.root / "site"
        site.mkdir()
        for name in p.AGENT_INSTALLER_FILES:
            shutil.copy2(self.root / name, site)
        path = site / p.WINDOWS_INSTALLER_SOURCE
        record = json.loads(path.read_text())
        record["tag"] = "agpc-windows-v0.1.2"
        path.write_text(json.dumps(record))
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(p.PublishError, "staged Windows installer source differs"):
                p.sign_release(site, self.root)
