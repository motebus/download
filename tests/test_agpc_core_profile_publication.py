"""Original Core profile publication binding; no network or package execution."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import publish_agpc_core_profiles as pub
import test_build_agpc_core_profiles as producer_fixtures

SOURCE = 'c' * 40


def encoded(value):
    return (json.dumps(value, indent=2) + '\n').encode()


def repin(files, record):
    files['SHA256SUMS'] = ''.join(pub.sha(data) + '  ' + name + '\n'
                                for name, data in sorted(files.items()) if name != 'SHA256SUMS').encode()
    record['assets'] = {name: {'bytes': len(data), 'sha256': pub.sha(data)} for name, data in files.items()}


def archive_bytes(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        for name, data in sorted(files.items()):
            archive.writestr(pub.PREFIX + name, data)
    return out.getvalue()


class CoreProfilePublication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.producer = producer_fixtures.CoreProducerTests()
        cls.producer.setUp()
        cls.addClassCleanup(cls.producer.doCleanups)
        cls.producer.inputs['installer_tag'] = pub.INSTALLER_TAG
        cls.producer.inputs['aggregate_tag'] = pub.AGGREGATE_TAG
        result = cls.producer.build()
        cls.files = {path.name: path.read_bytes() for path in result.iterdir()}
        cls.inputs = encoded(cls.producer.inputs)
        cls.baseline = {name: (cls.producer.baseline / name).read_bytes() for name in pub.producer.BASELINE_FILES}
        cls.record = {'schema': 'agpc-core-profile.publication-inputs/v1',
                      'installer_tag': pub.INSTALLER_TAG, 'aggregate_tag': pub.AGGREGATE_TAG,
                      'source_project': 1341, 'source_commit': SOURCE, 'source_ref': 'main',
                      'pipeline_id': 123, 'job_id': 456, 'input_sha256': pub.sha(cls.inputs),
                      'assets': {}}
        repin(cls.files, cls.record)
        cls.archive = archive_bytes(cls.files)
        cls.record['archive'] = {'bytes': len(cls.archive), 'sha256': pub.sha(cls.archive)}

    def fixture(self):
        return copy.deepcopy(self.files), copy.deepcopy(self.record), self.inputs, copy.deepcopy(self.baseline)

    def receipts(self):
        pipeline = {'id': 123, 'project_id': 1341, 'status': 'success', 'ref': 'main', 'sha': SOURCE}
        job = {'id': 456, 'name': pub.JOB_NAME, 'status': 'success', 'ref': 'main',
               'allow_failure': False, 'tag': False, 'commit': {'id': SOURCE}, 'pipeline': copy.deepcopy(pipeline)}
        return pipeline, job

    def test_original_bundle_is_closed_and_preserves_baseline(self):
        aggregate = pub.validate_bundle(*self.fixture())
        self.assertEqual(len(self.files), 13)
        self.assertEqual(len(aggregate['assets']), 36)
        self.assertNotIn('agpc-core.sh', self.files)
        self.assertEqual(self.files['agpc-mesh.sh'], self.files['agpc.sh'])
        self.assertTrue(any(a['name'] == 'agpc-core_0.1.0.core.20261106.1_amd64.deb'
                            for a in aggregate['assets']))

    def test_record_refuses_unknown_or_symbolic_inputs(self):
        for key, value in [('source_commit', 'main'), ('source_project', 1336), ('source_ref', 'candidate'),
                           ('installer_tag', 'v0.3.0-96'), ('aggregate_tag', pub.BASELINE_TAG),
                           ('pipeline_id', True), ('job_id', 0), ('extra', True)]:
            _, record, _, _ = self.fixture()
            record[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                pub.validate_record(record)

    def test_each_original_asset_and_committed_input_is_byte_bound(self):
        for name in sorted(pub.FILES):
            files, record, inputs, baseline = self.fixture()
            files[name] += b'changed'
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'CI asset differs'):
                pub.validate_bundle(files, record, inputs, baseline)
        files, record, inputs, baseline = self.fixture()
        with self.assertRaisesRegex(ValueError, 'bundle/input inventory'):
            pub.validate_bundle(files, record, inputs + b' ', baseline)

    def test_missing_extra_and_rehashed_bad_checksum_inventory_rejected(self):
        for change in (lambda f: f.pop('agpc-mesh.sh'), lambda f: f.update(extra=b'extra')):
            files, record, inputs, baseline = self.fixture()
            change(files)
            with self.assertRaisesRegex(ValueError, 'bundle/input inventory'):
                pub.validate_bundle(files, record, inputs, baseline)
        files, record, inputs, baseline = self.fixture()
        files['SHA256SUMS'] = b'wrong\n'
        record['assets']['SHA256SUMS'] = {'sha256': pub.sha(files['SHA256SUMS']), 'bytes': len(files['SHA256SUMS'])}
        with self.assertRaisesRegex(ValueError, 'checksum inventory'):
            pub.validate_bundle(files, record, inputs, baseline)

    def test_original_baseline_cannot_change_or_omit_a_file(self):
        for name in pub.producer.BASELINE_FILES:
            files, record, inputs, baseline = self.fixture()
            baseline[name] += b'changed'
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'baseline blob differs'):
                pub.validate_bundle(files, record, inputs, baseline)
        files, record, inputs, baseline = self.fixture()
        baseline.pop('agpc.sh')
        with self.assertRaisesRegex(ValueError, 'baseline closure differs'):
            pub.validate_bundle(files, record, inputs, baseline)

    def test_rehashed_overlay_cannot_substitute_an_inherited_package(self):
        files, record, inputs, baseline = self.fixture()
        overlay = json.loads(files['agent-computer-apt-overlay.json'])
        overlay['release']['packages'][0]['sha256'] = '0' * 64
        files['agent-computer-apt-overlay.json'] = encoded(overlay)
        manifest = json.loads(files['release-manifest.json'])
        manifest['overlay_sha256'] = pub.sha(files['agent-computer-apt-overlay.json'])
        files['release-manifest.json'] = encoded(manifest)
        repin(files, record)
        with self.assertRaisesRegex(ValueError, 'overlay composition/source binding'):
            pub.validate_bundle(files, record, inputs, baseline)

    def test_source_profile_and_false_acceptance_claims_are_rejected_after_rehash(self):
        for filename, key, value in [('release-manifest.json', 'native_profile_acceptance', 'passed'),
                                     ('release-manifest.json', 'source_commit', 'a' * 40),
                                     ('agpc-mesh.source.json', 'profile', 'full'),
                                     ('agpc-all.source.json', 'sha256', '0' * 64)]:
            files, record, inputs, baseline = self.fixture()
            obj = json.loads(files[filename]); obj[key] = value; files[filename] = encoded(obj)
            repin(files, record)
            with self.subTest(filename=filename, key=key), self.assertRaises(ValueError):
                pub.validate_bundle(files, record, inputs, baseline)

    def test_rehashed_aggregate_cannot_retarget_original_component(self):
        files, record, inputs, baseline = self.fixture()
        aggregate = json.loads(files['aggregate-component-release.json'])
        aggregate['assets'][0]['source_tag'] = 'unreviewed-v1'
        files['aggregate-component-release.json'] = encoded(aggregate)
        repin(files, record)
        with self.assertRaisesRegex(ValueError, 'aggregate/overlay binding'):
            pub.validate_bundle(files, record, inputs, baseline)

    def test_private_source_locations_are_rejected(self):
        files, record, inputs, baseline = self.fixture()
        files['agpc-apps.sh'] += b'# https://' + b'gitlab.example.invalid/private\n'
        repin(files, record)
        with self.assertRaisesRegex(ValueError, 'private source URL'):
            pub.validate_bundle(files, record, inputs, baseline)

    def test_only_required_successful_original_main_job_is_accepted(self):
        pub.check_jobs(self.record, *self.receipts())
        for index, key, value in [(0, 'status', 'running'), (0, 'ref', 'candidate'),
                                 (0, 'sha', 'a' * 40), (1, 'allow_failure', True),
                                 (1, 'name', 'unrelated'), (1, 'status', 'failed'), (1, 'tag', True), (1, 'tag', None)]:
            values = self.receipts(); values[index][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                pub.check_jobs(self.record, *values)

    def api_fixture(self):
        pipeline, job = self.receipts()
        input_path = '/repository/files/' + pub.urllib.parse.quote(pub.INPUT_PATH, safe='') + '/raw?ref=' + SOURCE
        responses = {'/repository/branches/main': encoded({'protected': True, 'commit': {'id': SOURCE}}),
                     '/pipelines/123': encoded(pipeline), '/jobs/456': encoded(job), input_path: self.inputs}
        baseline_commit = json.loads(self.inputs)['baseline_source_commit']
        responses.update({'/repository/files/' + pub.urllib.parse.quote(name, safe='') + '/raw?ref=' + baseline_commit: data
                          for name, data in self.baseline.items()})
        responses['/jobs/456/artifacts'] = self.archive
        return responses

    def test_fresh_readback_checks_main_baseline_and_all_original_files(self):
        responses = self.api_fixture(); calls = []
        def get(path):
            calls.append(path)
            return responses[path]
        with patch.object(pub, 'api_reader') as api:
            self.assertEqual(pub.fresh_producer(self.record, get), self.files)
            api.assert_not_called()
        self.assertEqual(set(calls), set(responses))

    def test_advanced_or_unprotected_source_main_refused(self):
        for protected, commit in [(False, SOURCE), (True, 'a' * 40)]:
            responses = self.api_fixture()
            responses['/repository/branches/main'] = encoded({'protected': protected, 'commit': {'id': commit}})
            with self.assertRaisesRegex(ValueError, 'advanced or is unprotected'):
                pub.fresh_producer(self.record, responses.__getitem__)

    def test_original_zip_bytes_and_closed_members_are_required(self):
        responses = self.api_fixture()
        responses['/jobs/456/artifacts'] += b'changed'
        with self.assertRaisesRegex(ValueError, 'original CI archive differs'):
            pub.fresh_producer(self.record, responses.__getitem__)
        for files in ({**self.files, '../escape': b'bad'},
                      {name: value for name, value in self.files.items() if name != 'agpc-mesh.sh'}):
            with self.assertRaises(ValueError): pub.archive_files(archive_bytes(files))
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as archive:
            info = zipfile.ZipInfo(pub.PREFIX + 'agpc-mesh.sh')
            info.external_attr = 0o120777 << 16
            archive.writestr(info, 'other-file')
        with self.assertRaisesRegex(ValueError, 'linked original archive'):
            pub.archive_files(out.getvalue())

    def test_publication_requires_exact_workflow_main_context(self):
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': pub.REPO, 'GITHUB_REF': 'refs/heads/main',
               'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_SHA': 'a' * 40,
               'GITHUB_WORKFLOW_REF': pub.REPO + '/.github/workflows/publish-agpc-core-profiles.yml@refs/heads/main'}
        with patch.dict(os.environ, env, clear=True): pub.context()
        for key, value in [('GITHUB_EVENT_NAME', 'pull_request'), ('GITHUB_REF', 'refs/heads/candidate'),
                           ('GITHUB_SHA', 'main'), ('GITHUB_WORKFLOW_REF', 'other')]:
            with self.subTest(key=key), patch.dict(os.environ, {**env, key: value}, clear=True), self.assertRaises(ValueError):
                pub.context()


if __name__ == '__main__': unittest.main()
