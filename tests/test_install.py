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
        self.assertIn("/usr/libexec/ss-webos/install-desktop-shortcut", text)

    def test_shell_contracts_parse(self) -> None:
        subprocess.run(["sh", "-n", str(INSTALLER)], check=True)
        subprocess.run(["bash", "-n", str(COMPATIBILITY)], check=True)

    def test_device_helper_is_started_after_and_stopped_before_desk(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        system_units = next(
            match for match in re.finditer(r'SYSTEM_UNITS="(.*?)"', text, re.S)
            if "deskd.service" in match.group(1)
        )
        stop_units = next(
            match for match in re.finditer(r'STOP_SYSTEM_UNITS="(.*?)"', text, re.S)
            if "deskd.service" in match.group(1)
        )
        self.assertLess(
            system_units.group(1).index("deskd.service"),
            system_units.group(1).index("deskd-device.service"),
        )
        self.assertLess(
            stop_units.group(1).index("deskd-device.service"),
            stop_units.group(1).index("deskd.service"),
        )

    def test_stale_meta_recovery_is_unconditional_and_precedes_prerequisites(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        first_update = text.index("apt-get update")
        status_check = text.index("dpkg-query -W", first_update)
        meta_removal = text.index("dpkg --remove medge", status_check)
        dependency_check = text.index("apt-get check", meta_removal)
        prerequisite_install = text.index(
            "apt-get install -y --no-install-recommends ca-certificates curl gnupg"
        )
        self.assertNotIn("&& ! apt-get check", text)
        self.assertLess(first_update, status_check)
        self.assertLess(meta_removal, prerequisite_install)
        self.assertLess(dependency_check, prerequisite_install)
        self.assertIn("/var/lib/dpkg/info/medge.$maintainer_script", text)
        self.assertIn("installed components are preserved", text)

    def test_server_profile_installs_physical_packages_without_meta(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        server_case = text.split("medge)", 1)[1].split(";;", 1)[0]
        self.assertIn('APT_PACKAGES="sphered moted aport qbix mbox motessh"', server_case)
        self.assertNotIn('APT_PACKAGES="medge"', server_case)

    def test_repository_refresh_bypasses_stale_intermediary_cache(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        source_install = text.index(
            'install -m 0644 "$TEMP_DIR/medge.sources" "$SOURCES_PATH"'
        )
        forced_update = text.index(
            "apt-get -o Acquire::http::No-Cache=true update"
        )
        transaction_plan = text.index('APT_INSTALL_PLAN="$(apt-get --print-uris')
        self.assertLess(source_install, forced_update)
        self.assertLess(forced_update, transaction_plan)

    def test_server_profile_removes_only_explicit_retired_packages(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        server_case = text.split("medge)", 1)[1].split(";;", 1)[0]
        self.assertIn(
            'RETIRED_PACKAGES="agos mote mgate ucli qbix-func qbix-wasm moteos"',
            server_case,
        )
        self.assertIn("apt-get remove -y --no-auto-remove $INSTALLED_RETIRED", text)
        self.assertGreaterEqual(text.count("''|config-files|not-installed) ;;"), 2)
        self.assertNotIn("apt-get autoremove", text)
        self.assertNotIn("apt-get purge", text)

    def test_server_profile_stops_loaded_retired_mgate_daemon(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        server_case = text.split("medge)", 1)[1].split(";;", 1)[0]
        self.assertIn("mgated.service", server_case)
        self.assertLess(
            server_case.index("mbox.service"),
            server_case.index("mgated.service"),
        )

    def test_compatibility_images_are_digest_pinned(self) -> None:
        text = COMPATIBILITY.read_text(encoding="utf-8")
        images = re.findall(r"docker\.io/library/ubuntu@sha256:[0-9a-f]{64}", text)
        self.assertEqual(len(images), 2)
        self.assertEqual(len(set(images)), 2)
        self.assertIn("run_target 24.04", text)
        self.assertIn("run_target 26.04", text)


if __name__ == "__main__":
    unittest.main()
