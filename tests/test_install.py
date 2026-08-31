from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
COMPATIBILITY = ROOT / "scripts/validate-ubuntu-compatibility.sh"
EXPECTED_ALL = (
    "sphere",
    "moted",
    "medge",
    "mlink",
    "mdesk",
    "ss-webos",
    "mote-proxy",
    "motemcp",
    "cx-pivot",
    "mote-sync",
    "mote-syncd",
)
INSTALLERS = {
    "sphere.sh": EXPECTED_ALL,
    "sshpack.sh": (
        "sphere",
        "moted",
        "mote-proxy",
        "motemcp",
        "mote-sync",
        "mote-syncd",
    ),
    "webdesk.sh": (
        "sphere",
        "mlink",
        "mdesk",
        "ss-webos",
    ),
}


class InstallContractTest(unittest.TestCase):
    def test_public_root_has_exact_three_installers(self) -> None:
        actual = {
            path.name for path in ROOT.iterdir()
            if path.is_file()
            and path.name.endswith(".sh")
            and path.name != "github-setup.sh"
        }
        self.assertEqual(actual, set(INSTALLERS))
        for filename in INSTALLERS:
            installer = ROOT / filename
            self.assertTrue(installer.stat().st_mode & 0o111)

    def test_installers_have_exact_v9_trust_and_profile_contract(self) -> None:
        for filename, selected in INSTALLERS.items():
            text = (ROOT / filename).read_text(encoding="utf-8")
            self.assertTrue(text.startswith("#!/usr/bin/env bash\nset -euo pipefail\n"))
            for package_name in EXPECTED_ALL:
                self.assertIn(f'    "{package_name}",', text)
            for required in (
                "medge-public-release/v9",
                "AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0",
                "release-manifest.json.asc",
                "gpgv --keyring",
                'apt-get install -y "${PACKAGE_ARGS[@]}"',
                "Ubuntu 24.04 or 26.04 is required",
            ):
                self.assertIn(required, text)
            if filename == "sphere.sh":
                self.assertIn("selected = expected", text)
            else:
                match = re.search(
                    r"selected = \(\n(?P<body>.*?)\n\)\nversion_re",
                    text,
                    flags=re.DOTALL,
                )
                self.assertIsNotNone(match)
                names = tuple(re.findall(r'"([^"]+)"', match.group("body")))
                self.assertEqual(names, selected)

    def test_installers_never_remove_packages_or_mutate_runtime_state(self) -> None:
        for filename in INSTALLERS:
            text = (ROOT / filename).read_text(encoding="utf-8")
            for forbidden in (
                "apt-get remove",
                "apt-get purge",
                "dpkg --remove",
                "MCHAT_",
                "/etc/hosts",
                "systemctl enable",
                "systemctl restart",
            ):
                self.assertNotIn(forbidden, text)

    def test_installers_accept_stdin_without_bash_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            fake_id = Path(temp_name) / "id"
            fake_id.write_text("#!/bin/sh\necho 1000\n", encoding="utf-8")
            fake_id.chmod(0o755)
            environment = dict(os.environ)
            environment["PATH"] = f"{temp_name}:{environment['PATH']}"
            for filename in INSTALLERS:
                completed = subprocess.run(
                    ["bash"],
                    input=(ROOT / filename).read_text(encoding="utf-8"),
                    text=True,
                    capture_output=True,
                    env=environment,
                    check=False,
                )
                self.assertEqual(completed.returncode, 1)
                self.assertIn("run this installer as root", completed.stderr)
                self.assertNotIn("BASH_SOURCE", completed.stderr)

    def test_shell_contracts_parse(self) -> None:
        for filename in INSTALLERS:
            subprocess.run(["bash", "-n", str(ROOT / filename)], check=True)
        subprocess.run(["bash", "-n", str(COMPATIBILITY)], check=True)

    def test_supported_ubuntu_targets_are_exact(self) -> None:
        for filename in INSTALLERS:
            text = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn("ubuntu:24.04|ubuntu:26.04)", text)
            self.assertNotIn("ubuntu:22.04", text)
        compatibility = COMPATIBILITY.read_text(encoding="utf-8")
        self.assertIn("run_target 24.04", compatibility)
        self.assertIn("run_target 26.04", compatibility)


if __name__ == "__main__":
    unittest.main()
