import importlib.util
from pathlib import Path
import tempfile
import sys
import unittest
import subprocess
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

    def test_protected_snapshot_uses_privileged_stat_and_keeps_package_version(self):
        def run(args, **kwargs):
            if args[0] == "dpkg-query":
                return subprocess.CompletedProcess(args, 0, "install ok installed\t3.3.0-1", "")
            self.assertEqual(args[:3], ["sudo", "test", "-f"])
            return subprocess.CompletedProcess(args, 0)
        def command(args):
            if args[0] == "dpkg-query":
                return " /etc/private/service.env oldhash\n"
            self.assertEqual(args[:2], ["sudo", "sha256sum"])
            return "fixturehash  /etc/private/service.env"
        with patch.object(acceptance.subprocess, "run", side_effect=run), patch.object(acceptance, "command", side_effect=command):
            snapshot = acceptance.management_snapshot()
        self.assertEqual(snapshot["medge"]["version"], "3.3.0-1")
        self.assertEqual(snapshot["agpc-manager"]["configuration_sha256"], {"/etc/private/service.env": "fixturehash"})
