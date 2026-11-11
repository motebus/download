"""Validate the Apple Silicon installer command contract."""
from pathlib import Path
import subprocess
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "agpc-mac.sh"


class InstallerTests(unittest.TestCase):
    def test_default_and_explicit_plan(self):
        for args in ((), ("--plan",)):
            result = subprocess.run(["/bin/bash", str(SCRIPT), *args],
                                    capture_output=True, text=True, check=True)
            self.assertIn("0.1.0-preview.21", result.stdout)
            self.assertIn("~/.local/bin/agpc", result.stdout)

    def test_help_documents_explicit_install(self):
        result = subprocess.run(["/bin/bash", str(SCRIPT), "--help"],
                                capture_output=True, text=True, check=True)
        self.assertIn("--verify", result.stdout)
        self.assertIn("--install", result.stdout)

    def test_unknown_and_ambiguous_arguments_are_rejected(self):
        for args in (("--install-docker",), ("--install", "--plan")):
            result = subprocess.run(["/bin/bash", str(SCRIPT), *args], capture_output=True)
            self.assertEqual(result.returncode, 2)
