"""Exact native-entry provenance/archive fixtures; no API, shell or DEB execution."""
import base64
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import stage_agpc_voice_native_entry_inputs as staging
import prepare_agpc_voice_native_entry_session as session


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class NativeEntryInputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name) / 'output'
        # Consumer identities are deliberately synthetic; no new producer has
        # been selected in the active public input record by this patch.
        self.commit, self.job, self.review = 'a' * 40, 73001, 73002
        self.packages = {name: ('synthetic nonexecutable archive ' + name).encode()
                         for name in staging.PACKAGE_SHA256}
        self.files = {'packages/' + name: raw for name, raw in self.packages.items()}
        for name in staging.RUNTIME_NAMES:
            self.files['src/' + name + '.py'] = b'raise AssertionError("source must never execute")\n'
        self.files['src/native_voice.py'] = (b'INSTALL_CONTRACT_ADMITTED = False\n'
            b"RELEASE = 'office117.20261015.2+l1isolation.2+sipauth.1+radio909.1+continuous117.1+zhtw.1+utilities.1'\nraise AssertionError('must never execute')\n")
        for name in ('verify_agpc_voice_native_ci.py', 'verify_agpc_voice_native_entry_ci.py'):
            self.files['scripts/' + name] = b'raise AssertionError("harness must never execute")\n'
        self.wrapper()
        self.source = dict(schema='agpc.voice-native-entry-ci-source/v1', installer_commit=self.commit,
            voice_commit=staging.VOICE_COMMIT, voice_ci_pipeline=28200, voice_ci_job=65966, voice_review=25,
            **{k: False for k in staging.FALSE_FLAGS})
        self.inputs = dict(schema='agpc.voice-native-entry-ci-public-inputs/v1',
            source_commit=self.commit, ci_job=self.job, install_review=self.review)
        self.api = {}
        for project, job, commit, pipeline, review in (
                (1341, self.job, self.commit, 73003, self.review),
                (1348, 65966, staging.VOICE_COMMIT, 28200, 25)):
            self.api[f'projects/{project}/jobs/{job}'] = dict(id=job, status='success', ref='main', tag=False,
                name='agpc-voice-native-entry-ci-inputs' if project == 1341 else 'voice-source-cohort',
                commit=dict(id=commit), pipeline=dict(id=pipeline, sha=commit, ref='main'))
            self.api[f'projects/{project}/pipelines/{pipeline}'] = dict(id=pipeline, status='success', ref='main', sha=commit)
            endpoint = f'projects/{project}/merge_requests/{review}'
            self.api[endpoint] = dict(state='merged', target_branch='main', merge_commit_sha=commit)
            self.api[endpoint + '/approvals'] = dict(approved=True, approved_by=[dict(user=dict(id=34))])
            self.api[f'projects/{project}/members/all/34'] = dict(id=34, access_level=50)
        self.get_json = Mock(side_effect=lambda endpoint: copy.deepcopy(self.api[endpoint]))
        self.original = self.packages[staging.VOICE_FILENAME]
        self.get_bytes = Mock(side_effect=self.artifact)
        self.refresh()

    def wrapper(self):
        sources = {name: self.files['src/' + name + '.py'].decode() for name in staging.RUNTIME_NAMES}
        payload = base64.b64encode(gzip.compress(json.dumps(sources).encode(), mtime=0)).decode()
        self.files['agpc-voice.sh'] = ("#!/bin/bash\npython3 - <<'AGPC_VOICE_PACKAGED_RUNTIME'\n"
            "import base64\npayload = base64.b64decode(" + repr(payload) + ")\n"
            "raise AssertionError('wrapper must never execute')\nAGPC_VOICE_PACKAGED_RUNTIME\n").encode()

    def refresh(self):
        self.source['files'] = [dict(path=name, bytes=len(raw), sha256=sha(raw))
                               for name, raw in sorted(self.files.items()) if name != 'SOURCE.json']
        self.save_source()
        self.pack()

    def save_source(self):
        self.files['SOURCE.json'] = json.dumps(self.source).encode()

    def pack(self, extra=()):
        stream = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for name, raw in self.files.items():
                    archive.writestr(staging.PREFIX + name, raw)
                for name, raw in extra:
                    archive.writestr(name, raw)
        self.archive = stream.getvalue()
        self.inputs.update(archive_bytes=len(self.archive), archive_sha256=sha(self.archive))

    def artifact(self, endpoint):
        if endpoint == f'projects/1341/jobs/{self.job}/artifacts':
            return self.archive
        if endpoint == 'projects/1348/jobs/65966/artifacts/components/agpc-voice/dist/' + staging.VOICE_FILENAME:
            return self.original
        raise AssertionError('Unexpected endpoint')

    def stage(self):
        with patch.object(staging, 'PACKAGE_SHA256', {name: sha(raw) for name, raw in self.packages.items()}), \
             patch.object(staging, 'VOICE_BYTES', len(self.packages[staging.VOICE_FILENAME])):
            return staging.stage(self.inputs, self.output, self.get_json, self.get_bytes)

    def reject(self, reason='.'):
        with self.assertRaisesRegex(ValueError, reason):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_valid_exact_bundle_requires_jobs_approvals_original_and_closed_runtime(self):
        self.assertEqual(self.stage(), (self.commit, sha(self.files['SOURCE.json'])))
        self.assertEqual({p.relative_to(self.output).as_posix(): p.read_bytes()
                          for p in self.output.rglob('*') if p.is_file()}, self.files)
        self.assertEqual(len(self.files), 14)
        self.assertEqual(len(self.source['files']), 13)
        self.assertEqual((self.output / 'agpc-voice.sh').stat().st_mode & 0o777, 0o755)
        for project, review in ((1341, self.review), (1348, 25)):
            self.get_json.assert_any_call(f'projects/{project}/merge_requests/{review}/approvals')
            self.get_json.assert_any_call(f'projects/{project}/members/all/34')

    def test_session_hash_comes_from_verified_bytes_despite_staging_replacement(self):
        original_chmod = Path.chmod
        def replace_after_write(path, mode):
            original_chmod(path, mode)
            if path == self.output / 'SOURCE.json':
                path.write_bytes(b'changed after the verified write')
        with patch.object(Path, 'chmod', replace_after_write):
            commit, manifest_sha256 = self.stage()
        self.assertEqual(commit, self.commit)
        self.assertEqual(manifest_sha256, sha(self.files['SOURCE.json']))
        self.assertNotEqual(manifest_sha256, sha((self.output / 'SOURCE.json').read_bytes()))

    def test_production_pins(self):
        self.assertEqual(staging.VOICE_COMMIT, '71b746438e8990ae6685b8ca86dd6bd9e0cdc9e9')
        self.assertEqual((staging.VOICE_JOB, staging.VOICE_PIPELINE, staging.VOICE_REVIEW), (65966, 28200, 25))
        self.assertEqual(staging.VOICE_FILENAME,
                         'agpc-voice_0.1.0~office117.20261015.2+l1isolation.2+sipauth.1+radio909.1+continuous117.1+zhtw.1+utilities.1_all.deb')
        self.assertEqual(staging.VOICE_BYTES, 348352)
        self.assertEqual(staging.PACKAGE_SHA256[staging.VOICE_FILENAME],
                         '394baefe1242a288f822f5df6d90dd5a6c0eac7d71891aa66f66da19b2cb829f')
        self.assertEqual(len(staging.PACKAGE_SHA256), 4)
        self.assertEqual(staging.PACKAGE_SHA256['agpc-voice_0.1.0~office117.20261015.2+l1isolation.2+sipauth.1+radio909.1+continuous117.1+zhtw.1_all.deb'],
                         '9216cb1210083ca6e8fa2a8737451a4d8af120c7e92ff0c627b0b9cab890d4b1')
        self.assertEqual(staging.PACKAGE_SHA256['agpc-voice_0.1.0~office117.20261015.2+l1isolation.2_all.deb'],
                         '89005f0c53235e7f72370a624a397d4ef4221a52d1a36d23fcb6b129f4c8d15a')
        self.assertEqual(staging.PACKAGE_SHA256['agpc-freeswitch-core_1.11.3+agpc1_amd64.deb'],
                         'a207b111702e7ae7c8682cffa7468a450b66b4acb69203a8f545edcff25a25e4')

    def test_root_session_and_stager_require_the_same_selected_and_predecessor_bundle(self):
        self.assertEqual(session.FILES, staging.FILES - {'SOURCE.json'})
        self.assertNotIn('packages/agpc-voice_0.1.0~candidate.6_all.deb', session.FILES)

    def test_bad_input_types_and_extra_override_never_contact_api(self):
        original = self.inputs
        for value in ([], None, dict(original, schema='old'), dict(original, ci_job=True),
                      dict(original, install_review=0), dict(original, source_commit='main'),
                      dict(original, archive_bytes=True), dict(original, archive_sha256='bad'),
                      dict(original, artifacts_dir='/tmp/override')):
            self.inputs = value
            self.reject()
        self.inputs = original
        self.get_json.assert_not_called()
        self.get_bytes.assert_not_called()

    def test_actual_reviews_must_be_merged_exact_and_maintainer_approved(self):
        for project, review in ((1341, self.review), (1348, 25)):
            prefix = f'projects/{project}/merge_requests/{review}'
            cases = [(prefix, 'state', 'opened'), (prefix, 'merge_commit_sha', 'b' * 40),
                     (prefix + '/approvals', 'approved', False),
                     (prefix + '/approvals', 'approved_by', []),
                     (f'projects/{project}/members/all/34', 'access_level', 30)]
            for endpoint, key, value in cases:
                with self.subTest(endpoint=endpoint, key=key), patch.dict(self.api[endpoint], {key: value}):
                    self.reject('review|approval')
        self.get_bytes.assert_not_called()

    def test_exact_main_jobs_pipeline_and_producer_name(self):
        for endpoint, key, value in (
            (f'projects/1341/jobs/{self.job}', 'name', 'agpc-voice-native-ci-inputs'),
            (f'projects/1341/jobs/{self.job}', 'ref', 'feature'),
            ('projects/1348/jobs/65966', 'status', 'running'),
            ('projects/1348/pipelines/28200', 'status', 'failed')):
            with self.subTest(endpoint=endpoint, key=key), patch.dict(self.api[endpoint], {key: value}):
                self.reject('job|CI|pipeline')
        self.get_bytes.assert_not_called()

    def test_archive_hash_and_length_are_both_required(self):
        for key, value in [('archive_bytes', len(self.archive) + 1), ('archive_sha256', 'f' * 64)]:
            with self.subTest(key=key), patch.dict(self.inputs, {key: value}):
                self.reject('archive mismatch')

    def test_paths_duplicates_symlinks_and_nonregular_members_fail_closed(self):
        for name in ('../escape', 'scripts/../../escape', '/absolute', 'unexpected',
                     'src\\native_voice.py', 'agpc-voice.sh', 'extra/'):
            self.pack(extra=[(staging.PREFIX + name, b'x')])
            self.reject('artifact')
        for kind in (stat.S_IFLNK, stat.S_IFIFO):
            member = zipfile.ZipInfo(staging.PREFIX + 'extra')
            member.create_system = 3
            member.external_attr = (kind | 0o644) << 16
            self.pack(extra=[(member, b'outside')])
            self.reject('Unsafe native artifact')

    def test_claims_schema_inventory_and_byte_counts_are_bound(self):
        original = copy.deepcopy(self.source)
        for field, value in [('schema', 'old'), ('voice_review', 22.0), ('voice_ci_pipeline', 28133)] + [
                (key, True) for key in staging.FALSE_FLAGS]:
            self.source = dict(original, **{field: value})
            self.save_source(); self.pack()
            self.reject('source binding')
        self.source = copy.deepcopy(original)
        self.source['files'][0]['bytes'] += 1
        self.save_source(); self.pack()
        self.reject('source byte')

    def test_runtime_payload_parity_and_closed_literal_gate(self):
        self.files['src/native_voice.py'] += b'# mismatched embedded payload\n'
        self.refresh()
        self.reject('Embedded and staged')
        self.files['src/native_voice.py'] = self.files['src/native_voice.py'].replace(b'= False', b'= True')
        self.wrapper(); self.refresh()
        self.reject('closed source gate')

    def test_previous_closed_runtime_cannot_validate_the_new_cohort(self):
        original = self.files['src/native_voice.py']
        for predecessor in (b'office117.20261015.2', b'office117.20261015.2+l1isolation.2',
                            b'office117.20261015.2+l1isolation.2+sipauth.1', b'office117.20261015.2+l1isolation.2+sipauth.1+radio909.1+continuous117.1'):
            with self.subTest(predecessor=predecessor):
                self.files['src/native_voice.py'] = original.replace(
                    b'office117.20261015.2+l1isolation.2+sipauth.1+radio909.1+continuous117.1+zhtw.1+utilities.1', predecessor)
                self.wrapper(); self.refresh()
                self.reject('closed source gate')

    def test_both_predecessor_archives_are_required_and_pinned_after_rehash(self):
        for filename in ('agpc-voice_0.1.0~office117.20261015.2+l1isolation.2+sipauth.1+radio909.1+continuous117.1+zhtw.1_all.deb',
                         'agpc-voice_0.1.0~office117.20261015.2+l1isolation.2_all.deb'):
            name = 'packages/' + filename
            original = self.files[name]
            with self.subTest(filename=filename, change='missing'):
                del self.files[name]
                self.refresh()
                self.reject('input files missing')
            with self.subTest(filename=filename, change='changed'):
                self.files[name] = b'changed predecessor'
                self.refresh()
                self.reject('package pin')
            self.files[name] = original
            self.refresh()

    def test_fourth_archive_cannot_be_replaced_by_an_unselected_predecessor(self):
        name = 'packages/agpc-voice_0.1.0~office117.20261015.2+l1isolation.2_all.deb'
        self.files['packages/agpc-voice_0.1.0~candidate.6_all.deb'] = self.files.pop(name)
        self.refresh()
        self.reject('Unexpected native artifact file')

    def test_fixed_package_pins_and_original_component_are_independent(self):
        self.original = b'different endpoint archive'
        self.reject('original reviewed component')
        self.files['packages/' + staging.VOICE_FILENAME] += b'forged'
        self.refresh()
        self.reject('package pin')

    def test_expansion_limit_applies_before_source_validation(self):
        self.files['src/native_voice.py'] = b'x' * 20000
        self.refresh()
        with patch.object(staging.voice, 'LIMIT', len(self.archive) + 1):
            self.reject('exceeds limit')

    def test_existing_output_and_dangling_link_are_preserved(self):
        self.output.mkdir()
        keep = self.output / 'keep'; keep.write_bytes(b'owner')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.stage()
        self.assertEqual(keep.read_bytes(), b'owner')
        keep.unlink(); self.output.rmdir()
        self.output.symlink_to(self.output.with_name('missing'))
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.stage()


if __name__ == '__main__':
    unittest.main()
