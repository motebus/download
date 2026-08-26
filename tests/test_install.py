from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).parents[1]
INSTALLER = ROOT / "install.sh"
COMPATIBILITY = ROOT / "scripts/validate-ubuntu-compatibility.sh"
WRAPPERS = {
    "ss-webos-install.sh": ("ss-webos", "ss-webos"),
    "mote-proxy-install.sh": ("mote-proxy", "sphere mote-proxy"),
    "motemcp-install.sh": ("motemcp", "sphere moted motemcp"),
}


class InstallContractTest(unittest.TestCase):
    def test_named_installers_select_exact_boundaries(self) -> None:
        dispatcher = INSTALLER.read_text(encoding="utf-8")
        for filename, (profile, packages) in WRAPPERS.items():
            wrapper = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn(f"MEDGE_INSTALL_PROFILE={profile}", wrapper)
            self.assertIn(f'APT_PACKAGES="{packages}"', dispatcher)

    def test_desktop_package_names_are_canonical(self) -> None:
        dispatcher = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('mdesk)      APT_PACKAGES="sphere moted mdesk"', dispatcher)
        self.assertIn('ss-webos)   APT_PACKAGES="ss-webos"', dispatcher)
        self.assertNotIn("ss-desk", dispatcher)
        self.assertNotIn('APT_PACKAGES="desk', dispatcher)
        self.assertFalse((ROOT / "webos-install.sh").exists())

    def test_mdesk_installer_is_self_contained_and_digest_pinned(self) -> None:
        text = (ROOT / "mdesk-install.sh").read_text(encoding="utf-8")
        self.assertIn("deb-v2026.08.26-3", text)
        self.assertIn("sphere_4.0.0-1_amd64.deb", text)
        self.assertIn("moted_3.2.0-6_amd64.deb", text)
        self.assertIn("mdesk_3.0.0-2_amd64.deb", text)
        self.assertEqual(text.count("sha256sum --check"), 1)
        self.assertNotIn("motebus.github.io", text)
        self.assertNotIn("ss-desk_", text)
        self.assertIn("dpkg --compare-versions", text)
        self.assertIn("Keeping %s=%s", text)
        self.assertIn('chmod 0755 "$PACKAGE_DIR"', text)
        self.assertIn('chmod 0644 "$PACKAGE_DIR/$asset"', text)

    def test_medge_installer_is_complete_self_contained_and_digest_pinned(self) -> None:
        text = (ROOT / "medge-install.sh").read_text(encoding="utf-8")
        self.assertIn("deb-v2026.08.26-3", text)
        for asset in (
            "sphere_4.0.0-1_amd64.deb",
            "moted_3.2.0-6_amd64.deb",
            "medge_1.0.0-3_all.deb",
            "mote-proxy_1.3.0-2_all.deb",
            "motemcp_1.0.0-3_all.deb",
            "medge-core_1.0.0-3_all.deb",
            "mdesk_3.0.0-2_amd64.deb",
            "ss-webos_2.0.0-8_amd64.deb",
            "cx-node_0.3.1-7_amd64.deb",
            "medge-all_1.0.0-3_all.deb",
        ):
            self.assertIn(asset, text)
        self.assertEqual(text.count("sha256sum --check"), 1)
        self.assertNotIn("motebus.github.io", text)
        self.assertNotIn("MEDGE_INSTALL_PROFILE", text)
        self.assertIn("dpkg --compare-versions", text)
        self.assertIn('apt-get install -y "$@"', text)
        self.assertIn('chmod 0755 "$PACKAGE_DIR"', text)
        self.assertIn('chmod 0644 "$PACKAGE_DIR/$asset"', text)

    def test_installers_never_remove_packages_or_topology(self) -> None:
        dispatcher = INSTALLER.read_text(encoding="utf-8")
        installers = [dispatcher]
        installers.extend(
            (ROOT / filename).read_text(encoding="utf-8")
            for filename in ("medge-install.sh", "mdesk-install.sh", *WRAPPERS)
        )
        for text in installers:
            for forbidden in ("apt-get remove", "apt-get purge", "dpkg --remove", "MCHAT_"):
                self.assertNotIn(forbidden, text)
        self.assertEqual(dispatcher.count("apt-get install -y $APT_PACKAGES"), 1)

    def test_dispatcher_fails_closed_without_a_named_profile(self) -> None:
        dispatcher = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('INSTALL_PROFILE="${MEDGE_INSTALL_PROFILE:-}"', dispatcher)
        self.assertIn("use a named component installer", dispatcher)

    def test_shell_contracts_parse(self) -> None:
        subprocess.run(["sh", "-n", str(INSTALLER)], check=True)
        subprocess.run(["sh", "-n", str(ROOT / "medge-install.sh")], check=True)
        subprocess.run(["sh", "-n", str(ROOT / "mdesk-install.sh")], check=True)
        for filename in WRAPPERS:
            subprocess.run(["sh", "-n", str(ROOT / filename)], check=True)
        subprocess.run(["bash", "-n", str(COMPATIBILITY)], check=True)

    def test_supported_ubuntu_targets_are_exact(self) -> None:
        dispatcher = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("ubuntu:24.04|ubuntu:26.04)", dispatcher)
        self.assertNotIn("ubuntu:22.04", dispatcher)
        compatibility = COMPATIBILITY.read_text(encoding="utf-8")
        self.assertIn("run_target 24.04", compatibility)
        self.assertIn("run_target 26.04", compatibility)


if __name__ == "__main__":
    unittest.main()
