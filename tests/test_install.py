from __future__ import annotations

from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).parents[1]
INSTALLER = ROOT / "install.sh"
COMPATIBILITY = ROOT / "scripts/validate-ubuntu-compatibility.sh"
CX_INSTALLER = ROOT / "cx-install.sh"
MEDGE_ALL_INSTALLER = ROOT / "install-medge-all.sh"


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
        subprocess.run(["sh", "-n", str(CX_INSTALLER)], check=True)
        subprocess.run(["bash", "-n", str(COMPATIBILITY)], check=True)
        subprocess.run(["bash", "-n", str(MEDGE_ALL_INSTALLER)], check=True)

    def test_release_asset_medge_all_installer_has_exact_package_set(self) -> None:
        text = MEDGE_ALL_INSTALLER.read_text(encoding="utf-8")
        self.assertIn('release_tag="deb-v2026.08.24-5"', text)
        for package in (
            "sphere_4.0.0-1_amd64.deb",
            "moted_3.0.0-2_amd64.deb",
            "medge_1.0.0-3_all.deb",
            "mote-proxy_1.0.0-2_all.deb",
            "motemcp_1.0.0-2_all.deb",
            "medge-core_1.0.0-3_all.deb",
            "mdesk_2.1.0-9_amd64.deb",
            "ss-webos_2.0.0-8_amd64.deb",
            "cx-node_0.3.1-3_amd64.deb",
            "medge-all_1.0.0-3_all.deb",
        ):
            self.assertIn(package, text)
        self.assertNotIn("vdevice_", text)
        self.assertNotIn("mlink_", text)
        self.assertIn("sha256sum --ignore-missing --check SHA256SUMS", text)
        self.assertIn("ubuntu:24.04|ubuntu:26.04", text)
        self.assertNotIn("dpkg-query -W -f='${Status}\\n' chatgpt", text)
        self.assertNotIn("dpkg-query -W -f='${Status}\\n' codex", text)
        self.assertNotIn("must be installed because", text)
        self.assertIn("apt_with_lock_retry apt-get update", text)
        self.assertIn("Could not get lock", text)
        self.assertIn("Unable to (acquire|lock)", text)
        self.assertIn("APT remained locked after five minutes", text)
        self.assertIn("no lock file was removed", text)
        self.assertIn('apt-get install -y --no-install-recommends \\\n  "${package_paths[@]}"', text)

    def test_cx_installer_requires_explicit_admission_and_pinned_key(self) -> None:
        text = CX_INSTALLER.read_text(encoding="utf-8")
        self.assertIn("--node-id CX<number>", text)
        self.assertIn("--node-mote <name.mote>", text)
        self.assertIn("--hub-mma <mma>", text)
        self.assertIn("--bootstrap <absolute-file>", text)
        self.assertIn("AECAA1DCDAF19C7B7FEAF0C082A0E180EDAEA7A0", text)
        self.assertIn("Signed-By: /etc/apt/keyrings/medge-archive-keyring.gpg", text)
        self.assertIn('cmp -s "$BOOTSTRAP" "$target"', text)
        self.assertIn("CX_NODE_MOTE=%s", text)
        self.assertIn(
            "^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$",
            text,
        )
        self.assertIn("CX_REGISTRATION_ACCEPTANCE_FILE=/var/lib/cx-node/registration-acceptance.json", text)
        self.assertIn("/usr/bin/cx-node --doctor /etc/mote/cx-node/cx-node.env", text)
        self.assertIn("local runtime is active but Hub enrollment was not accepted", text)
        self.assertIn("local_runtime=healthy hub_enrollment=enrolled", text)
        self.assertLess(
            text.index("locked topology target must be a regular non-symlink file"),
            text.index("apt-get update"),
        )
        self.assertNotIn("ssh-keygen", text)
        self.assertNotIn("sshd_config", text)
        self.assertNotIn("authorized_keys", text)

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

    def test_interrupted_qbix_upgrade_is_recovered_before_any_apt_install(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        first_update = text.index("apt-get update")
        broken_qbix = text.index("unpacked:2.0.0-2", first_update)
        candidate = text.index("apt-cache policy qbix", broken_qbix)
        download = text.index('apt-get download "qbix=$QBIX_CANDIDATE_VERSION"', candidate)
        package_validation = text.index('dpkg-deb -f "$QBIX_RECOVERY_DEB" Package', download)
        recovery_install = text.index('dpkg --install "$QBIX_RECOVERY_DEB"', package_validation)
        prerequisite_install = text.index(
            "apt-get install -y --no-install-recommends ca-certificates curl gnupg"
        )
        self.assertLess(first_update, broken_qbix)
        self.assertLess(broken_qbix, candidate)
        self.assertLess(candidate, download)
        self.assertLess(download, package_validation)
        self.assertLess(package_validation, recovery_install)
        self.assertLess(recovery_install, prerequisite_install)
        self.assertIn("Recovering interrupted Qbix 2.0.0-2", text)

    def test_retired_pages_source_is_migrated_before_first_apt_update(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        migration = text.index('grep -Fqx "URIs: $RETIRED_BASE_URL"')
        rewrite = text.index('sed -i "s#^URIs: $RETIRED_BASE_URL')
        first_update = text.index("apt-get update")
        self.assertIn(
            'RETIRED_BASE_URL="https://motebus.github.io/medge-deb"',
            text,
        )
        self.assertLess(migration, rewrite)
        self.assertLess(rewrite, first_update)

    def test_server_profile_installs_physical_packages_without_meta(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        server_case = text.split("medge)", 1)[1].split(";;", 1)[0]
        self.assertIn(
            'APT_PACKAGES="sphered moted aport qbix mbox motestream motessh moterdp"',
            server_case,
        )
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

    def test_compatibility_uses_the_approved_manifest_package_set(self) -> None:
        text = COMPATIBILITY.read_text(encoding="utf-8")
        self.assertIn('release-manifest.json', text)
        self.assertIn('manifest.get("packages", [])', text)
        self.assertIn('EXPECTED_PACKAGE_NAMES=${EXPECTED_PACKAGES[*]}', text)
        self.assertIn('for package_name in $EXPECTED_PACKAGE_NAMES', text)


if __name__ == "__main__":
    unittest.main()
