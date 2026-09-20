import io
import json
from pathlib import Path
import os
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import publish_native as native


class NativePagesTests(unittest.TestCase):
    def test_standalone_preserves_arguments_exit_and_cleans_private_files(self):
        files = {name: b"" for name in native.LINUX_BACKEND}
        files["browser/browser.cjs"] = b"p-channel-payload"
        files["agpc_linux.py"] = b'import sys,json,pathlib; assert pathlib.Path(__file__).parent.joinpath("browser/browser.cjs").read_bytes() == b"p-channel-payload"; print(json.dumps(sys.argv)); raise SystemExit(23)\n'
        wrapper = native.standalone_linux(files)
        self.assertEqual(wrapper, native.standalone_linux(dict(reversed(list(files.items())))))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "agpc.sh")
            path.write_bytes(wrapper)
            environment = {**os.environ, "TMPDIR": directory}
            args = ["info", "a b", "$(not-a-command)", "--json"]
            for command, stdin in [(["bash", str(path), *args], None), (["bash", "-s", "--", *args], wrapper.decode())]:
                result = subprocess.run(command, input=stdin, capture_output=True, text=True, env=environment)
                self.assertEqual(result.returncode, 23, result.stderr)
                self.assertEqual(json.loads(result.stdout)[1:], args)
                self.assertEqual(list(Path(directory).glob("agpc-native-*")), [])

    def test_apps_entrypoint_dispatches_to_apps_module(self):
        files = {name: b"raise SystemExit(99)\n" for name in native.LINUX_BACKEND}
        files["native_apps.py"] = b'import sys; print(sys.argv[0]); raise SystemExit(0)\n'
        wrapper = native.standalone_linux(files, "agpc-apps.sh")
        result = subprocess.run(["bash"], input=wrapper, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"native_apps.py", result.stdout)
        with self.assertRaises(ValueError):
            native.standalone_linux(files, "unexpected.sh")

    def test_standalone_detects_embedded_corruption(self):
        files = {name: b"pass\n" for name in native.LINUX_BACKEND}
        wrapper = native.standalone_linux(files)
        start = wrapper.index(b"payload = base64.b64decode('") + len(b"payload = base64.b64decode('")
        wrapper = wrapper[:start] + b"A" + wrapper[start + 1:]
        result = subprocess.run(["bash"], input=wrapper, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"checksum mismatch", result.stderr)

    def test_windows_cpu_hash_and_extra_file_checks(self):
        executable = bytearray(256)
        executable[:2] = b"MZ"
        struct.pack_into("<I", executable, 60, 64)
        executable[64:68] = b"PE\0\0"
        struct.pack_into("<H", executable, 68, 0x8664)
        def fixture(extra=False):
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w") as archive:
                archive.writestr("agpc.exe", executable)
                archive.writestr("README.txt", b"usage")
                if extra: archive.writestr("private.env", b"unexpected")
            return output.getvalue()
        expected = native.digest(executable)
        self.assertEqual(native.windows_executable(fixture(), expected, 0x8664), executable)
        for blob, sha, cpu in [(fixture(), "0" * 64, 0x8664), (fixture(), expected, 0xAA64), (fixture(True), expected, 0x8664)]:
            with self.assertRaises(ValueError): native.windows_executable(blob, sha, cpu)

    def test_pages_extraction_rejects_paths_links_and_duplicates(self):
        for names in [["../escape"], ["/absolute"], ["same", "same"], ["link"]]:
            with self.subTest(names=names), tempfile.TemporaryDirectory() as directory:
                tar_bytes = io.BytesIO()
                with tarfile.open(fileobj=tar_bytes, mode="w") as archive:
                    for name in names:
                        item = tarfile.TarInfo(name)
                        if name == "link":
                            item.type = tarfile.SYMTYPE
                            item.linkname = "/outside"
                        else:
                            item.size = 1
                        archive.addfile(item, io.BytesIO(b"x"))
                zip_path = Path(directory, "pages.zip")
                with zipfile.ZipFile(zip_path, "w") as archive:
                    archive.writestr("artifact.tar", tar_bytes.getvalue())
                with self.assertRaises(ValueError): native.extract_site(zip_path, Path(directory, "site"))

    def test_macos_archive_cpu_digest_links_and_inventory(self):
        executable = bytearray(64)
        struct.pack_into('<IIIIII', executable, 0, 0xfeedfacf, 0x100000c, 0, 2, 1, 32)
        def fixture(data=executable, extra=None, symlink=False, mode=0o755):
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode='w:gz') as archive:
                for name, content in [('agpc', data), ('README.txt', b'usage')] + ([] if extra is None else [(extra, b'x')]):
                    item = tarfile.TarInfo(name)
                    item.size = len(content)
                    item.mode = mode if name == 'agpc' else 0o644
                    if name == 'agpc' and symlink:
                        item.type = tarfile.SYMTYPE
                        item.linkname = '/outside'
                    archive.addfile(item, io.BytesIO(content))
            return output.getvalue()
        expected = native.digest(executable)
        self.assertEqual(native.macos_executable(fixture(), expected), executable)
        intel = bytearray(executable)
        struct.pack_into('<I', intel, 4, 0x1000007)
        for data, sha in [(fixture(), '0' * 64), (fixture(data=intel), native.digest(intel)),
                          (fixture(extra='../private.env'), expected), (fixture(extra='agpc'), expected),
                          (fixture(symlink=True), expected), (fixture(mode=0o644), expected)]:
            with self.assertRaises(ValueError): native.macos_executable(data, sha)

    def test_unrelated_site_changes_are_rejected(self):
        before = {"pool/main/package.deb": "original", "dists/stable/InRelease": "signed", "agpc.sh": "old"}
        native.verify_preservation(before, {**before, "agpc.sh": "native", "agpc.exe": "exe", "agpc": "mac"})
        for after in [{**before, "pool/main/package.deb": "changed"}, {"agpc.sh": "new"}, {**before, "unrelated": "added"}]:
            with self.assertRaises(ValueError): native.verify_preservation(before, after)

    def test_overlay_preserves_all_other_files_and_signs_new_entrypoints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            site.mkdir()
            (site / "agent-sphere-apps.sh").write_bytes(b"debian")
            (site / "dists").mkdir()
            (site / "dists/InRelease").write_bytes(b"signed index")
            (root / "scripts").mkdir()
            (root / "scripts/native-index.html").write_bytes(b"native page")
            before = native.snapshot(site)
            files = {name: b"native" for name in native.NATIVE_FILES}
            def sign(_, target):
                for name in native.NATIVE_FILES: (target / (name + ".asc")).write_bytes(b"signature")
            with patch.object(native, "assemble", return_value=({"debian_installer_sha256": native.digest(b"debian")}, {"version": "fixture"}, files)), patch.object(native, "sign_files", side_effect=sign):
                native.overlay(root, site, root / "evidence.json")
            native.verify_preservation(before, native.snapshot(site))
            self.assertEqual((site / "dists/InRelease").read_bytes(), b"signed index")
            self.assertEqual(json.loads((root / "evidence.json").read_text())["preserved_files"], 2)

    def test_every_apt_publication_applies_native_files_last(self):
        workflow = (Path(__file__).parents[1] / ".github/workflows/publish-apt.yml").read_text()
        self.assertLess(workflow.index("scripts/validate_agent_sphere_apt.py . apt-site"), workflow.index("scripts/publish_native.py overlay"))
        self.assertLess(workflow.index("scripts/publish_native.py overlay"), workflow.index("actions/upload-pages-artifact"))


if __name__ == "__main__":
    unittest.main()
