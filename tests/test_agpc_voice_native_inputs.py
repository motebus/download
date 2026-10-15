"""Offline native-input staging checks; no credentials, transport or package execution."""
import copy
import hashlib
import io
import json
from pathlib import Path
import stat
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import stage_agpc_voice_native_inputs as staging


VOICE_COMMIT = "92a89e307762478de23b9559d3b755e9ee42b231"
VOICE_FILENAME = "agpc-voice_0.1.0~office117.20261015.2_all.deb"
EXPECTED_FILES = {"SOURCE.json", "scripts/verify_agpc_voice_native_ci.py"} | {
    "src/" + name + ".py" for name in (
        "native_voice", "native_install", "native_rpc", "rdp_client",
        "browser_install", "desktop_preferences")
} | {
    "packages/" + VOICE_FILENAME,
    "packages/agpc-voice_0.1.0~candidate.6_all.deb",
    "packages/agpc-freeswitch-core_1.11.3+agpc1_amd64.deb",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


class VoiceNativeInputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "staged"
        self.commit = "a" * 40
        self.job = 73001
        self.original = b"offline component fixture; never executed or installed\n"
        self.files = {
            name: (b'raise AssertionError("staged source must not execute")\n'
                   if name.endswith(".py") else ("fixture " + name + "\n").encode())
            for name in EXPECTED_FILES - {"SOURCE.json"}
        }
        self.files["packages/" + VOICE_FILENAME] = self.original
        self.source = dict(
            schema="agpc.voice-native-ci-source/v1", installer_commit=self.commit,
            production_gate=False, voice_commit=VOICE_COMMIT, voice_ci_job=65637,
            voice_review=4, published=False, native_acceptance=False,
            normal_installer_transaction=False,
        )
        self.inputs = dict(schema="agpc.voice-native-ci-public-inputs/v1",
                           source_commit=self.commit, ci_job=self.job)
        self.api_records = {}
        for project, job, commit, pipeline in (
            (1341, self.job, self.commit, 38001), (1348, 65637, VOICE_COMMIT, 28057)
        ):
            self.api_records[f"projects/{project}/jobs/{job}"] = dict(
                id=job, status="success", ref="main", tag=False, commit=dict(id=commit),
                pipeline=dict(id=pipeline, sha=commit, ref="main"))
            self.api_records[f"projects/{project}/pipelines/{pipeline}"] = dict(
                id=pipeline, status="success", ref="main", sha=commit)
        self.get_json = Mock(side_effect=lambda endpoint: copy.deepcopy(self.api_records[endpoint]))
        self.get_bytes = Mock(side_effect=self.artifact)
        self.refresh_source()
        self.pack()

    def artifact(self, endpoint):
        if endpoint == f"projects/1341/jobs/{self.job}/artifacts":
            return self.archive
        if endpoint == "projects/1348/jobs/65637/artifacts/components/agpc-voice/dist/" + VOICE_FILENAME:
            return self.original
        raise AssertionError("Unexpected artifact endpoint: " + endpoint)

    def refresh_source(self):
        self.source["files"] = [
            dict(path=name, bytes=len(raw), sha256=digest(raw))
            for name, raw in sorted(self.files.items()) if name != "SOURCE.json"
        ]
        self.save_source()

    def save_source(self):
        self.files["SOURCE.json"] = json.dumps(self.source, sort_keys=True).encode()

    def pin_archive(self, data):
        self.archive = data
        self.inputs.update(archive_bytes=len(data), archive_sha256=digest(data))

    def pack(self, extra=()):
        buffer = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)  # Intentional duplicate-member fixtures.
            with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for directory in ("", "src/", "scripts/", "packages/"):
                    archive.writestr(staging.PREFIX + directory, b"")
                for name, raw in sorted(self.files.items()):
                    archive.writestr(staging.PREFIX + name, raw)
                for name, raw in extra:
                    archive.writestr(name, raw)
        self.pin_archive(buffer.getvalue())

    def run_stage(self, inputs=None):
        # Only the fixed component fixture pins are replaced. ZIP, source inventory,
        # per-file SHA256 and exact main-CI validation all use the real implementation.
        with patch.multiple(staging, VOICE_BYTES=len(self.original_fixture),
                            VOICE_SHA256=digest(self.original_fixture)):
            return staging.stage(self.inputs if inputs is None else inputs, self.output,
                                 get_json=self.get_json, get_bytes=self.get_bytes)

    @property
    def original_fixture(self):
        return b"offline component fixture; never executed or installed\n"

    def reject(self, message, exception=ValueError, inputs=None):
        with self.assertRaisesRegex(exception, message):
            self.run_stage(inputs=inputs)
        self.assertFalse(self.output.exists(), "Rejected inputs must not be materialized")

    def test_production_pins_remain_exact_office117_2(self):
        self.assertEqual(staging.VOICE_COMMIT, VOICE_COMMIT)
        self.assertEqual(staging.VOICE_JOB, 65637)
        self.assertEqual(staging.VOICE_REVIEW, 4)
        self.assertEqual(staging.VOICE_FILENAME, VOICE_FILENAME)
        self.assertEqual(staging.VOICE_BYTES, 48834)
        self.assertEqual(staging.VOICE_SHA256,
                         "4f3daddb1e6b1290fb2bbc411b75a3ff04f26ffc9eb9f097416db40220a20453")
        self.assertEqual(staging.FILES, EXPECTED_FILES)

    def test_success_stages_only_exact_bytes_after_both_main_jobs_and_original_deb(self):
        self.assertEqual(self.run_stage(), self.commit)
        actual = {p.relative_to(self.output).as_posix(): p.read_bytes()
                  for p in self.output.rglob("*") if p.is_file()}
        self.assertEqual(actual, self.files)
        self.assertEqual([c.args[0] for c in self.get_json.call_args_list], [
            f"projects/1341/jobs/{self.job}", "projects/1341/pipelines/38001",
            "projects/1348/jobs/65637", "projects/1348/pipelines/28057"])
        self.assertEqual([c.args[0] for c in self.get_bytes.call_args_list], [
            f"projects/1341/jobs/{self.job}/artifacts",
            "projects/1348/jobs/65637/artifacts/components/agpc-voice/dist/" + VOICE_FILENAME])
        self.assertFalse(json.loads(actual["SOURCE.json"])["production_gate"])

    def test_invalid_inputs_fail_before_any_api_request(self):
        for inputs in ([], "invalid", 1, True):
            with self.subTest(inputs=inputs):
                self.reject("Native inputs must be an object", inputs=inputs)
        invalid = {
            "schema": ["wrong", None], "source_commit": ["main", "A" * 40, 1, None],
            "ci_job": [True, 0, -1, "73001"],
            "archive_bytes": [True, 0, -1, staging.voice.LIMIT + 1],
            "archive_sha256": ["f" * 63, "G" * 64, None, 1],
        }
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    inputs = dict(self.inputs, **{field: value})
                    self.reject(".", inputs=inputs)
        self.get_json.assert_not_called()
        self.get_bytes.assert_not_called()

    def test_both_jobs_require_exact_successful_nontag_main_identity(self):
        for project, job in ((1341, self.job), (1348, 65637)):
            endpoint = f"projects/{project}/jobs/{job}"
            original = copy.deepcopy(self.api_records[endpoint])
            changes = (
                ("status", "failed"), ("status", "running"), ("ref", "feature/test"),
                ("tag", True), ("id", job + 1), ("commit", dict(id="b" * 40)),
                ("pipeline", dict(id=original["pipeline"]["id"], sha="b" * 40, ref="main")),
                ("pipeline", dict(id=original["pipeline"]["id"], sha=original["commit"]["id"], ref="feature")),
            )
            for field, value in changes:
                with self.subTest(project=project, field=field, value=value):
                    self.api_records[endpoint] = dict(original, **{field: value})
                    self.reject("successful exact main CI required")
            self.api_records[endpoint] = original
        self.get_bytes.assert_not_called()

    def test_both_pipelines_must_succeed_for_the_same_main_commit(self):
        for project, pipeline in ((1341, 38001), (1348, 28057)):
            endpoint = f"projects/{project}/pipelines/{pipeline}"
            original = dict(self.api_records[endpoint])
            for field, value in (("status", "failed"), ("ref", "feature"),
                                 ("sha", "b" * 40), ("id", pipeline + 1)):
                with self.subTest(project=project, field=field):
                    self.api_records[endpoint] = dict(original, **{field: value})
                    self.reject("successful exact main pipeline required")
            self.api_records[endpoint] = original
        self.get_bytes.assert_not_called()

    def test_transport_failure_is_not_retried_or_materialized(self):
        self.get_bytes.side_effect = OSError("fixture transport unavailable")
        self.reject("fixture transport unavailable", OSError)
        self.assertEqual(self.get_bytes.call_count, 1)

    def test_original_zip_length_and_sha256_are_independently_required(self):
        self.inputs["archive_bytes"] += 1
        self.reject("Native archive mismatch")
        self.inputs["archive_bytes"] -= 1
        self.inputs["archive_sha256"] = "f" * 64
        self.reject("Native archive mismatch")
        self.assertTrue(all(c.args[0].startswith("projects/1341/")
                            for c in self.get_bytes.call_args_list))

    def test_correctly_pinned_nonzip_still_fails_without_output(self):
        self.pin_archive(b"not an archive")
        self.reject("File is not a zip file", zipfile.BadZipFile)

    def test_missing_extra_duplicate_and_traversal_members_are_rejected(self):
        for name in ("unrelated.txt", "../escaped", "src/../../escaped",
                     "src\\native_voice.py", "/absolute"):
            with self.subTest(name=name):
                self.pack(extra=[(staging.PREFIX + name, b"unexpected")])
                self.reject("Unexpected native artifact file")
        self.pack(extra=[(staging.PREFIX + "src/native_voice.py", b"duplicate")])
        self.reject("Unexpected native artifact file")
        del self.files["src/native_voice.py"]
        self.pack()
        self.reject("Native input files missing")
        self.assertFalse((self.root / "escaped").exists())

    def test_foreign_prefix_and_extra_directory_are_rejected(self):
        self.pack(extra=[("different-prefix/file", b"unexpected")])
        self.reject("Unsafe native artifact member")
        self.pack(extra=[(staging.PREFIX + "unexpected/", b"")])
        self.reject("Unexpected native artifact directory")

    def test_symlink_member_is_rejected_before_extraction(self):
        member = zipfile.ZipInfo(staging.PREFIX + "src/native_voice.py")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        del self.files["src/native_voice.py"]
        self.pack(extra=[(member, b"../../outside")])
        self.reject("Unsafe native artifact member")
        self.assertFalse((self.root / "outside").exists())

    def test_encrypted_member_flag_is_rejected_before_read(self):
        data = bytearray(self.archive)
        central = data.index(b"PK\x01\x02")
        flags = struct.unpack_from("<H", data, central + 8)[0]
        struct.pack_into("<H", data, central + 8, flags | 1)
        self.pin_archive(bytes(data))
        self.reject("Unsafe native artifact member")

    def test_empty_member_is_rejected(self):
        self.files["src/native_voice.py"] = b""
        self.refresh_source()
        self.pack()
        self.reject("Native artifact exceeds limit")

    def test_compressed_member_cannot_exceed_uncompressed_limit(self):
        self.files["src/native_voice.py"] = b"x" * 8193
        self.refresh_source()
        self.pack()
        self.assertLess(len(self.archive), 8192)
        with patch.object(staging.voice, "LIMIT", 8192):
            self.reject("Native artifact exceeds limit")

    def test_total_expansion_limit_applies_across_individually_bounded_members(self):
        for name in self.files:
            if name.startswith("src/"):
                self.files[name] = b"x" * 1500
        self.refresh_source()
        self.pack()
        self.assertLess(len(self.archive), 4096)
        self.assertTrue(all(len(raw) <= 4096 for raw in self.files.values()))
        with patch.object(staging.voice, "LIMIT", 4096):
            self.reject("Native artifact exceeds limit")

    def test_malformed_source_json_and_duplicate_fields_are_rejected(self):
        for raw in (b"{", b"[]", b'{"schema":1,"schema":2}'):
            with self.subTest(raw=raw):
                self.files["SOURCE.json"] = raw
                self.pack()
                self.reject(".")

    def test_source_identity_and_all_nonacceptance_flags_are_required(self):
        original = copy.deepcopy(self.source)
        changes = [
            ("schema", "wrong"), ("installer_commit", "b" * 40),
            ("voice_commit", "b" * 40), ("voice_ci_job", 65506), ("voice_review", 3),
        ] + [(key, value) for key in ("production_gate", "published", "native_acceptance",
                                     "normal_installer_transaction") for value in (True, 0, None)]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                self.source = dict(original, **{field: value})
                self.save_source()
                self.pack()
                self.reject("Native input source binding mismatch")

    def test_source_inventory_cannot_omit_duplicate_or_replace_records(self):
        records = self.source["files"]
        invalid = [None, {}, records[:-1], records + records[:1],
                   records[:-1] + records[:1], records[:-1] + [None],
                   records[:-1] + [dict(records[-1], path="outside")]]
        for value in invalid:
            with self.subTest(records=value):
                self.source["files"] = value
                self.save_source()
                self.pack()
                self.reject("Native source inventory mismatch")

    def test_each_source_record_requires_actual_byte_count_and_hash(self):
        original = copy.deepcopy(self.source["files"])
        for field, value in (("bytes", 0), ("bytes", "1"), ("sha256", "f" * 64),
                             ("sha256", None)):
            with self.subTest(field=field):
                self.source["files"] = copy.deepcopy(original)
                self.source["files"][0][field] = value
                self.save_source()
                self.pack()
                self.reject("Native source byte mismatch")

    def test_modified_runtime_with_unchanged_record_fails_despite_valid_zip_pin(self):
        self.files["src/native_voice.py"] += b"# tampered runtime\n"
        self.pack()
        self.reject("Native source byte mismatch")

    def test_original_component_endpoint_bytes_must_match_staged_package(self):
        self.original = b"different original component artifact"
        self.reject("Native Voice input differs from original component main CI")

    def test_matching_forged_component_and_inventory_cannot_replace_fixed_component_pin(self):
        self.original = b"x" * len(self.original_fixture)
        self.files["packages/" + VOICE_FILENAME] = self.original
        self.refresh_source()
        self.pack()
        self.reject("Native Voice input differs from original component main CI")

    def test_fixed_component_length_cannot_be_replaced_by_agreeing_api_and_inventory(self):
        self.original += b"extra"
        self.files["packages/" + VOICE_FILENAME] = self.original
        self.refresh_source()
        self.pack()
        self.reject("Native Voice input differs from original component main CI")

    def test_existing_output_is_preserved(self):
        self.output.mkdir()
        sentinel = self.output / "keep"
        sentinel.write_bytes(b"original")
        with self.assertRaisesRegex(ValueError, "Native output already exists"):
            self.run_stage()
        self.assertEqual(list(self.output.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
