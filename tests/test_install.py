from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPHERE_INSTALLER = ROOT / "install-sphere.sh"
COMPONENT_DISPATCHER = ROOT / "install.sh"
COMPATIBILITY = ROOT / "scripts/validate-ubuntu-compatibility.sh"
COMPONENT_WRAPPERS = {
    "ss-webos-install.sh": ("ss-webos", "ss-webos"),
    "mote-proxy-install.sh": ("mote-proxy", "sphere mote-proxy"),
    "motemcp-install.sh": ("motemcp", "sphere moted motemcp"),
}


class InstallContractTest(unittest.TestCase):
    def test_install_sphere_is_the_only_aggregate_entry(self) -> None:
        self.assertTrue(SPHERE_INSTALLER.is_file())
        self.assertTrue(SPHERE_INSTALLER.stat().st_mode & 0o111)
        self.assertFalse((ROOT / "install-medge-all.sh").exists())
        self.assertFalse((ROOT / "medge-install.sh").exists())

    def test_install_sphere_has_exact_v9_trust_and_package_contract(self) -> None:
        text = SPHERE_INSTALLER.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/env bash\nset -euo pipefail\n"))
        for package_name in (
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
        ):
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

    def test_install_sphere_never_removes_packages_or_mutates_topology(self) -> None:
        text = SPHERE_INSTALLER.read_text(encoding="utf-8")
        for forbidden in (
            "apt-get remove",
            "apt-get purge",
            "dpkg --remove",
            "MCHAT_",
            "/etc/hosts",
            "systemctl enable",
        ):
            self.assertNotIn(forbidden, text)

    def test_install_sphere_accepts_stdin_without_bash_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            fake_id = Path(temp_name) / "id"
            fake_id.write_text("#!/bin/sh\necho 1000\n", encoding="utf-8")
            fake_id.chmod(0o755)
            environment = dict(os.environ)
            environment["PATH"] = f"{temp_name}:{environment['PATH']}"
            completed = subprocess.run(
                ["bash"],
                input=SPHERE_INSTALLER.read_text(encoding="utf-8"),
                text=True,
                capture_output=True,
                env=environment,
                check=False,
            )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("run this installer as root", completed.stderr)
        self.assertNotIn("BASH_SOURCE", completed.stderr)

    def test_install_sphere_pipeline_mode_uses_signed_pages_manifest(self) -> None:
        text = SPHERE_INSTALLER.read_text(encoding="utf-8")
        self.assertIn('${BASH_SOURCE[0]-}', text)
        self.assertIn('$BASE_URL/release-manifest.json', text)
        self.assertIn('$BASE_URL/release-manifest.json.asc', text)
        self.assertIn("approved Sphere release is not published", text)

    def test_component_installers_remain_separate_from_aggregate(self) -> None:
        dispatcher = COMPONENT_DISPATCHER.read_text(encoding="utf-8")
        for filename, (profile, packages) in COMPONENT_WRAPPERS.items():
            wrapper = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn(f"MEDGE_INSTALL_PROFILE={profile}", wrapper)
            self.assertIn(f'APT_PACKAGES="{packages}"', dispatcher)
            self.assertNotIn("install-sphere.sh", wrapper)
        self.assertNotIn("medge-all", dispatcher)

    def test_shell_contracts_parse(self) -> None:
        for filename in (
            "install-sphere.sh",
            "install.sh",
            "install-mote-transport.sh",
            "install-medge.sh",
            "mdesk-install.sh",
            *COMPONENT_WRAPPERS,
        ):
            subprocess.run(["bash", "-n", str(ROOT / filename)], check=True)
        subprocess.run(["bash", "-n", str(COMPATIBILITY)], check=True)

    def test_supported_ubuntu_targets_are_exact(self) -> None:
        text = SPHERE_INSTALLER.read_text(encoding="utf-8")
        self.assertIn("ubuntu:24.04|ubuntu:26.04)", text)
        self.assertNotIn("ubuntu:22.04", text)
        compatibility = COMPATIBILITY.read_text(encoding="utf-8")
        self.assertIn("run_target 24.04", compatibility)
        self.assertIn("run_target 26.04", compatibility)


if __name__ == "__main__":
    unittest.main()
