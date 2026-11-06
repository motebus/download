"""Profile publication boundary tests; synthetic bytes, no network or deployment."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('view_profile_publication', ROOT / 'scripts/publish_agpc_view_profiles.py')
pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)

SOURCE = 'a' * 40
PUBLIC_SOURCE = 'b' * 40
ENVIRONMENT = {
    'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': pub.REPO, 'GITHUB_REF': 'refs/heads/main',
    'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_SHA': PUBLIC_SOURCE,
    'GITHUB_WORKFLOW_REF': pub.REPO + '/.github/workflows/publish-agpc-view-profiles.yml@refs/heads/main',
}


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def fixture():
    view = {'name': 'agpc-view', 'version': '0.1.0-1', 'architecture': 'amd64',
            'asset': pub.VIEW_PACKAGE, 'sha256': 'd' * 64,
            'provenance': {'source_commit': 'c' * 40, 'source_ref': 'refs/heads/main',
                           'main_pipeline_id': 100, 'build_status': 'success', 'public_payload_reviewed': True}}
    inputs = encoded({'schema': 'agpc-view-profile-input/v1', 'installer_tag': pub.INSTALLER_TAG,
                      'aggregate_tag': pub.AGGREGATE_TAG, 'view_release_tag': pub.VIEW_TAG,
                      'view_package': view, 'view_main_job_id': 101, 'view_gui_job_id': 102,
                      'baseline_source_commit': 'e' * 40, 'baseline_overlay_sha256': 'e' * 64,
                      'baseline_uninstaller_sha256': 'f' * 64,
                      'baseline_installer_sha256': {n: 'f' * 64 for n in ('agpc.sh', 'agpc-all.sh', 'agpc-apps.sh')}})
    files = {name: ('#!/bin/sh\n# inert fixture: ' + name + '\n').encode() for name in pub.SCRIPTS}
    files['agpc-core.sh'] = files['agpc.sh']
    packages = [{'name': f'baseline-{i}', 'version': '1.0.0-1', 'architecture': 'amd64',
                 'asset': f'baseline-{i}_1.0.0-1_amd64.deb', 'sha256': pub.sha(str(i).encode())}
                for i in range(33)]
    overlay = {'schema': 'agent-computer-apt-overlay/v12', 'release': {
        'repository': pub.REPO, 'tag': pub.AGGREGATE_TAG, 'source_commit': SOURCE,
        'packages': packages[:32] + [view], 'retention_packages': packages[32:], 'external_prerequisites': []}}
    files['agent-computer-apt-overlay.json'] = encoded(overlay)
    for name, profile in pub.PROFILES.items():
        files[name.replace('.sh', '.source.json')] = encoded({
            'schema': 'agpc-installer-source/v3', 'repository': pub.REPO, 'tag': pub.INSTALLER_TAG,
            'source_commit': SOURCE, 'asset': name, 'sha256': pub.sha(files[name]), 'profile': profile})
    files['release-manifest.json'] = encoded({
        'schema': 'agent-sphere-release/v2', 'version': pub.INSTALLER_TAG[1:],
        'source_commit': SOURCE, 'source_ref': 'refs/heads/main',
        'component_baseline': {'pending_native_components': []}, 'installer_profiles': pub.PROFILES,
        'assets': [{'name': n, 'sha256': pub.sha(files[n]), 'bytes': len(files[n])} for n in sorted(pub.SCRIPTS)],
        'aggregate_tag': pub.AGGREGATE_TAG, 'overlay_sha256': pub.sha(files['agent-computer-apt-overlay.json']),
        'view_producer': {'package_job_id': 101, 'gui_job_id': 102, 'package': view},
        'native_profile_acceptance': 'required-before-pages-deploy'})
    files['aggregate-component-release.json'] = encoded({
        'schema': 'reviewed-native-publication/v2', 'tag': pub.AGGREGATE_TAG,
        'public_source_commit': 'GITHUB_SHA', 'title': 'AGPC native cohort with View GUI',
        'notes': 'Preserves every prior native package byte and adds the source-bound View GUI. Runtime readiness remains separately verified.',
        'assets': [{'name': p['asset'], 'sha256': p['sha256'], 'source_tag': pub.BASELINE_TAG} for p in packages]
                  + [{'name': view['asset'], 'sha256': view['sha256'], 'source_tag': pub.VIEW_TAG}]})
    record = {'schema': 'agpc-view-profile.publication-inputs/v1', 'installer_tag': pub.INSTALLER_TAG,
              'aggregate_tag': pub.AGGREGATE_TAG, 'source_project': 1341, 'source_commit': SOURCE,
              'source_ref': 'main', 'pipeline_id': 123, 'job_id': 456, 'input_sha256': pub.sha(inputs), 'assets': {}}
    repin(files, record)
    return files, record, inputs


def repin(files, record):
    files['SHA256SUMS'] = ''.join(pub.sha(data) + '  ' + name + '\n'
                                for name, data in sorted(files.items()) if name != 'SHA256SUMS').encode()
    record['assets'] = {name: {'sha256': pub.sha(data), 'bytes': len(data)} for name, data in files.items()}


def update_json(files, name, change):
    data = json.loads(files[name])
    change(data)
    files[name] = encoded(data)


def refresh_overlay_pin(files):
    update_json(files, 'release-manifest.json', lambda m: m.update(overlay_sha256=pub.sha(files['agent-computer-apt-overlay.json'])))


def receipts():
    pipeline = {'id': 123, 'project_id': 1341, 'status': 'success', 'ref': 'main', 'sha': SOURCE}
    job = {'id': 456, 'name': pub.JOB_NAME, 'status': 'success', 'ref': 'main', 'allow_failure': False,
           'commit': {'id': SOURCE}, 'pipeline': copy.deepcopy(pipeline)}
    return pipeline, job


class BundleBindings(unittest.TestCase):
    def test_exact_bundle_including_view_after_retention_is_admitted(self):
        files, record, inputs = fixture()
        aggregate = pub.validate_bundle(files, record, inputs)
        self.assertEqual(len(files), 13)
        self.assertEqual(len(aggregate['assets']), 34)
        self.assertEqual(aggregate['assets'][-1]['name'], pub.VIEW_PACKAGE)

    def test_record_identity_shape_and_pins_are_closed(self):
        changes = {
            'unknown field': lambda r: r.update(extra=True),
            'old installer': lambda r: r.update(installer_tag='v0.3.0-95'),
            'old aggregate': lambda r: r.update(aggregate_tag=pub.BASELINE_TAG),
            'wrong project': lambda r: r.update(source_project=1336),
            'wrong branch': lambda r: r.update(source_ref='candidate'),
            'symbolic source': lambda r: r.update(source_commit='main'),
            'bad input hash': lambda r: r.update(input_sha256='g' * 64),
            'boolean job': lambda r: r.update(job_id=True),
            'zero pipeline': lambda r: r.update(pipeline_id=0),
            'missing file': lambda r: r['assets'].pop('agpc-core.sh'),
            'unknown pin field': lambda r: r['assets']['agpc.sh'].update(other=1),
            'oversized asset': lambda r: r['assets']['agpc.sh'].update(bytes=pub.LIMIT + 1),
            'boolean size': lambda r: r['assets']['agpc.sh'].update(bytes=True),
            'invalid digest': lambda r: r['assets']['agpc.sh'].update(sha256='0' * 63),
        }
        for label, change in changes.items():
            _, record, _ = fixture()
            change(record)
            with self.subTest(label=label), self.assertRaises(ValueError):
                pub.validate_record(record)

    def test_each_original_asset_and_committed_input_is_hash_bound(self):
        for name in sorted(pub.FILES):
            files, record, inputs = fixture()
            files[name] += b'changed'
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'CI asset differs'):
                pub.validate_bundle(files, record, inputs)
        files, record, inputs = fixture()
        with self.assertRaisesRegex(ValueError, 'bundle/input inventory differs'):
            pub.validate_bundle(files, record, inputs + b' ')

    def test_missing_extra_and_rehashed_bad_checksum_inventory_are_rejected(self):
        for change in (lambda f: f.pop('agpc-core.sh'), lambda f: f.update(extra=b'extra')):
            files, record, inputs = fixture()
            change(files)
            with self.assertRaisesRegex(ValueError, 'bundle/input inventory differs'):
                pub.validate_bundle(files, record, inputs)
        files, record, inputs = fixture()
        files['SHA256SUMS'] = b'not the inventory\n'
        record['assets']['SHA256SUMS'] = {'sha256': pub.sha(files['SHA256SUMS']), 'bytes': len(files['SHA256SUMS'])}
        with self.assertRaisesRegex(ValueError, 'checksum inventory mismatch'):
            pub.validate_bundle(files, record, inputs)

    def test_manifest_rejects_changed_source_overlay_profile_or_acceptance_claim(self):
        for key, value in [('source_commit', 'c' * 40), ('overlay_sha256', '0' * 64),
                           ('aggregate_tag', pub.BASELINE_TAG), ('installer_profiles', {}),
                           ('native_profile_acceptance', 'passed')]:
            files, record, inputs = fixture()
            update_json(files, 'release-manifest.json', lambda m: m.update({key: value}))
            repin(files, record)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'release manifest binding mismatch'):
                pub.validate_bundle(files, record, inputs)

    def test_rebound_core_still_must_be_byte_identical_to_standard(self):
        files, record, inputs = fixture()
        files['agpc-core.sh'] += b'# differs\n'
        update_json(files, 'agpc-core.source.json', lambda m: m.update(sha256=pub.sha(files['agpc-core.sh'])))
        update_json(files, 'release-manifest.json', lambda m: m.update(assets=[
            {'name': n, 'sha256': pub.sha(files[n]), 'bytes': len(files[n])} for n in sorted(pub.SCRIPTS)]))
        repin(files, record)
        with self.assertRaisesRegex(ValueError, 'Core alias differs'):
            pub.validate_bundle(files, record, inputs)

    def test_each_source_record_binds_profile_bytes_and_source_revision(self):
        for name in pub.PROFILES:
            for key, value in [('source_commit', 'c' * 40), ('sha256', '0' * 64), ('profile', 'unknown')]:
                files, record, inputs = fixture()
                update_json(files, name.replace('.sh', '.source.json'), lambda m: m.update({key: value}))
                repin(files, record)
                with self.subTest(name=name, key=key), self.assertRaisesRegex(ValueError, 'installer source binding mismatch'):
                    pub.validate_bundle(files, record, inputs)

    def test_overlay_identity_and_view_inventory_remain_bound_after_rehash(self):
        changes = [
            ('overlay source binding', lambda o: o.update(schema='agent-computer-apt-overlay/v11')),
            ('overlay source binding', lambda o: o['release'].update(source_commit='c' * 40)),
            ('aggregate package inventory', lambda o: o['release']['packages'].pop()),
            ('aggregate package inventory', lambda o: o['release']['packages'].append(copy.deepcopy(o['release']['packages'][0]))),
            ('aggregate package inventory', lambda o: o['release']['packages'][-1].update(sha256='0' * 64)),
        ]
        for error, change in changes:
            files, record, inputs = fixture()
            update_json(files, 'agent-computer-apt-overlay.json', change)
            refresh_overlay_pin(files)
            repin(files, record)
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                pub.validate_bundle(files, record, inputs)

    def test_aggregate_cannot_omit_replace_or_retarget_package_assets(self):
        changes = [lambda a: a['assets'].pop(), lambda a: a['assets'][0].update(sha256='0' * 64),
                   lambda a: a['assets'][-1].update(source_tag=pub.BASELINE_TAG),
                   lambda a: a.update(public_source_commit='c' * 40)]
        for change in changes:
            files, record, inputs = fixture()
            update_json(files, 'aggregate-component-release.json', change)
            repin(files, record)
            with self.assertRaisesRegex(ValueError, 'aggregate/overlay binding mismatch'):
                pub.validate_bundle(files, record, inputs)

    def test_unsafe_aggregate_asset_is_rejected_even_with_consistent_bindings(self):
        files, record, inputs = fixture()
        update_json(files, 'agent-computer-apt-overlay.json', lambda o: o['release']['packages'][0].update(asset='../escape.deb'))
        update_json(files, 'aggregate-component-release.json', lambda a: a['assets'][0].update(name='../escape.deb'))
        refresh_overlay_pin(files)
        repin(files, record)
        with self.assertRaisesRegex(ValueError, 'unsafe aggregate asset'):
            pub.validate_bundle(files, record, inputs)

    def test_rehashed_private_source_location_is_rejected_before_publication(self):
        files, record, inputs = fixture()
        files['agpc-apps.sh'] += b'# ' + b'https://' + b'gitlab' + b'.example.invalid/private\n'
        repin(files, record)
        with self.assertRaisesRegex(ValueError, 'private source URL'):
            pub.validate_bundle(files, record, inputs)


class ProducerIdentity(unittest.TestCase):
    def test_required_successful_producer_job_is_admitted(self):
        _, record, _ = fixture()
        pub.check_jobs(record, *receipts())

    def test_wrong_project_branch_status_or_optional_job_is_rejected(self):
        cases = [(0, 'project_id', 1336), (0, 'id', 999), (0, 'status', 'failed'),
                 (0, 'ref', 'candidate'), (0, 'sha', 'c' * 40), (1, 'id', 999),
                 (1, 'name', 'unrelated-job'), (1, 'status', 'skipped'), (1, 'ref', 'candidate'),
                 (1, 'allow_failure', True), (1, 'allow_failure', None), (1, 'commit', {'id': 'c' * 40})]
        for index, key, value in cases:
            _, record, _ = fixture()
            values = receipts()
            values[index][key] = value
            with self.subTest(index=index, key=key), self.assertRaises(ValueError):
                pub.check_jobs(record, *values)
        for key, value in [('id', 999), ('project_id', 1336), ('ref', 'candidate'), ('sha', 'c' * 40)]:
            _, record, _ = fixture()
            pipeline, job = receipts()
            job['pipeline'][key] = value
            with self.subTest(nested=key), self.assertRaises(ValueError):
                pub.check_jobs(record, pipeline, job)

    def api_fixture(self):
        files, record, inputs = fixture()
        pipeline, job = receipts()
        input_path = '/repository/files/' + pub.urllib.parse.quote(pub.INPUT_PATH, safe='') + '/raw?ref=' + SOURCE
        responses = {'/repository/branches/main': encoded({'protected': True, 'commit': {'id': SOURCE}}),
                     '/pipelines/123': encoded(pipeline), '/jobs/456': encoded(job), input_path: inputs}
        responses.update({'/jobs/456/artifacts/' + pub.PREFIX + name: data for name, data in files.items()})
        return files, record, responses, input_path

    def test_fresh_producer_reads_only_exact_committed_input_and_original_ci_files(self):
        files, record, responses, _ = self.api_fixture()
        calls = []
        def get(path):
            calls.append(path)
            return responses[path]
        with patch.object(pub, 'api_reader') as api:
            self.assertEqual(pub.fresh_producer(record, get=get), files)
            api.assert_not_called()
        self.assertEqual(set(calls), set(responses))

    def test_unprotected_or_advanced_source_main_is_rejected(self):
        for branch in ({'protected': False, 'commit': {'id': SOURCE}},
                       {'protected': True, 'commit': {'id': 'c' * 40}}, {'commit': {'id': SOURCE}}):
            _, record, responses, _ = self.api_fixture()
            responses['/repository/branches/main'] = encoded(branch)
            with self.subTest(branch=branch), self.assertRaisesRegex(ValueError, 'advanced or is unprotected'):
                pub.fresh_producer(record, get=responses.__getitem__)

    def test_original_ci_artifact_or_committed_input_drift_is_rejected(self):
        _, record, responses, input_path = self.api_fixture()
        for path, error in [(input_path, 'committed producer inputs differ'),
                            ('/jobs/456/artifacts/' + pub.PREFIX + 'agpc-core.sh', 'CI asset differs')]:
            changed = dict(responses)
            changed[path] += b' changed'
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, error):
                pub.fresh_producer(record, get=changed.__getitem__)


class ImmutablePublication(unittest.TestCase):
    def test_exact_dispatch_context_is_required(self):
        with patch.dict(os.environ, ENVIRONMENT, clear=True):
            pub.context()
        for key in ENVIRONMENT:
            with self.subTest(key=key), patch.dict(os.environ, {**ENVIRONMENT, key: 'wrong'}, clear=True), \
                    self.assertRaises(ValueError):
                pub.context()

    def test_wrong_context_fails_before_producer_or_external_commands(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(pub, 'run') as run, \
                patch.object(pub, 'fresh_producer') as producer, self.assertRaisesRegex(ValueError, 'publisher context'):
            pub.publish('installer')
        run.assert_not_called()
        producer.assert_not_called()

    def test_advanced_public_main_is_rejected(self):
        with patch.dict(os.environ, ENVIRONMENT, clear=True), \
                patch.object(pub, 'run', return_value=json.dumps({'commit': {'sha': 'c' * 40}})), \
                self.assertRaisesRegex(ValueError, 'publisher main advanced'):
            pub.fresh_public_main()

    def test_release_or_tag_must_be_definitely_absent(self):
        missing = subprocess.CompletedProcess([], 1, '', 'HTTP 404')
        for first, second in [(subprocess.CompletedProcess([], 0, '{}', ''), missing),
                              (subprocess.CompletedProcess([], 1, '', 'HTTP 403'), missing),
                              (missing, subprocess.CompletedProcess([], 0, '{}', '')),
                              (missing, subprocess.CompletedProcess([], 1, '', 'network failed'))]:
            with patch.object(pub.subprocess, 'run', side_effect=[first, second]), self.assertRaises(ValueError):
                pub.absent_release(pub.INSTALLER_TAG)
        with patch.object(pub.subprocess, 'run', side_effect=[missing, missing]) as run:
            pub.absent_release(pub.AGGREGATE_TAG)
        self.assertIn('/releases/tags/' + pub.AGGREGATE_TAG, run.call_args_list[0].args[0][-1])
        self.assertIn('/git/ref/tags/' + pub.AGGREGATE_TAG, run.call_args_list[1].args[0][-1])

    def test_existing_counterpart_requires_exact_nondraft_inventory_and_hash_readback(self):
        pins = {'one.deb': 'a' * 64, 'two.deb': 'b' * 64}
        info = {'tag_name': pub.AGGREGATE_TAG, 'draft': False, 'assets': [{'name': n} for n in pins]}
        with patch.object(pub, 'release_info', return_value=info), patch.object(pub, 'download_asset') as download, \
                patch.object(pub, 'absent_release') as absent, contextlib.redirect_stdout(io.StringIO()):
            pub.verify_counterpart(pub.AGGREGATE_TAG, pins)
        absent.assert_not_called()
        self.assertEqual([(c.args[0], c.args[1], c.args[2]) for c in download.call_args_list],
                         [(pub.AGGREGATE_TAG, n, h) for n, h in sorted(pins.items())])
        for change in (lambda i: i.update(draft=True), lambda i: i.update(tag_name='other'),
                       lambda i: i['assets'].pop(), lambda i: i['assets'].append({'name': 'extra.deb'}),
                       lambda i: i['assets'][0].update(name='two.deb')):
            changed = copy.deepcopy(info)
            change(changed)
            with patch.object(pub, 'release_info', return_value=changed), patch.object(pub, 'download_asset') as download, \
                    self.assertRaisesRegex(ValueError, 'unexpected assets'):
                pub.verify_counterpart(pub.AGGREGATE_TAG, pins)
            download.assert_not_called()

    def test_missing_counterpart_checks_tag_absence_and_never_repairs_existing_bytes(self):
        with patch.object(pub, 'release_info', return_value=None), patch.object(pub, 'absent_release') as absent:
            pub.verify_counterpart(pub.INSTALLER_TAG, {})
            absent.assert_called_once_with(pub.INSTALLER_TAG)
        info = {'tag_name': pub.INSTALLER_TAG, 'draft': False, 'assets': [{'name': 'agpc.sh'}]}
        with patch.object(pub, 'release_info', return_value=info), \
                patch.object(pub, 'download_asset', side_effect=ValueError('released asset differs')), \
                self.assertRaisesRegex(ValueError, 'released asset differs'):
            pub.verify_counterpart(pub.INSTALLER_TAG, {'agpc.sh': 'a' * 64})

    def test_download_readback_rejects_changed_bytes_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            path = stage / 'fixture.deb'
            data = b'exact released bytes'
            path.write_bytes(data)
            with patch.object(pub, 'run'):
                pub.download_asset(pub.VIEW_TAG, path.name, pub.sha(data), stage)
                path.write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError, 'released asset differs'):
                    pub.download_asset(pub.VIEW_TAG, path.name, pub.sha(data), stage)
                path.unlink()
                target = stage / 'target'
                target.write_bytes(data)
                path.symlink_to(target)
                with self.assertRaisesRegex(ValueError, 'released asset differs'):
                    pub.download_asset(pub.VIEW_TAG, path.name, pub.sha(data), stage)


class Preparation(unittest.TestCase):
    def test_prepare_emits_only_a_bound_review_record_and_refuses_overwrite(self):
        files, record, inputs = fixture()
        pipeline, job = receipts()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / 'bundle'
            bundle.mkdir()
            for name, data in files.items():
                (bundle / name).write_bytes(data)
            args = SimpleNamespace(bundle=bundle, pipeline=root / 'pipeline.json', job=root / 'job.json',
                                   inputs=root / 'inputs.json', record_output=root / 'record.json')
            args.pipeline.write_bytes(encoded(pipeline))
            args.job.write_bytes(encoded(job))
            args.inputs.write_bytes(inputs)
            before = {p.name: p.read_bytes() for p in bundle.iterdir()}
            with patch.object(pub, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
                pub.prepare(args)
            run.assert_not_called()
            self.assertEqual(json.loads(args.record_output.read_bytes()), record)
            self.assertEqual({p.name: p.read_bytes() for p in bundle.iterdir()}, before)
            with self.assertRaisesRegex(ValueError, 'record already exists'):
                pub.prepare(args)


if __name__ == '__main__':
    unittest.main()
