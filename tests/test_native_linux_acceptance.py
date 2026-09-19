import importlib.util
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
SPEC = importlib.util.spec_from_file_location("native_linux_acceptance", Path(__file__).parents[1] / "scripts/verify_native_linux_install.py")
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)


class NativeLinuxAcceptanceTests(unittest.TestCase):
    def test_snapshot_detects_modified_target_and_preserves_dangling_link(self):
        with tempfile.TemporaryDirectory() as folder:
            target, link = Path(folder, "target"), Path(folder, "codex")
            self.assertEqual(acceptance.codex_state(link), {"kind": "absent"})
            link.symlink_to(target)
            self.assertEqual(acceptance.codex_state(link)["kind"], "symlink")
            target.write_bytes(b"original")
            before = acceptance.codex_state(link)
            target.write_bytes(b"modified")
            self.assertNotEqual(acceptance.codex_state(link), before)

    def test_installer_cannot_take_ownership_or_bundle_codex(self):
        with tempfile.TemporaryDirectory() as folder:
            before = {"kind": "absent"}
            receipt = {"runtime": folder}
            with patch.object(acceptance, "codex_state", return_value=before):
                acceptance.verify_codex_untouched(before, receipt)
                with self.assertRaises(RuntimeError):
                    acceptance.verify_codex_untouched(before, {**receipt, "codex": {}})
                Path(folder, "codex").mkdir()
                with self.assertRaises(RuntimeError):
                    acceptance.verify_codex_untouched(before, receipt)
            with patch.object(acceptance, "codex_state", return_value={"kind": "file"}):
                with self.assertRaises(RuntimeError):
                    acceptance.verify_codex_untouched(before, receipt)
