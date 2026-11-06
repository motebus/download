import copy
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import publish_agpc_model_components as p


class PublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory()
        cls.root = Path(cls.work.name)
        cls.fixtures = {name: cls.fixture(name) for name in p.COMPONENTS}

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    @classmethod
    def fixture(cls, component):
        spec = p.COMPONENTS[component]
        root = cls.root / component
        control = root / 'DEBIAN'; control.mkdir(parents=True)
        (control / 'control').write_text('Package: ' + spec['package'] + '\nVersion: ' + spec['version']
            + '\nArchitecture: amd64\nMaintainer: Test <test@example.invalid>\nDescription: test\n')
        (control / 'control').chmod(0o644)
        if component == 'vmodel':
            paths = {'usr/bin/vmodel': b'original native executable',
                     'usr/share/doc/agpc-vmodel/consumer-contract.json': b'{}',
                     'usr/share/doc/agpc-vmodel/provenance.json': b'{}'}
        else:
            paths = {'usr/bin/model-llm': b'original Provider executable',
                     'lib/systemd/system/model-llm.service': b'[Service]\n',
                     'usr/share/model-llm/model-llm.toml.example': b'[provider]\n',
                     **{'usr/share/doc/model-llm/' + name: b'fixture\n'
                        for name in ('README.md', 'SPEC.md', 'copyright', 'provider-provenance.json')}}
            (control / 'md5sums').write_text('\n')
            for name in ('preinst', 'postinst', 'prerm', 'postrm'):
                (control / name).write_text('#!/bin/sh\nexit 0\n')
                (control / name).chmod(0o755)
        for name, data in paths.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o755 if name.startswith('usr/bin/') else 0o644)
        for target in [root, *root.rglob('*')]:
            if target.is_dir():
                target.chmod(0o755)
        output = cls.root / (component + '.deb')
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(root), str(output)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deb = output.read_bytes()
        commit = 'a' * 40
        pipeline = {'id': 12, 'project_id': spec['project'], 'status': 'success', 'ref': 'main', 'sha': commit}
        job = {'id': 22, 'name': spec['job'], 'status': 'success', 'ref': 'main', 'tag': False,
               'allow_failure': False, 'commit': {'id': commit}, 'pipeline': pipeline}
        files = {'packaging/recipe.py': p.pin(b'approved source\n')}
        manifest = {'schema': spec['schema'], 'delivery_product': spec['product'],
                    'build_kind': 'gitlab-native-ci',
                    'source': {'project': spec['project'], 'commit': commit, 'ref': 'main', 'dirty': False,
                               'files': files},
                    'producer': ({'pipeline_id': 12, 'job_id': 22, 'name': spec['job']} if component == 'vmodel'
                                 else {'pipeline_id': '12', 'job_id': '22', 'job_name': spec['job']}),
                    'package': {'name': spec['package'], 'version': spec['version'], 'architecture': 'amd64',
                                'filename': p.filename(spec), **p.pin(deb)},
                    'checks': [{'name': name, 'exit': 0,
                                **({'container': False, 'unprivileged': True}
                                   if name == 'native-environment' else {})}
                               for name in sorted(spec['checks'])],
                    **{name: False for name in p.FLAGS}, 'supported_os': []}
        responses = {'/repository/branches/main': p.encoded({'protected': True, 'commit': {'id': commit}}),
                     '/pipelines/12': p.encoded(pipeline), '/jobs/22': p.encoded(job),
                     '/repository/files/packaging%2Frecipe.py/raw?ref=' + commit: b'approved source\n'}
        if component == 'vmodel':
            old = 'b' * 40
            files['native/vmodel/src/main.rs'] = p.pin(b'original source\n')
            responses['/repository/files/native%2Fvmodel%2Fsrc%2Fmain.rs/raw?ref=' + commit] = b'original source\n'
            native_manifest = {'schema': 'agpc.core.vmodel-artifact/v1', 'candidate': spec['version'],
                               'source': {'project': 1336, 'commit': old,
                                          'files': {'native/vmodel/src/main.rs': p.pin(b'original source\n')}},
                               'producer': {'CI_JOB_ID': '21', 'CI_PIPELINE_ID': '11', 'ref': 'main'},
                               'artifacts': {'vmodel': p.pin(paths['usr/bin/vmodel'])}}
            native_raw = p.encoded(native_manifest)
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, 'w') as archive:
                archive.writestr('native/vmodel/dist/MANIFEST.json', native_raw)
                archive.writestr('native/vmodel/dist/vmodel', paths['usr/bin/vmodel'])
            compiled_archive = raw.getvalue()
            manifest['compiled_input'] = {'schema': 'agpc.core.vmodel-package-input/v1',
                'source_commit': old, 'pipeline': '11', 'job': '21', 'owner': 'agpc-core',
                'package': 'agpc-vmodel', 'version': spec['version'], 'architecture': 'amd64',
                'archive_bytes': len(compiled_archive), 'archive_sha256': p.sha(compiled_archive),
                'manifest_sha256': p.sha(native_raw), 'vmodel_sha256': p.sha(paths['usr/bin/vmodel']),
                'library_sha256': 'e' * 64, **{k: False for k in
                    ('release_admitted', 'native_install_accepted', 'abi_acceptance', 'runtime_ready')}}
            build_receipt = p.encoded({'schema': 'agpc.core.vmodel-nonrelease-build/v1',
                'compiled_input': manifest['compiled_input'], 'filename': p.filename(spec), **p.pin(deb),
                **{k: False for k in (*p.FLAGS, 'payload_executed', 'maintainer_scripts_executed')},
                'supported_os': [], 'commands': [
                    {'command': ['/usr/bin/dpkg', '--print-architecture'], 'exit': 0},
                    {'command': ['/usr/bin/perl', '/private/tools/dpkg-shlibdeps', '-O'], 'exit': 0},
                    {'command': ['/usr/bin/dpkg-deb', '--build', 'root', 'package'], 'exit': 0}]})
            package_plan = p.encoded({'schema': 'test.package-plan/v1'})
            manifest['records'] = {p.filename(spec): p.pin(deb),
                'BUILD-RECEIPT.json': p.pin(build_receipt), 'PACKAGE-PLAN.json': p.pin(package_plan)}
            manifest['payload_executed'] = False
            native_pipeline = {**pipeline, 'id': 11, 'sha': old}
            native_job = {**job, 'id': 21, 'name': 'vmodel-native', 'commit': {'id': old},
                          'pipeline': native_pipeline}
            responses.update({'/pipelines/11': p.encoded(native_pipeline), '/jobs/21': p.encoded(native_job),
                '/jobs/21/artifacts': compiled_archive,
                '/repository/files/native%2Fvmodel%2Fsrc%2Fmain.rs/raw?ref=' + old: b'original source\n',
                '/repository/files/native%2Fvmodel%2Fsrc%2Fmain.rs/raw?ref=' + commit: b'original source\n'})
        else:
            manifest['source_composition'] = {
                'frozen': {'project': 1317, 'commit': 'cb579c409e2f0f29b7511976d0fc27d0238c1a1d'},
                'overlay': {'project': 1336, 'commit': 'c' * 40}, 'origin_sha256': 'd' * 64}
            manifest['native_shlibs'] = {'libc6': '2.34', 'libgcc-s1': '4.2'}
            provenance = {'schema': 'agpc.model.payload-provenance/v1', 'delivery_product': spec['product'],
                **{key: manifest[key] for key in ('source', 'producer', 'source_composition', 'native_shlibs')},
                'binary_sha256': p.sha(paths['usr/bin/model-llm']), **{key: False for key in p.FLAGS[:4]}}
            (root / 'usr/share/doc/model-llm/provider-provenance.json').write_bytes(p.encoded(provenance))
            subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(root), str(output)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deb = output.read_bytes()
            manifest['package'].update(p.pin(deb))
        raw = p.encoded(manifest)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as archive:
            archive.writestr(spec['prefix'] + p.filename(spec), deb)
            archive.writestr(spec['prefix'] + spec['manifest'], raw)
            if component == 'vmodel':
                archive.writestr(spec['prefix'] + 'BUILD-RECEIPT.json', build_receipt)
                archive.writestr(spec['prefix'] + 'PACKAGE-PLAN.json', package_plan)
        archive = buf.getvalue()
        record = {'schema': 'agpc.component-publication/v1', 'component': component,
                  'delivery_product': spec['product'], 'tag': spec['tag'], 'candidate_tag': 'candidate-' + spec['tag'],
                  'source_project': spec['project'], 'source_commit': commit, 'source_ref': 'main',
                  'pipeline_id': 12, 'job_id': 22, 'archive': p.pin(archive),
                  'producer_manifest': p.pin(raw), 'source_inventory_sha256': p.sha(p.encoded(files))}
        bundle = p.public_bundle(raw, deb, record, spec)
        record['assets'] = {name: p.pin(data) for name, data in bundle.items()}
        responses['/jobs/22/artifacts'] = archive
        return dict(spec=spec, deb=deb, raw=raw, manifest=manifest, record=record,
                    pipeline=pipeline, job=job, archive=archive, responses=responses, bundle=bundle)

    def setUp(self):
        self.f = copy.deepcopy(self.fixtures['vmodel'])

    def changed_manifest(self, mutate):
        mutate(self.f['manifest'])
        raw = p.encoded(self.f['manifest'])
        self.f['record']['producer_manifest'] = p.pin(raw)
        return p.validate_producer(raw, self.f['deb'], self.f['record'], self.f['spec'])

    def test_valid_both_original_main_bundles(self):
        for component, fixture in self.fixtures.items():
            with self.subTest(component=component):
                p.validate_record(fixture['record'], component)
                actual = p.fresh_producer(fixture['record'], fixture['spec'], fixture['responses'].__getitem__)
                self.assertEqual(actual, fixture['bundle'])
                meta = json.loads(actual['MANIFEST.json'])
                self.assertFalse(any(meta['producer_admission'].values()))
                self.assertEqual(meta['supported_os'], [])

    def test_public_filename_mapping_preserves_original_package_and_archive(self):
        for component, fixture in self.fixtures.items():
            spec = fixture['spec']
            name = p.public_filename(spec)
            self.assertNotIn('~', name)
            self.assertNotEqual(name, p.filename(spec))
            self.assertEqual(fixture['bundle'][name], fixture['deb'])
            manifest = json.loads(fixture['bundle']['MANIFEST.json'])
            self.assertEqual(manifest['public_asset_filename'], name)
            self.assertEqual(manifest['package']['filename'], p.filename(spec))
            self.assertEqual(manifest['package']['version'], spec['version'])
            self.assertEqual(p.archive_files(fixture['archive'], spec)[0], fixture['deb'])
            record = copy.deepcopy(fixture['record'])
            record['assets'][p.filename(spec)] = record['assets'].pop(name)
            with self.assertRaisesRegex(ValueError, 'public asset inventory'):
                p.validate_record(record, component)
        for value in ('', '../package.deb', p.filename(self.f['spec']), 'other.deb'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'public asset filename'):
                p.public_filename(dict(self.f['spec'], public_asset_filename=value))

    def test_consumer_keeps_independent_original_main_build_identity(self):
        self.assertNotEqual(self.f['manifest']['compiled_input']['source_commit'],
                            self.f['record']['source_commit'])
        p.fresh_producer(self.f['record'], self.f['spec'], self.f['responses'].__getitem__)

    def test_record_cannot_change_product_project_or_add_override(self):
        for key, value in [('source_project', 1317), ('delivery_product', 'agpc-model'),
                           ('source_ref', 'branch'), ('tag', 'arbitrary'), ('override', True)]:
            record = copy.deepcopy(self.f['record']); record[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                p.validate_record(record, 'vmodel')

    def test_branch_tag_optional_or_failed_job_refused(self):
        for key, value in [('ref', 'branch'), ('tag', True), ('allow_failure', True), ('status', 'failed')]:
            job = copy.deepcopy(self.f['job']); job[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                p.check_jobs(self.f['record'], self.f['pipeline'], job, self.f['spec'])

    def test_false_or_local_producer_cannot_be_relabelled(self):
        for mutate in [lambda m: m.update(build_kind='local-candidate'),
                       lambda m: m['source'].update(dirty=True),
                       lambda m: m['source'].update(ref='branch')]:
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.changed_manifest(mutate)
            self.f = copy.deepcopy(self.fixtures['vmodel'])

    def test_preview_does_not_admit_runtime(self):
        for flag in p.FLAGS:
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                self.changed_manifest(lambda m: m.update({flag: True}))
            self.f = copy.deepcopy(self.fixtures['vmodel'])

    def test_failed_or_missing_checks_refused(self):
        with self.assertRaises(ValueError):
            self.changed_manifest(lambda m: m['checks'][0].update(exit=1))
        self.f = copy.deepcopy(self.fixtures['vmodel'])
        with self.assertRaises(ValueError):
            self.changed_manifest(lambda m: m.update(checks=[]))

    def test_original_archive_corruption_refused(self):
        self.f['responses']['/jobs/22/artifacts'] += b'x'
        with self.assertRaisesRegex(ValueError, 'archive differs'):
            p.fresh_producer(self.f['record'], self.f['spec'], self.f['responses'].__getitem__)

    def test_source_main_must_stay_protected_and_current(self):
        for branch in [{'protected': False, 'commit': {'id': 'a' * 40}},
                       {'protected': True, 'commit': {'id': 'f' * 40}}]:
            self.f['responses']['/repository/branches/main'] = p.encoded(branch)
            with self.subTest(branch=branch), self.assertRaises(ValueError):
                p.fresh_producer(self.f['record'], self.f['spec'], self.f['responses'].__getitem__)

    def test_tracked_source_bytes_checked_independently(self):
        self.f['responses']['/repository/files/packaging%2Frecipe.py/raw?ref=' + 'a' * 40] = b'drift'
        with self.assertRaisesRegex(ValueError, 'tracked source'):
            p.fresh_producer(self.f['record'], self.f['spec'], self.f['responses'].__getitem__)

    def test_original_compiled_source_bytes_checked_independently(self):
        self.f['responses']['/repository/files/native%2Fvmodel%2Fsrc%2Fmain.rs/raw?ref=' + 'b' * 40] = b'drift'
        with self.assertRaisesRegex(ValueError, 'original compiled source'):
            p.fresh_producer(self.f['record'], self.f['spec'], self.f['responses'].__getitem__)

    def test_compiled_branch_pipeline_cannot_become_main(self):
        pipeline = json.loads(self.f['responses']['/pipelines/11']); pipeline['ref'] = 'branch'
        self.f['responses']['/pipelines/11'] = p.encoded(pipeline)
        with self.assertRaisesRegex(ValueError, 'main pipeline'):
            p.fresh_producer(self.f['record'], self.f['spec'], self.f['responses'].__getitem__)

    def test_runtime_source_change_at_packaging_main_refused(self):
        self.f['responses']['/repository/files/native%2Fvmodel%2Fsrc%2Fmain.rs/raw?ref=' + 'a' * 40] = b'drift'
        with self.assertRaisesRegex(ValueError, 'tracked source input differs|runtime input differs'):
            p.fresh_producer(self.f['record'], self.f['spec'], self.f['responses'].__getitem__)

    def test_package_receipt_pin_checks_actual_original_bytes(self):
        manifest = copy.deepcopy(self.f['manifest'])
        manifest['records']['BUILD-RECEIPT.json'] = p.pin(b'changed')
        with self.assertRaisesRegex(ValueError, 'package receipt differs'):
            p.verify_packaging_receipts(self.f['archive'], manifest, self.f['spec'])

    def test_new_runtime_file_at_packaging_main_refused(self):
        self.f['manifest']['source']['files']['native/vmodel/src/extra.rs'] = p.pin(b'extra')
        self.f['record']['source_inventory_sha256'] = p.sha(p.encoded(self.f['manifest']['source']['files']))
        raw = p.encoded(self.f['manifest'])
        self.f['record']['producer_manifest'] = p.pin(raw)
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(self.f['archive'])) as original, zipfile.ZipFile(buf, 'w') as archive:
            for item in original.infolist():
                archive.writestr(item, raw if item.filename.endswith('PUBLICATION-MANIFEST.json')
                                 else original.read(item))
        self.f['responses']['/jobs/22/artifacts'] = buf.getvalue()
        self.f['record']['archive'] = p.pin(buf.getvalue())
        self.f['responses']['/repository/files/native%2Fvmodel%2Fsrc%2Fextra.rs/raw?ref=' + 'a' * 40] = b'extra'
        with self.assertRaisesRegex(ValueError, 'runtime inventory differs'):
            p.fresh_producer(self.f['record'], self.f['spec'], self.f['responses'].__getitem__)

    def test_zip_unsafe_and_symlink_members_refused(self):
        for name, mode in [('../outside', 0o100644), ('link', stat.S_IFLNK | 0o777)]:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w') as archive:
                info = zipfile.ZipInfo(name); info.external_attr = mode << 16
                archive.writestr(info, b'payload')
            with self.subTest(name=name), self.assertRaises(ValueError):
                p.archive_files(buf.getvalue(), self.f['spec'])

    def test_missing_deb_and_placeholder_record_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as archive:
            archive.writestr('build-evidence/log', b'no package')
        with self.assertRaisesRegex(ValueError, 'package/manifest missing'):
            p.archive_files(buf.getvalue(), self.f['spec'])
        self.f['record']['job_id'] = None
        with self.assertRaises(ValueError):
            p.validate_record(self.f['record'], 'vmodel')

    def test_package_identity_swap_refused(self):
        other = self.fixtures['model']['deb']
        self.f['manifest']['package'].update(p.pin(other))
        raw = p.encoded(self.f['manifest']); self.f['record']['producer_manifest'] = p.pin(raw)
        with self.assertRaises(ValueError):
            p.validate_producer(raw, other, self.f['record'], self.f['spec'])

    def test_source_inventory_escape_refused(self):
        self.f['manifest']['source']['files'] = {'../secret': p.pin(b'private')}
        self.f['record']['source_inventory_sha256'] = p.sha(p.encoded(self.f['manifest']['source']['files']))
        with self.assertRaises(ValueError):
            self.changed_manifest(lambda m: None)

    def test_no_unreviewed_dispatch_context(self):
        with patch.dict(p.os.environ, {}, clear=True), self.assertRaises(ValueError):
            p.context()

    def test_json_duplicate_fields_refused(self):
        with self.assertRaises(ValueError):
            p.json_bytes(b'{"schema":"real","schema":"fake"}')

    def test_provider_container_or_privileged_build_refused(self):
        for name, value in [('container', True), ('unprivileged', False)]:
            self.f = copy.deepcopy(self.fixtures['model'])
            environment = next(c for c in self.f['manifest']['checks'] if c['name'] == 'native-environment')
            environment[name] = value
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'native build environment'):
                self.changed_manifest(lambda m: None)

    def test_provider_internal_provenance_cannot_be_relabelled(self):
        self.f = copy.deepcopy(self.fixtures['model'])
        self.f['record']['pipeline_id'] = 13
        with self.assertRaisesRegex(ValueError, 'payload provenance differs'):
            self.changed_manifest(lambda m: m['producer'].update(pipeline_id='13'))

    def test_source_api_origin_and_redirect_refused(self):
        origin = 'https://' + 'gitlab.ypcloud.com'
        for value in (origin + '/wrong.git', origin + '/codex/codex-agpc/agpc-download-source.git?token=x',
                      'https://example.invalid/codex/codex-agpc/agpc-download-source.git'):
            with self.subTest(value=value), patch.dict(p.os.environ, {'AGPC_GITLAB_SOURCE_URL': value}), \
                    self.assertRaisesRegex(ValueError, 'source API origin'):
                p.api_reader(self.f['spec'])
        request = p.urllib.request.Request(origin + '/api/v4/projects/1336', headers={'PRIVATE-TOKEN': 'fixture'})
        with self.assertRaisesRegex(ValueError, 'cross-origin'):
            p.SameOriginRedirect().redirect_request(request, None, 302, '', {}, 'https://example.invalid/')

    def publication_probe(self, failure_on_refresh):
        root = self.root / ('publish-test-' + str(failure_on_refresh))
        records = root / 'scripts/component-publications'
        records.mkdir(parents=True, exist_ok=True)
        raw = p.encoded(self.f['record'])
        (records / 'vmodel.json').write_bytes(raw)
        (root / 'medge-archive-keyring.fingerprint').write_text(p.FINGERPRINT)
        calls, signed = [], []
        def command(*args, **kwargs):
            calls.append(args)
            if args[:3] == ('gh', 'release', 'download'):
                name = args[args.index('--pattern') + 1]
                target = Path(args[args.index('--dir') + 1]) / name
                target.write_bytes(self.f['bundle'][name])
            return ''
        def signer(*args):
            signed.append(True)
        responses = ([self.f['bundle'], ValueError('producer drift')] if failure_on_refresh
                     else [ValueError('original branch is not main')])
        modules = {'publish_native': types.SimpleNamespace(sign_files=signer),
                   'publish_apt': types.SimpleNamespace(validate_no_gitlab_urls=lambda path: None)}
        with patch.object(p, 'ROOT', root), patch.object(p, 'context'), \
                patch.object(p.subprocess, 'check_output', return_value=raw), \
                patch.object(p, 'fresh_producer', side_effect=responses), \
                patch.object(p, 'current_public_main'), patch.object(p, 'absent_release'), \
                patch.object(p, 'run', side_effect=command), \
                patch.dict(sys.modules, modules), \
                patch.dict(p.os.environ, {'GITHUB_SHA': 'e' * 40, 'MEDGE_APT_SIGNING_KEY': 'test-key'}):
            with self.assertRaises(ValueError):
                p.publish('vmodel')
        self.assertFalse(any(args[:3] == ('gh', 'release', 'create') for args in calls))
        self.assertEqual(bool(signed), failure_on_refresh)

    def test_rejected_source_never_reaches_signer_or_release_creation(self):
        self.publication_probe(False)

    def test_producer_drift_after_signing_prevents_release_creation(self):
        self.publication_probe(True)


if __name__ == '__main__':
    unittest.main()
