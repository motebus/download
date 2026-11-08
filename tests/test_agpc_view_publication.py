"""View publication admission tests; no network, signing keys, or installation.

The DEB fixtures contain inert ELF headers. Mocked readelf output exercises the
publisher's validation boundaries, not native compilation or GUI acceptance.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("view_publication", ROOT / "scripts/publish_agpc_view.py")
pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)
import publish_native

SOURCE_SHA = "a" * 40
PUBLISHER_SHA = "b" * 40
ENVIRONMENT = {
    "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": pub.REPO,
    "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch",
    "GITHUB_WORKFLOW_REF": pub.REPO + "/.github/workflows/publish-agpc-view.yml@refs/heads/main",
    "GITHUB_SHA": PUBLISHER_SHA,
}


def record_for(package=b"original CI package", original=None):
    original = original or pub.encoded({"sha256": pub.sha(package)})
    assets = {pub.PACKAGE: package, "MANIFEST.json": b"manifest", "SHA256SUMS": b"sums"}
    return {
        "schema": "agpc-view.publication-inputs/v1", "tag": pub.TAG,
        "package": pub.PACKAGE, "version": pub.VERSION, "architecture": "amd64",
        "source_project": 1336, "source_commit": SOURCE_SHA, "source_ref": "main",
        "pipeline_id": 123, "job_id": 456, "gui_job_id": 457,
        "pipeline_status": "success", "producer_manifest_sha256": pub.sha(original),
        "candidate_tag": "candidate-" + pub.TAG,
        "assets": {name: {"sha256": pub.sha(data), "bytes": len(data)} for name, data in assets.items()},
        "notes": "Standalone native View package; runtime readiness is separate.",
    }


def producer_receipts(record):
    pipeline = {"id": record["pipeline_id"], "status": "success", "ref": "main", "sha": SOURCE_SHA}
    jobs = []
    for key, name in (("job_id", "agpc-view-native"), ("gui_job_id", "agpc-view-gui-native")):
        jobs.append({"id": record[key], "name": name, "status": "success", "ref": "main",
                     "commit": {"id": SOURCE_SHA}, "pipeline": copy.deepcopy(pipeline), "allow_failure": False})
    return pipeline, *jobs


class ProducerAdmission(unittest.TestCase):
    def test_exact_record_and_required_jobs_are_admitted(self):
        record = record_for()
        pub.validate_record(record)
        pub.check_jobs(record, *producer_receipts(record))

    def test_unreviewed_record_shapes_and_pins_are_rejected(self):
        cases = {
            "unknown field": lambda r: r.update(extra=True),
            "wrong schema": lambda r: r.update(schema="other/v1"),
            "wrong package": lambda r: r.update(package="other.deb"),
            "wrong architecture": lambda r: r.update(architecture="arm64"),
            "wrong project": lambda r: r.update(source_project=1337),
            "branch artifact": lambda r: r.update(source_ref="feature"),
            "failed pipeline": lambda r: r.update(pipeline_status="failed"),
            "short source ref": lambda r: r.update(source_commit="main"),
            "bad producer digest": lambda r: r.update(producer_manifest_sha256="0" * 63),
            "boolean job id": lambda r: r.update(job_id=True),
            "same native and GUI job": lambda r: r.update(gui_job_id=r["job_id"]),
            "different candidate tag": lambda r: r.update(candidate_tag="candidate-other"),
            "extra asset": lambda r: r["assets"].update({"run.sh": {"sha256": "0" * 64, "bytes": 1}}),
            "asset pin field": lambda r: r["assets"][pub.PACKAGE].update(url="https://example.invalid"),
            "zero size": lambda r: r["assets"][pub.PACKAGE].update(bytes=0),
            "boolean size": lambda r: r["assets"][pub.PACKAGE].update(bytes=True),
            "oversized asset": lambda r: r["assets"][pub.PACKAGE].update(bytes=pub.LIMIT + 1),
            "invalid asset hash": lambda r: r["assets"][pub.PACKAGE].update(sha256="g" * 64),
            "private publication reference": lambda r: r.update(notes="See gitlab private producer"),
        }
        for label, change in cases.items():
            with self.subTest(label=label):
                record = record_for()
                change(record)
                with self.assertRaises(ValueError):
                    pub.validate_record(record)

    def test_wrong_pipeline_and_gui_job_are_rejected(self):
        cases = [
            (0, "id", 999), (0, "status", "failed"), (0, "ref", "feature"), (0, "sha", "c" * 40),
            (1, "id", 999), (1, "name", "some-native-job"), (1, "status", "skipped"),
            (2, "id", 999), (2, "name", "agpc-view-native"), (2, "status", "failed"),
            (2, "ref", "feature"), (2, "allow_failure", True), (2, "allow_failure", None),
            (2, "commit", {"id": "c" * 40}),
            (2, "pipeline", {"id": 999, "sha": SOURCE_SHA, "ref": "main"}),
            (2, "pipeline", {"id": 123, "sha": "c" * 40, "ref": "main"}),
            (2, "pipeline", {"id": 123, "sha": SOURCE_SHA, "ref": "feature"}),
        ]
        for index, key, value in cases:
            with self.subTest(receipt=index, key=key, value=value):
                record = record_for()
                receipts = producer_receipts(record)
                receipts[index][key] = value
                with self.assertRaises(ValueError):
                    pub.check_jobs(record, *receipts)

    def fresh(self, change=None, publisher=PUBLISHER_SHA):
        package = b"original CI package"
        original = pub.encoded({"sha256": pub.sha(package)})
        record = record_for(package, original)
        pipeline, native, gui = producer_receipts(record)
        prefix = "/jobs/456/artifacts/components/agpc-view/dist/"
        responses = {
            "/repository/branches/main": pub.encoded({"commit": {"id": SOURCE_SHA}}),
            "/pipelines/123": pub.encoded(pipeline), "/jobs/456": pub.encoded(native),
            "/jobs/457": pub.encoded(gui), prefix + pub.PACKAGE: package,
            prefix + "manifest.json": original,
        }
        if change:
            change(record, responses, prefix)
        calls = []
        def get(path):
            calls.append(path)
            return responses[path]
        with patch.dict(os.environ, ENVIRONMENT, clear=True), patch.object(pub, "api_reader") as api, \
                patch.object(pub, "run", return_value=json.dumps({"commit": {"sha": publisher}})) as run:
            result = pub.fresh_main(record, get=get)
            api.assert_not_called()
            run.assert_called_once_with("gh", "api", "repos/" + pub.REPO + "/branches/main")
        self.assertEqual(result, original)
        self.assertEqual(set(calls), set(responses))

    def test_fresh_main_reads_exact_original_artifacts(self):
        self.fresh()

    def test_original_ci_tamper_is_rejected_even_with_other_candidate_pin(self):
        def package_changed(record, responses, prefix):
            responses[prefix + pub.PACKAGE] = b"modified CI package"
        def manifest_changed(record, responses, prefix):
            responses[prefix + "manifest.json"] = pub.encoded({"sha256": "0" * 64})
        def candidate_changed(record, responses, prefix):
            record["assets"][pub.PACKAGE] = {"sha256": pub.sha(b"different candidate"), "bytes": 19}
        def inconsistent_original(record, responses, prefix):
            data = pub.encoded({"sha256": "0" * 64})
            responses[prefix + "manifest.json"] = data
            record["producer_manifest_sha256"] = pub.sha(data)
        for change in (package_changed, manifest_changed, candidate_changed, inconsistent_original):
            with self.subTest(change=change.__name__), self.assertRaises(ValueError):
                self.fresh(change)

    def test_source_or_publisher_main_advancing_is_rejected(self):
        def advanced(record, responses, prefix):
            responses["/repository/branches/main"] = pub.encoded({"commit": {"id": "c" * 40}})
        with self.assertRaisesRegex(ValueError, "source main advanced"):
            self.fresh(advanced)
        with self.assertRaisesRegex(ValueError, "publisher main advanced"):
            self.fresh(publisher="c" * 40)


@unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb is required for inert archive fixtures")
class BuildAndBundleAdmission(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.record = record_for()

    def fixture(self, proof_change=None, extra_control=None, extra_payload=None, binary_mode=0o755, binary_size=64):
        folder = Path(tempfile.mkdtemp(dir=self.root))
        stage = folder / "root"
        stage.mkdir()
        binary = bytearray(binary_size)
        binary[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", binary, 16, 3)
        struct.pack_into("<H", binary, 18, 62)
        needed = ["libc.so.6", "libcairo.so.2", "libgcc_s.so.1", "libgio-2.0.so.0", "libglib-2.0.so.0", "libgobject-2.0.so.0", "libgtk-4.so.1"]
        source = {name: {"sha256": pub.sha(name.encode()), "bytes": len(name)} for name in pub.SOURCE_FILES}
        proof = {
            "schema": "agpc-view.build-provenance/v1", "package": pub.IDENTITY,
            "release_admitted": False, "runtime_ready": False,
            "source": {"project": 1336, "base_commit": SOURCE_SHA, "dirty_candidate": False,
                       "files": source, "tree_sha256": pub.sha(pub.encoded(source))},
            "binary": {"sha256": pub.sha(binary), "bytes": len(binary), "abi": {
                "needed": needed, "format": "ELF64", "machine": "x86-64", "glibc_minimum": "2.39",
                "interpreter": "/lib64/ld-linux-x86-64.so.2"}},
        }
        if proof_change:
            proof_change(proof)
        payload = {name: (name + "\n").encode() for name in pub.PAYLOAD}
        payload["usr/bin/agpc-view"] = bytes(binary)
        payload["usr/share/applications/agpc-view.desktop"] = b"[Desktop Entry]\nType=Application\nExec=agpc-view\nTerminal=false\nIcon=agpc-view\n"
        payload["usr/share/doc/agpc-view/PROVENANCE.json"] = pub.encoded(proof)
        files = {}
        for name, data in payload.items():
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            mode = binary_mode if name == "usr/bin/agpc-view" else 0o644
            path.chmod(mode)
            files[name] = {"sha256": pub.sha(data), "bytes": len(data), "mode": format(mode, "04o"), "uid": 0, "gid": 0}
        if extra_payload:
            path = stage / extra_payload
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"unexpected")
        controls = stage / "DEBIAN"
        controls.mkdir()
        (controls / "control").write_text("Package: agpc-view\nVersion: " + pub.VERSION +
            "\nArchitecture: amd64\nMaintainer: Test <test@example.invalid>\nDescription: Inert publisher test fixture\nDepends: " + ", ".join(pub.DEPENDENCIES) + "\n")
        (controls / "md5sums").write_text("".join(hashlib.md5(data).hexdigest() + "  " + name + "\n" for name, data in sorted(payload.items())))
        if extra_control:
            (controls / extra_control).write_text("#!/bin/sh\nexit 0\n")
            (controls / extra_control).chmod(0o755)
        for directory in [stage, *stage.rglob("*")]:
            if directory.is_dir():
                directory.chmod(0o755)
        package = folder / pub.PACKAGE
        subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(stage), str(package)],
                       check=True, capture_output=True, timeout=30)
        build = {"schema": "agpc-view.package-manifest/v1", "package": pub.IDENTITY, "filename": pub.PACKAGE,
                 "sha256": pub.sha(package.read_bytes()), "bytes": package.stat().st_size,
                 "dependencies": list(pub.DEPENDENCIES), "files": files, "provenance": proof, "release_admitted": False}
        return package, build

    @staticmethod
    def readelf(command, option, path):
        if command != "readelf":
            raise AssertionError("unexpected command: " + command)
        return {
            "--program-headers": "[Requesting program interpreter: /lib64/ld-linux-x86-64.so.2]",
            "--dynamic": "\n".join("(NEEDED) [" + name + "]" for name in (
                "libc.so.6", "libcairo.so.2", "libgcc_s.so.1", "libgio-2.0.so.0", "libglib-2.0.so.0", "libgobject-2.0.so.0", "libgtk-4.so.1")),
            "--version-info": "GLIBC_2.2.5 GLIBC_2.39",
        }[option]

    def validate(self, package, build):
        with patch.object(pub, "run", side_effect=self.readelf):
            pub.validate_build(package, build, self.record)

    def test_inert_scriptless_fixture_exercises_archive_validation(self):
        self.validate(*self.fixture())

    def test_larger_native_tls_binary_has_an_explicit_bounded_payload_budget(self):
        self.validate(*self.fixture(binary_size=pub.LIMIT + 1))
        with self.assertRaisesRegex(ValueError, "oversized DEB file"):
            self.validate(*self.fixture(binary_size=pub.PAYLOAD_LIMIT + 1))

    def test_added_scripts_payload_and_privileged_modes_are_rejected(self):
        for options in ({"extra_control": "postinst"}, {"extra_control": "triggers"},
                        {"extra_payload": "usr/bin/unreviewed"}, {"binary_mode": 0o4755}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.validate(*self.fixture(**options))

    def test_recomputed_package_cannot_hide_bad_source_or_binary_provenance(self):
        changes = {
            "dirty source": lambda p: p["source"].update(dirty_candidate=True),
            "different source": lambda p: p["source"].update(base_commit="c" * 40),
            "bad tree hash": lambda p: p["source"].update(tree_sha256="0" * 64),
            "missing source input": lambda p: p["source"]["files"].pop("components/agpc-view/Cargo.lock"),
            "different binary hash": lambda p: p["binary"].update(sha256="0" * 64),
            "claimed admission": lambda p: p.update(release_admitted=True),
            "claimed readiness": lambda p: p.update(runtime_ready=True),
        }
        for label, change in changes.items():
            with self.subTest(label=label), self.assertRaises(ValueError):
                self.validate(*self.fixture(proof_change=change))

    def test_manifest_cannot_change_dependencies_or_embedded_provenance(self):
        for change in (lambda b: b["dependencies"].append("unreviewed"),
                       lambda b: b.update(provenance={}),
                       lambda b: b["files"]["usr/bin/agpc-view"].update(sha256="0" * 64)):
            package, build = self.fixture()
            change(build)
            with self.assertRaises(ValueError):
                self.validate(package, build)

    def test_actual_elf_metadata_must_match_reviewed_abi(self):
        package, build = self.fixture()
        for target, replacement in (("--dynamic", "(RUNPATH) [/tmp/lib]"),
                                    ("--program-headers", "[Requesting program interpreter: /tmp/loader]"),
                                    ("--version-info", "GLIBC_2.40"),
                                    ("--version-info", "GLIBC_2.39 GLIBC_PRIVATE")):
            def altered(command, option, path):
                return replacement if option == target else self.readelf(command, option, path)
            with self.subTest(target=target, replacement=replacement), \
                    patch.object(pub, "run", side_effect=altered), self.assertRaises(ValueError):
                pub.validate_build(package, build, self.record)

    def bundle(self):
        package, build = self.fixture()
        original = pub.encoded({**build, "native_library_resolution": "producer-specific paths"})
        record = record_for(package.read_bytes(), original)
        folder = Path(tempfile.mkdtemp(dir=self.root))
        files = {pub.PACKAGE: package.read_bytes(), "MANIFEST.json": pub.encoded(pub.manifest_for(record, build))}
        files["SHA256SUMS"] = "".join(pub.sha(data) + "  " + name + "\n" for name, data in sorted(files.items())).encode()
        record["assets"] = {name: {"sha256": pub.sha(data), "bytes": len(data)} for name, data in files.items()}
        for name, data in files.items():
            (folder / name).write_bytes(data)
        return folder, record, original

    def test_bundle_keeps_original_build_except_host_library_resolution(self):
        folder, record, original = self.bundle()
        with patch.object(pub, "run", side_effect=self.readelf):
            pub.validate_bundle(folder, record, original)

    def test_changed_candidate_or_extra_file_is_rejected(self):
        for name in (*sorted(pub.ASSETS), "unexpected.txt"):
            folder, record, original = self.bundle()
            (folder / name).write_bytes(b"tampered candidate")
            with self.subTest(name=name), self.assertRaises(ValueError):
                pub.validate_bundle(folder, record, original)

    def test_repinning_public_manifest_cannot_replace_original_ci_manifest(self):
        folder, record, original = self.bundle()
        manifest = json.loads((folder / "MANIFEST.json").read_bytes())
        manifest["build"]["provenance"]["source"]["base_commit"] = "c" * 40
        changed = pub.encoded(manifest)
        (folder / "MANIFEST.json").write_bytes(changed)
        record["assets"]["MANIFEST.json"] = {"sha256": pub.sha(changed), "bytes": len(changed)}
        with self.assertRaisesRegex(ValueError, "differs from original producer"):
            pub.validate_bundle(folder, record, original)

    def test_invalid_candidate_fails_before_key_import_or_signing(self):
        folder, record, original = self.bundle()
        scripts = self.root / "scripts"
        scripts.mkdir()
        (scripts / "agpc-view-release.json").write_bytes(pub.encoded(record))
        calls = []
        def run(*args, **kwargs):
            calls.append(args)
            self.assertEqual(args[:3], ("gh", "release", "download"))
            name = args[args.index("--pattern") + 1]
            destination = Path(args[args.index("--dir") + 1]) / name
            destination.write_bytes(b"tampered" if name == pub.PACKAGE else (folder / name).read_bytes())
            return ""
        with patch.dict(os.environ, ENVIRONMENT, clear=True), patch.object(pub, "ROOT", self.root), \
                patch.object(pub, "fresh_main", return_value=original), patch.object(pub, "absent_release"), \
                patch.object(pub, "run", side_effect=run), patch.object(publish_native, "sign_files") as signer, \
                self.assertRaisesRegex(ValueError, "candidate asset mismatch"):
            pub.publish()
        signer.assert_not_called()
        self.assertEqual(len(calls), len(pub.ASSETS))


class PublicationGuards(unittest.TestCase):
    def test_only_exact_dispatch_context_is_accepted(self):
        with patch.dict(os.environ, ENVIRONMENT, clear=True):
            pub.context()
        for key in ENVIRONMENT:
            with self.subTest(key=key), patch.dict(os.environ, {**ENVIRONMENT, key: "wrong"}, clear=True), \
                    self.assertRaises(ValueError):
                pub.context()

    def test_wrong_context_fails_before_any_external_command(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(pub, "run") as run, \
                patch.object(pub, "fresh_main") as fresh, patch.object(publish_native, "sign_files") as signer, \
                self.assertRaisesRegex(ValueError, "publisher context"):
            pub.publish()
        run.assert_not_called()
        fresh.assert_not_called()
        signer.assert_not_called()

    def test_existing_release_or_unknown_absence_is_rejected(self):
        for code, error in ((0, ""), (1, "HTTP 403"), (1, "connection failed")):
            with self.subTest(code=code, error=error), \
                    patch.object(pub.subprocess, "run", return_value=subprocess.CompletedProcess([], code, "", error)), \
                    self.assertRaises(ValueError):
                pub.absent_release()
        with patch.object(pub.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "HTTP 404")) as run:
            pub.absent_release()
            self.assertEqual(run.call_count, 2)

    def test_duplicate_json_fields_and_oversized_metadata_are_rejected(self):
        for data in (b'{"sha256":"old","sha256":"new"}', b" " * (pub.LIMIT + 1)):
            with self.assertRaises(ValueError):
                pub.read_json(data)

    def test_command_failure_does_not_disclose_credentials(self):
        errors = (subprocess.CalledProcessError(1, ["git", "secret-token"], stderr="private-url"),
                  subprocess.TimeoutExpired(["git", "secret-token"], 60, stderr="private-url"))
        for error in errors:
            with patch.object(pub.subprocess, "check_output", side_effect=error), \
                    self.assertRaisesRegex(RuntimeError, "^publication command failed: git$"):
                pub.run("git", "secret-token")


if __name__ == "__main__":
    unittest.main()
