from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLERS = ("sphere.sh", "webdesk.sh", "sshkit.sh")
ENTRIES = (*INSTALLERS, "uninstall.sh")
BASE_URL = "https://motebus.github.io/download"


def python_block(text: str, marker: str) -> str:
    return text.split(marker, 1)[1].split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]


def planner(text: str) -> str:
    return python_block(text, 'python3 - "$MANIFEST_PATH" >"$TEMP_DIR/package-plan"')


def fixture_manifest(text: str) -> dict:
    code = planner(text)
    expected = next(
        ast.literal_eval(node.value) for node in ast.parse(code).body
        if isinstance(node, ast.Assign) and node.targets[0].id == "expected"
    )
    return {
        "schema": re.search(r'manifest.get\("schema"\) != "([^"]+)"', code)[1],
        "status": "approved", "suite": "stable", "component": "main", "architecture": "amd64",
        "packages": [
            {"name": name, "version": "1.2.3-1", "architecture": "all",
             "asset": f"{name}_1.2.3-1_all.deb", "sha256": "1" * 64}
            for name in expected
        ],
        "installers": [{"name": name, "sha256": "1" * 64} for name in ENTRIES],
    }


def run_python(code: str, *args: object) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-", *map(str, args)], input=code,
                          text=True, capture_output=True, check=False)


def build_deb(root: Path, name: str = "sphere", version: str = "1.2.3-1") -> Path:
    source = root / f"build-{name}"
    (source / "DEBIAN").mkdir(parents=True)
    (source / "DEBIAN/control").write_text(
        f"Package: {name}\nVersion: {version}\nArchitecture: all\n"
        "Maintainer: Installer Test <installer@example.invalid>\nDescription: offline fixture\n"
    )
    target = root / f"{name}_{version}_all.deb"
    subprocess.run(["dpkg-deb", "--build", "--root-owner-group", str(source), str(target)],
                   check=True, capture_output=True)
    return target


class ManifestSnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.home = cls.root / "gnupg"
        cls.home.mkdir(mode=0o700)
        cls.env = dict(os.environ, GNUPGHOME=str(cls.home))
        subprocess.run([
            "gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "",
            "--quick-generate-key", "Installer Test <installer@example.invalid>", "ed25519", "sign", "0",
        ], env=cls.env, check=True, capture_output=True)
        keys = subprocess.check_output(["gpg", "--batch", "--with-colons", "--list-keys"],
                                       env=cls.env, text=True, stderr=subprocess.DEVNULL)
        cls.fingerprint = next(line.split(":")[9] for line in keys.splitlines() if line.startswith("fpr:"))
        cls.key = cls.root / "archive.gpg"
        cls.key.write_bytes(subprocess.check_output(["gpg", "--batch", "--export"], env=cls.env))

    @classmethod
    def tearDownClass(cls) -> None:
        subprocess.run(["gpgconf", "--kill", "gpg-agent"], env=cls.env, check=False, capture_output=True)
        cls.temp.cleanup()

    def harness(self, filename: str, variant: str) -> subprocess.CompletedProcess:
        text = (ROOT / filename).read_text()
        manifest = self.root / "input.json"
        signature = self.root / "input.json.asc"
        manifest.write_text(json.dumps(fixture_manifest(text)))
        subprocess.run(["gpg", "--batch", "--yes", "--armor", "--detach-sign", "--output",
                        str(signature), str(manifest)], env=self.env, check=True, capture_output=True)
        if variant == "bad-signature":
            manifest.write_text(manifest.read_text().replace('"approved"', '"tampered"'))
        start = text.index("# A local override")
        marker = 'mapfile -t APPROVED_PACKAGES' if filename == "uninstall.sh" else 'mapfile -t PACKAGE_RECORDS'
        end = text.index(marker)
        prefix = r'''
set -euo pipefail
fail() { printf '%s\n' "$*" >&2; exit 1; }
PROFILE_NAME=sphere
BASE_URL=https://motebus.github.io/download
curl() {
    local dest="${@: -2:1}" url="${@: -1}"
    case "$url" in
        */medge-archive-keyring.gpg) cp "$TEST_KEY" "$dest" ;;
        */medge.sources) printf 'fixture source\n' >"$dest" ;;
        */release-manifest.json.asc) cp "$TEST_SIGNATURE" "$dest" ;;
        */release-manifest.json) cp "$TEST_MANIFEST" "$dest" ;;
        *) return 1 ;;
    esac
}
gpgv() {
    [[ "${@: -1}" != "$TEST_MANIFEST" && "${@: -2:1}" != "$TEST_SIGNATURE" ]] || return 90
    [[ "$(stat -c '%a' "${@: -1}")" == 400 ]] || return 91
    [[ "$(stat -c '%a' "$(dirname "${@: -1}")")" == 700 ]] || return 92
    command gpgv "$@" || return
    if [[ "$TEST_VARIANT" == mutate-original ]]; then
        printf 'not JSON\n' >"$TEST_MANIFEST"
    fi
}
'''
        env = dict(self.env, EXPECTED_FINGERPRINT=self.fingerprint, TEST_KEY=str(self.key),
                   TEST_MANIFEST=str(manifest), TEST_SIGNATURE=str(signature), TEST_VARIANT=variant)
        env.pop("MEDGE_RELEASE_MANIFEST", None)
        env.pop("MEDGE_RELEASE_MANIFEST_SIGNATURE", None)
        if variant != "download":
            if variant != "signature-only":
                env["MEDGE_RELEASE_MANIFEST"] = str(manifest)
            if variant != "manifest-only":
                env["MEDGE_RELEASE_MANIFEST_SIGNATURE"] = str(signature)
        return subprocess.run(["bash"], input=prefix + text[start:end] + '\nprintf "verified-plan\\n"\n',
                              env=env, text=True, capture_output=True)

    def test_signed_private_snapshot_survives_original_file_replacement(self) -> None:
        for filename in ENTRIES:
            with self.subTest(filename=filename):
                result = self.harness(filename, "mutate-original")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("verified-plan", result.stdout)

    def test_bad_signature_stops_before_manifest_planning(self) -> None:
        for filename in ENTRIES:
            with self.subTest(filename=filename):
                result = self.harness(filename, "bad-signature")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("signature verification failed", result.stderr)
                self.assertNotIn("verified-plan", result.stdout)

    def test_partial_overrides_fail_in_every_entry_point(self) -> None:
        for filename in ENTRIES:
            for variant in ("manifest-only", "signature-only"):
                with self.subTest(filename=filename, variant=variant):
                    result = self.harness(filename, variant)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("set both", result.stderr)

    def test_no_override_fetches_and_verifies_both_release_files(self) -> None:
        for filename in ENTRIES:
            with self.subTest(filename=filename):
                result = self.harness(filename, "download")
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_package_planner_requires_sha256_for_selected_and_unselected_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"
            for filename in INSTALLERS:
                text = (ROOT / filename).read_text()
                manifest = fixture_manifest(text)
                path.write_text(json.dumps(manifest))
                result = run_python(planner(text), path)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(all(len(line.split("\t")) == 4 for line in result.stdout.splitlines()))
                for row in (0, -1):
                    for bad_digest in (None, "", "f" * 63, "G" * 64):
                        with self.subTest(filename=filename, row=row, digest=bad_digest):
                            broken = fixture_manifest(text)
                            broken["packages"][row]["sha256"] = bad_digest
                            path.write_text(json.dumps(broken))
                            result = run_python(planner(text), path)
                            self.assertNotEqual(result.returncode, 0)
                            self.assertIn("invalid release SHA-256", result.stderr)


class AptArtifactTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archives = self.root / "archives"
        self.archives.mkdir()
        self.manifest_path = self.root / "manifest.json"
        self.selection = self.root / "selection"
        self.plan = self.root / "plan"
        self.code = python_block((ROOT / "sphere.sh").read_text(), 'verify_apt_artifacts() {')
        built = build_deb(self.root)
        self.asset = self.archives / built.name
        shutil.copyfile(built, self.asset)
        self.asset.chmod(0o644)
        self.item = {"name": "sphere", "version": "1.2.3-1", "architecture": "all",
                     "asset": self.asset.name, "sha256": hashlib.sha256(self.asset.read_bytes()).hexdigest()}
        self.manifest = {"packages": [self.item]}
        self.selection.write_text("sphere\t1.2.3-1\t" + self.asset.name + "\t" + self.item["sha256"] + "\n")
        self.uri = f"{BASE_URL}/pool/main/s/sphere/{self.asset.name}"
        self.write_plan()

    def write_plan(self, uri: str | None = None, filename: str | None = None) -> None:
        self.plan.write_text(f"Reading package lists...\n'{uri or self.uri}' {filename or self.asset.name} "
                             f"{self.asset.stat().st_size} MD5Sum:unused\n")

    def verify(self, mode: str = "staged") -> subprocess.CompletedProcess:
        self.manifest_path.write_text(json.dumps(self.manifest))
        return run_python(self.code, mode, self.manifest_path, self.selection,
                          self.plan, self.archives, BASE_URL)

    def test_valid_release_artifact_passes_plan_and_staging(self) -> None:
        for mode in ("plan", "staged"):
            result = self.verify(mode)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_every_installer_uses_the_same_artifact_verifier(self) -> None:
        for filename in INSTALLERS:
            self.assertEqual(self.code, python_block((ROOT / filename).read_text(), 'verify_apt_artifacts() {'))

    def test_same_version_from_other_origin_or_path_is_rejected(self) -> None:
        for uri in (
            self.uri.replace("motebus.github.io", "mirror.example.invalid"),
            self.uri.replace("/download/", "/download-attacker/"),
            self.uri.replace("https:", "http:"),
            self.uri.replace("1.2.3-1", "1x2x3-1"),
            self.uri.replace("https://", "https://user@"),
            self.uri + "?alternate=1", self.uri + "#alternate",
        ):
            with self.subTest(uri=uri):
                self.write_plan(uri)
                self.assertNotEqual(self.verify("plan").returncode, 0)

    def test_missing_reacquisition_is_rejected_even_for_installed_version(self) -> None:
        self.plan.write_text("sphere is already the newest version.\n")
        result = self.verify("plan")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reacquire every selected package", result.stderr)

    def test_unsafe_duplicate_and_malformed_acquisition_records_are_rejected(self) -> None:
        good = self.plan.read_text()
        for bad in (good + good, "'https://example.invalid/file'\n",
                    good.replace(self.asset.name + " ", "../" + self.asset.name + " "),
                    good.replace(self.asset.name + " ", "%2f" + self.asset.name + " ")):
            with self.subTest(plan=bad):
                self.plan.write_text(bad)
                self.assertNotEqual(self.verify("plan").returncode, 0)

    def test_same_size_cached_package_tampering_fails_sha256(self) -> None:
        content = bytearray(self.asset.read_bytes())
        content[-1] ^= 1
        self.asset.write_bytes(content)
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256 differs", result.stderr)

    def test_debian_metadata_is_checked_after_matching_digest(self) -> None:
        other = build_deb(self.root, name="other-package")
        shutil.copyfile(other, self.asset)
        self.item["sha256"] = hashlib.sha256(self.asset.read_bytes()).hexdigest()
        self.write_plan()
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Debian metadata differs", result.stderr)

    def test_staging_rejects_extra_missing_linked_or_writable_archives(self) -> None:
        data = self.asset.read_bytes()
        for variant in ("extra", "missing", "symlink", "hardlink", "writable"):
            with self.subTest(variant=variant):
                extra = self.archives / "extra.deb"
                outside = self.root / "linked.deb"
                if variant == "extra":
                    extra.write_bytes(data)
                elif variant == "missing":
                    self.asset.unlink()
                elif variant in {"symlink", "hardlink"}:
                    self.asset.unlink()
                    outside.write_bytes(data)
                    if variant == "symlink":
                        self.asset.symlink_to(outside)
                    else:
                        os.link(outside, self.asset)
                else:
                    self.asset.chmod(0o666)
                self.assertNotEqual(self.verify().returncode, 0)
                extra.unlink(missing_ok=True)
                self.asset.unlink(missing_ok=True)
                outside.unlink(missing_ok=True)
                self.asset.write_bytes(data)
                self.asset.chmod(0o644)

    def test_catalog_dependency_outside_profile_is_still_bound_to_manifest(self) -> None:
        dependency = dict(self.item, name="moted", asset="moted_1.2.3-1_all.deb")
        self.manifest["packages"].append(dependency)
        with self.plan.open("a") as output:
            output.write("'https://mirror.example.invalid/moted_1.2.3-1_all.deb' moted_1.2.3-1_all.deb 1 MD5Sum:x\n")
        result = self.verify("plan")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("moted: APT origin or asset differs", result.stderr)

    def test_percent_encoded_debian_epoch_is_supported(self) -> None:
        built = build_deb(self.root, name="epoch-package", version="2:1.2.3-1")
        self.asset.unlink()
        filename = built.name.replace(":", "%3a")
        self.asset = self.archives / filename
        shutil.copyfile(built, self.asset)
        self.asset.chmod(0o644)
        self.item.update(name="epoch-package", version="2:1.2.3-1", asset=built.name,
                         sha256=hashlib.sha256(built.read_bytes()).hexdigest())
        self.selection.write_text("epoch-package\t2:1.2.3-1\n")
        self.write_plan(f"{BASE_URL}/pool/main/e/epoch-package/{filename}")
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_apt_stages_never_mutate_before_artifact_verification(self) -> None:
        text = (ROOT / "sphere.sh").read_text()
        start = text.index("# Keep this invocation's indexes")
        end = text.index('for record in "${PACKAGE_RECORDS[@]}"; do', text.index('--no-download -y install'))
        body = text[start:end]
        for variant in ("good", "tampered", "wrong-origin", "removal"):
            with self.subTest(variant=variant):
                run_root = self.root / variant
                run_root.mkdir()
                log = run_root / "calls"
                self.manifest_path.write_text(json.dumps(self.manifest))
                self.write_plan(self.uri.replace("motebus.github.io", "mirror.example.invalid")
                                if variant == "wrong-origin" else self.uri)
                script = r'''
set -euo pipefail
fail() { printf '%s\n' "$*" >&2; exit 1; }
ORIGINAL_UMASK="$(umask)"
umask 077
mapfile -t PACKAGE_RECORDS <"$TEST_SELECTION"
cp "$TEST_SELECTION" "$TEMP_DIR/package-plan"
apt-get() {
    printf '%s\n' "$*" >>"$TEST_LOG"
    [[ " $* " == *' update '* ]] && return 0
    [[ " $* " == *' --no-remove '* && " $* " == *' --reinstall '* ]] || return 91
    [[ "$TEST_VARIANT" != removal ]] || return 92
    case " $* " in
        *' --print-uris '*) cat "$TEST_PLAN" ;;
        *' --download-only '*)
            cp "$TEST_ASSET" "$TEMP_DIR/apt/archives/$(basename "$TEST_ASSET")"
            if [[ "$TEST_VARIANT" == tampered ]]; then
                printf x | dd of="$TEMP_DIR/apt/archives/$(basename "$TEST_ASSET")" bs=1 seek=0 conv=notrunc status=none
            fi ;;
        *' --no-download '*)
            [[ "$(umask)" == "$ORIGINAL_UMASK" ]] || return 94
            printf 'MUTATED\n' >>"$TEST_LOG" ;;
        *) return 93 ;;
    esac
}
'''
                env = dict(os.environ, TEMP_DIR=str(run_root), BASE_URL=BASE_URL,
                           MANIFEST_PATH=str(self.manifest_path), TEST_SELECTION=str(self.selection),
                           TEST_LOG=str(log), TEST_PLAN=str(self.plan), TEST_ASSET=str(self.asset), TEST_VARIANT=variant)
                result = subprocess.run(["bash"], input=script + body, env=env, text=True, capture_output=True)
                calls = log.read_text()
                if variant == "good":
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(calls.count("MUTATED"), 1)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn("MUTATED", calls)

    def test_real_apt_solver_refuses_conflicting_package_removal(self) -> None:
        # Use an isolated dpkg status file and only simulation: no root or network.
        source = self.root / "conflict"
        (source / "DEBIAN").mkdir(parents=True)
        (source / "DEBIAN/control").write_text(
            "Package: conflict-fixture\nVersion: 1.0-1\nArchitecture: all\n"
            "Conflicts: unrelated-package\nMaintainer: Test <test@example.invalid>\n"
            "Description: removal guard fixture\n"
        )
        deb = self.root / "conflict-fixture_1.0-1_all.deb"
        subprocess.run(["dpkg-deb", "--build", "--root-owner-group", str(source), str(deb)],
                       check=True, capture_output=True)
        status = self.root / "status"
        original = (
            "Package: unrelated-package\nStatus: install ok installed\n"
            "Priority: optional\nSection: misc\nInstalled-Size: 1\n"
            "Maintainer: Test <test@example.invalid>\nArchitecture: all\n"
            "Version: 1.0-1\nDescription: fixture\n\n"
        )
        status.write_text(original)
        sources = self.root / "empty.list"
        sources.touch()
        parts = self.root / "sourceparts"
        parts.mkdir()
        lists = self.root / "lists"
        lists.mkdir()
        common = [
            "apt-get", "--simulate", "-o", f"Dir::State::status={status}",
            "-o", f"Dir::State::lists={lists}", "-o", f"Dir::Etc::sourcelist={sources}",
            "-o", f"Dir::Etc::sourceparts={parts}", "-o", "Dir::Cache::pkgcache=",
            "-o", "Dir::Cache::srcpkgcache=",
        ]
        unguarded = subprocess.run([*common, "install", str(deb)], text=True, capture_output=True)
        self.assertEqual(unguarded.returncode, 0, unguarded.stderr)
        self.assertIn("Remv unrelated-package", unguarded.stdout)
        guarded = subprocess.run([*common, "--no-remove", "install", str(deb)],
                                 text=True, capture_output=True, env=dict(os.environ, LC_ALL="C"))
        self.assertNotEqual(guarded.returncode, 0)
        self.assertIn("remove is disabled", guarded.stderr)
        self.assertEqual(status.read_text(), original)

    def test_retired_install_entry_is_not_restored(self) -> None:
        self.assertFalse((ROOT / "install.sh").exists())


if __name__ == "__main__":
    unittest.main()
