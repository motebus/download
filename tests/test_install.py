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
    "mote-secd",
    "mote-bridge-mcp",
    "ultra-mcp-ssh",
    "mcp-run",
    "cx-node",
    "mote-sync",
    "mote-syncd",
    "schatd",
    "schat",
    "codex-mesh",
)
INSTALLERS = {
    "sphere.sh": tuple(name for name in EXPECTED_ALL if name != "ultra-mcp-ssh"),
    "webdesk.sh": (
        "sphere",
        "mlink",
        "mdesk",
        "ss-webos",
    ),
    "sshkit.sh": (
        "sphere",
        "moted",
        "mote-proxy",
        "mote-secd",
        "mote-bridge-mcp",
        "ultra-mcp-ssh",
        "mcp-run",
        "mote-sync",
        "mote-syncd",
        "schatd",
        "schat",
    ),
}
RELEASE_SCRIPTS = (*INSTALLERS, "uninstall.sh")


class InstallContractTest(unittest.TestCase):
    def test_public_root_has_exact_four_release_scripts(self) -> None:
        actual = {
            path.name for path in ROOT.iterdir()
            if path.is_file()
            and path.name.endswith(".sh")
            and path.name != "github-setup.sh"
        }
        self.assertEqual(actual, set(RELEASE_SCRIPTS))
        for filename in RELEASE_SCRIPTS:
            installer = ROOT / filename
            self.assertTrue(installer.stat().st_mode & 0o111)

    def test_installers_have_exact_v16_trust_and_profile_contract(self) -> None:
        for filename, selected in INSTALLERS.items():
            text = (ROOT / filename).read_text(encoding="utf-8")
            self.assertTrue(text.startswith("#!/usr/bin/env bash\nset -euo pipefail\n"))
            for package_name in EXPECTED_ALL:
                self.assertIn(f'    "{package_name}",', text)
            for required in (
                "medge-public-release/v16",
                "AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0",
                "release-manifest.json.asc",
                "gpgv --keyring",
                'apt-get --allow-downgrades --print-uris -y install "${PACKAGE_ARGS[@]}"',
                'apt-get install -y --allow-downgrades "${PACKAGE_ARGS[@]}"',
                "Ubuntu 24.04 or 26.04 is required",
            ):
                self.assertIn(required, text)
            self.assertIn('manifest_path="$TEMP_DIR/release-manifest.json"', text)
            self.assertNotIn('elif [[ -n "$SCRIPT_SOURCE" ]]', text)
            if filename == "sphere.sh":
                self.assertIn(
                    'selected = tuple(name for name in expected if name != "ultra-mcp-ssh")',
                    text,
                )
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
                "medge-home.mote",
                "Supporting Center",
            ):
                self.assertNotIn(forbidden, text)

    def test_downgrades_remain_bounded_to_exact_manifest_pins(self) -> None:
        for filename in INSTALLERS:
            text = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn('PACKAGE_ARGS+=("$package_name=$package_version")', text)
            self.assertEqual(text.count("--allow-downgrades"), 2)
            self.assertNotIn("--allow-remove-essential", text)
            self.assertNotIn("--allow-change-held-packages", text)

    def test_sshkit_verifies_automatic_system_ssh_setup(self) -> None:
        required = (
            "verify_mote_proxy_ssh_setup",
            "/etc/ssh/ssh_config.d/50-mote-proxy.conf",
            "/usr/libexec/mote-proxy/ssh-proxy",
            "/usr/bin/ssh -G -F /etc/ssh/ssh_config",
            "sphere-installer-proxy-check.mote",
            "root:root:644",
            "root:root:755",
            "automatic *.mote SSH proxy setup is active",
            "verify_sphere_post_install",
            "/usr/sbin/sphere post-install",
            "Sphere essential post-install health checks failed",
        )
        text = (ROOT / "sshkit.sh").read_text(encoding="utf-8")
        for contract in required:
            self.assertIn(contract, text)
        for forbidden in (
            "~/.ssh/config",
            "cat >/etc/ssh/ssh_config",
            "tee /etc/ssh/ssh_config",
            "install /etc/ssh/ssh_config",
        ):
            self.assertNotIn(forbidden, text)

    def test_sphere_is_install_only(self) -> None:
        text = (ROOT / "sphere.sh").read_text(encoding="utf-8")
        for excluded in (
            "verify_mote_proxy_ssh_setup",
            "verify_sphere_post_install",
            "/usr/sbin/sphere post-install",
            "sphere-installer-proxy-check.mote",
        ):
            self.assertNotIn(excluded, text)

    def test_webdesk_does_not_verify_mote_proxy_setup(self) -> None:
        webdesk = (ROOT / "webdesk.sh").read_text(encoding="utf-8")
        for excluded in (
            "verify_mote_proxy_ssh_setup",
            "/etc/ssh/ssh_config.d/50-mote-proxy.conf",
            "sphere-installer-proxy-check.mote",
        ):
            self.assertNotIn(excluded, webdesk)

    def test_uninstaller_is_signed_bounded_and_preserves_non_sphere_state(self) -> None:
        text = (ROOT / "uninstall.sh").read_text(encoding="utf-8")
        for package_name in EXPECTED_ALL:
            self.assertIn(f'    "{package_name}",', text)
        for required in (
            "medge-public-release/v16",
            "AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0",
            "release-manifest.json.asc",
            "gpgv --keyring",
            "apt-get --simulate purge",
            'apt-get purge -y "${PURGE_ARGS[@]}"',
            "purge plan would remove packages outside Sphere",
            "/etc/ssh/ssh_config.d/50-mote-proxy.conf",
            "package-owned SSH proxy profile",
            "refusing removal",
            "remove_managed_ssh_proxy_profile",
            "this uninstaller accepts no arguments",
            "Sphere approved packages, SSH proxy profile, and installer-managed APT registration were removed",
            "User data, SSH identities, unrelated packages, and non-Sphere services were preserved",
        ):
            self.assertIn(required, text)
        self.assertIn('manifest_path="$TEMP_DIR/release-manifest.json"', text)
        self.assertNotIn('elif [[ -n "$SCRIPT_SOURCE" ]]', text)
        for forbidden in (
            "apt-get autoremove",
            "apt-get remove",
            "rm -rf",
            "/home/",
            "~/.ssh",
            "MCHAT_",
            "medge-home.mote",
            "Supporting Center",
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
        for filename in RELEASE_SCRIPTS:
            subprocess.run(["bash", "-n", str(ROOT / filename)], check=True)
        subprocess.run(["bash", "-n", str(COMPATIBILITY)], check=True)

    def test_dual_channel_bundle_verifier_parses(self) -> None:
        verifier = ROOT / "scripts/verify-dual-channel-bundle.js"
        self.assertTrue(verifier.is_file())
        subprocess.run(["node", "--check", str(verifier)], check=True)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("in-process", readme)
        self.assertIn("does not claim live MoteBus", readme)

    def test_supported_ubuntu_targets_are_exact(self) -> None:
        for filename in RELEASE_SCRIPTS:
            text = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn("ubuntu:24.04|ubuntu:26.04)", text)
            self.assertNotIn("ubuntu:22.04", text)
        compatibility = COMPATIBILITY.read_text(encoding="utf-8")
        self.assertIn("run_target 24.04", compatibility)
        self.assertIn("run_target 26.04", compatibility)
        self.assertIn("mote-bridge-mcp_*.deb", compatibility)
        self.assertIn("! dpkg-query -W motemcp", compatibility)
        self.assertIn("--allow-downgrades", compatibility)


if __name__ == "__main__":
    unittest.main()
