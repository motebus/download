from __future__ import annotations

from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).parents[1]
INSTALLER = ROOT / "install.sh"
COMPATIBILITY = ROOT / "scripts/validate-ubuntu-compatibility.sh"


class InstallContractTest(unittest.TestCase):
    def test_installer_accepts_exact_supported_ubuntu_versions(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        match = re.search(r'case "\$\{ID:-\}:\$\{VERSION_ID:-\}" in(.*?)esac', text, re.S)
        self.assertIsNotNone(match)
        assert match is not None
        case_body = match.group(1)
        self.assertIn("ubuntu:24.04|ubuntu:26.04)", case_body)
        self.assertNotIn("ubuntu:22.04", case_body)
        self.assertNotIn("ubuntu:25.10", case_body)
        self.assertIn("Ubuntu 24.04 or 26.04 is required", text)

    def test_shell_contracts_parse(self) -> None:
        subprocess.run(["sh", "-n", str(INSTALLER)], check=True)
        subprocess.run(["bash", "-n", str(COMPATIBILITY)], check=True)

    def test_compatibility_images_are_digest_pinned(self) -> None:
        text = COMPATIBILITY.read_text(encoding="utf-8")
        images = re.findall(r"docker\.io/library/ubuntu@sha256:[0-9a-f]{64}", text)
        self.assertEqual(len(images), 2)
        self.assertEqual(len(set(images)), 2)
        self.assertIn("run_target 24.04", text)
        self.assertIn("run_target 26.04", text)


if __name__ == "__main__":
    unittest.main()
