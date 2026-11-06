"""Core signer tests use synthetic CI receipts; no local package is a release input."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import publish_agpc_model_components as p


class CorePublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.spec = p.COMPONENTS['core']
        self.commit = 'a' * 40
        self.sources = {name: b'synthetic source\n' for name in p.CORE_SOURCES}
        published = []
        dependencies = []
        for name, version in p.CORE_ROOTS:
            if name in p.CORE_CANDIDATES:
                evidence = {'kind': 'source-candidate', 'path': p.CORE_CANDIDATES[name], 'artifact': None}
            else:
                asset = name + '_' + version + '_' + ('all' if name in ('agent-sphere', 'agpc-run') else 'amd64') + '.deb'
                published.append({'name': name, 'version': version, 'asset': asset,
                                  'sha256': 'b' * 64, 'provenance': {'source_commit': 'c' * 40}})
                evidence = {'kind': 'frozen-published-reference', 'tag': 'agent-computer-v0.3.0-85',
                            'asset': asset, 'sha256': 'b' * 64, 'source_commit': 'c' * 40}
            dependencies.append({'name': name, 'version': version,
                                 'relation': '>=' if name == 'agpc-cdp' else '=', 'evidence': evidence})
        self.sources['packaging/core/inputs/published-cohort85.json'] = p.encoded({
            'release': {'tag': 'agent-computer-v0.3.0-85', 'packages': published}})
        self.sources['packaging/core/inputs/agent-sphere.control'] = b'Package: agent-sphere\nDepends: sphered (>= 4.1.0-2)\n'
        self.sources['src/core_package_contract.py'] = (
            "PACKAGE = 'agpc-core'\nVERSION = " + repr(self.spec['version'])
            + "\nARCHITECTURE = 'amd64'\nROOT_DEPENDENCIES = " + repr(p.CORE_ROOTS)
            + "\nDEPENDENCY_RELATIONS = {'agpc-cdp': '>='}\n").encode()
        self.sources['components/agpc-manager/build.py'] = b'control = """Package: agpc-manager\nVersion: 4.4.0-3\n"""\n'
        self.sources['src/agpc_view_component.py'] = b"VERSION = '0.1.0-4'\n"
        self.sources['components/agpc-mesh/debian/changelog'] = b'agpc-mesh (3.0.0-6) unstable; urgency=medium\n'
        self.sources['components/agpc-cdp/debian/changelog'] = b'agpc-cdp (0.2.0-2) unstable; urgency=medium\n'
        self.sources['packaging/run/VERSION'] = b'0.2.0-4\n'
        self.sources['packaging/vmodel/input.json'] = p.encoded({
            'package': 'agpc-vmodel', 'version': dict(p.CORE_ROOTS)['agpc-vmodel'], 'iagent': {'version': '1.0.0-1'}})
        # Synthetic frozen source fixtures deliberately have separate test-only pins.
        self.frozen = {name: p.pin(self.sources[name]) for name in p.CORE_FROZEN_PINS}
        self.addCleanup(patch.stopall)
        patch.object(p, 'CORE_FROZEN_PINS', self.frozen).start()
        self.cohort = {'schema': 'agpc.core.package-cohort/v1', 'name': 'agpc-core',
            'version': self.spec['version'], 'architecture': 'amd64', 'kind': 'dependency-cohort',
            'installer': 'agpc-mesh.sh', 'dependencies': dependencies,
            'inherited_agent_sphere_depends': 'sphered (>= 4.1.0-2)',
            'transitive_cohort_admitted': False, **{flag: False for flag in p.CORE_FLAGS}}
        self.pipeline = {'id': 12, 'project_id': 1336, 'status': 'success', 'ref': 'main', 'sha': self.commit}
        self.job = {'id': 22, 'name': 'agpc-core-package', 'status': 'success', 'ref': 'main',
                    'tag': False, 'allow_failure': False, 'commit': {'id': self.commit}, 'pipeline': self.pipeline}
        self.producer = {'kind': 'gitlab-native-ci', 'job_id': 22, 'pipeline_id': 12,
                         'job_name': 'agpc-core-package', 'ref': 'main'}

    def build(self, extra_payload=None, extra_control=None, mode=None, empty_dir=None):
        source = {'project': 1336, 'commit': self.commit,
                  'files': {name: p.pin(raw) for name, raw in self.sources.items()}}
        payload = {'usr/share/doc/agpc-core/README': self.sources['packaging/core/README'],
                   'usr/share/agpc-core/cohort.json': p.encoded(self.cohort),
                   'usr/share/doc/agpc-core/PROVENANCE.json': p.encoded({
                       'schema': 'agpc.core.package-source/v1', 'source': source,
                       **{flag: False for flag in p.CORE_FLAGS}})}
        tree = self.root / ('tree-' + str(len(list(self.root.iterdir()))))
        tree.mkdir()
        for name, raw in {**payload, **(extra_payload or {}),
                          'DEBIAN/control': p.core_control(self.cohort), **(extra_control or {})}.items():
            target = tree / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            target.chmod(0o644)
        if empty_dir:
            (tree / empty_dir).mkdir(parents=True)
        for path in [tree, *tree.rglob('*')]:
            if path.is_dir():
                path.chmod(0o755)
        if mode:
            (tree / mode[0]).chmod(mode[1])
        path = self.root / 'package.deb'
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(tree), str(path)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deb = path.read_bytes()
        manifest = {'schema': self.spec['schema'], 'source': source, 'producer': self.producer,
                    'package': {'name': 'agpc-core', 'version': self.spec['version'], 'architecture': 'amd64',
                                'filename': p.filename(self.spec), **p.pin(deb)},
                    'cohort': self.cohort, 'checks': {name: True for name in self.spec['checks']},
                    'payload': {name: p.pin(raw) for name, raw in payload.items()},
                    **{flag: False for flag in p.CORE_FLAGS}}
        return self.seal(manifest, deb)

    def seal(self, manifest, deb):
        raw = p.encoded(manifest)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr(self.spec['prefix'] + p.filename(self.spec), deb)
            archive.writestr(self.spec['prefix'] + self.spec['manifest'], raw)
        archive = buffer.getvalue()
        record = {'schema': 'agpc.component-publication/v1', 'component': 'core',
                  'delivery_product': 'agpc-core', 'tag': self.spec['tag'],
                  'candidate_tag': 'candidate-' + self.spec['tag'], 'source_project': 1336,
                  'source_commit': self.commit, 'source_ref': 'main', 'pipeline_id': 12, 'job_id': 22,
                  'archive': p.pin(archive), 'producer_manifest': p.pin(raw),
                  'source_inventory_sha256': p.sha(p.encoded(manifest['source']['files']))}
        responses = {'/repository/branches/main': p.encoded({'protected': True, 'commit': {'id': self.commit}}),
                     '/pipelines/12': p.encoded(self.pipeline), '/jobs/22': p.encoded(self.job),
                     '/jobs/22/artifacts': archive,
                     **{'/repository/files/' + quote(name, safe='') + '/raw?ref=' + self.commit: data
                        for name, data in self.sources.items()}}
        return manifest, deb, raw, record, responses

    def fresh(self, fixture):
        _, _, _, record, responses = fixture
        return p.fresh_producer(record, self.spec, responses.__getitem__)

    def test_original_core_is_source_bound_metadata_preview(self):
        fixture = self.build()
        files = self.fresh(fixture)
        record = fixture[3]
        record['assets'] = {name: p.pin(data) for name, data in files.items()}
        p.validate_record(record, 'core')
        manifest = json.loads(files['MANIFEST.json'])
        self.assertEqual(set(files), {p.public_filename(self.spec), 'MANIFEST.json', 'SHA256SUMS'})
        self.assertEqual(manifest['cohort'], self.cohort)
        self.assertEqual(manifest['public_asset_filename'], p.public_filename(self.spec))
        self.assertEqual(manifest['package']['filename'], p.filename(self.spec))
        self.assertEqual(files[p.public_filename(self.spec)], fixture[1])
        self.assertEqual(p.archive_files(fixture[4]['/jobs/22/artifacts'], self.spec)[0], fixture[1])
        self.assertFalse(any(manifest['producer_admission'].values()))
        self.assertFalse(manifest['transitive_cohort_admitted'])
        self.assertEqual(manifest['supported_os'], [])
        self.assertNotIn('compiled_input', manifest)
        self.assertNotIn('source_composition_sha256', manifest)

    def test_core_never_requests_compiled_vmodel_job(self):
        fixture = self.build()
        requests = []
        def get(path):
            requests.append(path)
            return fixture[4][path]
        p.fresh_producer(fixture[3], self.spec, get)
        self.assertEqual([path for path in requests if path.startswith('/jobs/')], ['/jobs/22', '/jobs/22/artifacts'])
        self.assertEqual(sum(path.startswith('/repository/files/') for path in requests), 15)

    def test_local_branch_wrong_job_producers_rejected(self):
        for key, value in [('kind', 'local'), ('ref', 'branch'), ('job_name', 'vmodel-package-native'), ('job_id', 23)]:
            with self.subTest(key=key):
                old = dict(self.producer)
                self.producer[key] = value
                with self.assertRaisesRegex(ValueError, 'original main Core'):
                    self.fresh(self.build())
                self.producer = old

    def test_lifecycle_self_admission_rejected(self):
        for flag in p.CORE_FLAGS:
            fixture = self.build()
            manifest = copy.deepcopy(fixture[0]); manifest[flag] = True
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, 'cannot admit'):
                self.fresh(self.seal(manifest, fixture[1]))
        self.cohort['transitive_cohort_admitted'] = True
        with self.assertRaisesRegex(ValueError, 'cohort identity or admission'):
            self.fresh(self.build())

    def test_missing_false_or_nonboolean_checks_rejected(self):
        for value in (False, 1, None):
            fixture = self.build()
            manifest = copy.deepcopy(fixture[0]); manifest['checks']['source_binding'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'required checks'):
                self.fresh(self.seal(manifest, fixture[1]))

    def test_missing_and_extra_source_rejected_even_self_consistent(self):
        saved = dict(self.sources)
        for change in ('remove', 'add'):
            self.sources = dict(saved)
            if change == 'remove':
                self.sources.pop('packaging/core/SPEC.md')
            else:
                self.sources['unreviewed.py'] = b'new source'
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'source closure'):
                self.fresh(self.build())

    def test_frozen_source_repin_is_rejected(self):
        self.sources['packaging/core/inputs/published-cohort85.json'] += b'\n'
        with self.assertRaisesRegex(ValueError, 'frozen evidence'):
            self.fresh(self.build())

    def test_control_and_cohort_cannot_substitute_dependency(self):
        for name, version, relation in [('agpc-manager', '4.4.0-2', '='),
                                         ('agpc-cdp', '0.2.0-2', '='),
                                         ('agpc-vmodel', '0.1.0~vmodel.20261106.1', '>=')]:
            saved = copy.deepcopy(self.cohort)
            row = next(row for row in self.cohort['dependencies'] if row['name'] == name)
            row.update(version=version, relation=relation)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'exact dependency'):
                self.fresh(self.build())
            self.cohort = saved

    def test_candidate_cannot_claim_released_artifact(self):
        row = next(row for row in self.cohort['dependencies'] if row['name'] == 'agpc-view')
        row['evidence']['artifact'] = 'pretend.deb'
        with self.assertRaisesRegex(ValueError, 'candidate must not claim'):
            self.fresh(self.build())

    def test_frozen_dependency_relabel_rejected_against_source(self):
        self.cohort['dependencies'][0]['evidence']['source_commit'] = 'd' * 40
        with self.assertRaisesRegex(ValueError, 'frozen dependency source'):
            self.fresh(self.build())

    def test_source_contract_drift_cannot_relabel_package(self):
        self.sources['src/core_package_contract.py'] = self.sources['src/core_package_contract.py'].replace(b'4.4.0-3', b'4.4.0-2')
        with self.assertRaisesRegex(ValueError, 'tracked dependency contract'):
            self.fresh(self.build())

    def test_original_tracked_source_bytes_rechecked(self):
        fixture = self.build()
        fixture[4]['/repository/files/packaging%2Fcore%2FREADME/raw?ref=' + self.commit] = b'drift'
        with self.assertRaisesRegex(ValueError, 'tracked source input'):
            self.fresh(fixture)

    def test_embedded_provenance_prevents_manifest_only_relabel(self):
        fixture = self.build()
        manifest = copy.deepcopy(fixture[0])
        manifest['source']['files']['tests/test_core_package.py'] = p.pin(b'changed source\n')
        with self.assertRaisesRegex(ValueError, 'embedded provenance'):
            self.fresh(self.seal(manifest, fixture[1]))

    def test_no_extra_payload_directories_or_hooks(self):
        for options in ({'extra_payload': {'usr/bin/agpc-core': b'runtime'}},
                        {'extra_control': {'DEBIAN/triggers': b'interest anything\n'}},
                        {'extra_control': {'DEBIAN/conffiles': b'/usr/share/doc/agpc-core/README\n'}},
                        {'empty_dir': 'etc/agpc-core'},
                        {'mode': ('usr/share/doc/agpc-core/README', 0o755)}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.fresh(self.build(**options))

    def test_source_main_and_required_ci_must_remain_current(self):
        for update in ({'protected': False, 'commit': {'id': self.commit}},
                       {'protected': True, 'commit': {'id': 'd' * 40}}):
            fixture = self.build()
            fixture[4]['/repository/branches/main'] = p.encoded(update)
            with self.assertRaisesRegex(ValueError, 'main advanced or is unprotected'):
                self.fresh(fixture)
        self.job['allow_failure'] = True
        with self.assertRaisesRegex(ValueError, 'required successful'):
            self.fresh(self.build())


if __name__ == '__main__':
    unittest.main()
