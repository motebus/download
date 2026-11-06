"""Core is a real closed composition; entry renaming cannot admit a missing cohort."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import agpc_core_package as core
import agpc_profiles
import publish_apt as apt
import publish_component
import publish_native as native
import validate_agent_sphere_apt as solver
import test_agpc_native_publication_v8 as publication_tests

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'tests/fixtures/agpc-core-v96-baseline'


def config_fixture():
    config = json.loads((BASELINE / apt.AGENT_COMPUTER_OVERLAY_FILE).read_text())
    config['schema'] = apt.AGENT_COMPUTER_CORE_SCHEMA
    config['release']['tag'] = 'agent-computer-v9.9.9-100'
    approved = {p['name']: p for p in config['release']['packages']}
    for name, version in {**apt.AGPC_CORE_DEPENDENCIES, 'agpc-core': apt.AGPC_CORE_VERSION}.items():
        if name not in approved:
            approved[name] = {'name': name, 'architecture': 'amd64', 'sha256': 'a' * 64,
                              'provenance': copy.deepcopy(approved['agent-sphere']['provenance'])}
        approved[name]['version'] = version
        approved[name]['asset'] = apt.overlay_asset_name(name, version, approved[name]['architecture'], config['schema'])
    config['release']['packages'] = [approved[name] for name in apt.canonical_packages(config)]
    return config


class CoreContractTests(unittest.TestCase):
    def test_frozen_baseline_retains_original_bytes_modes_and_release(self):
        receipt = json.loads((BASELINE / 'FIXTURE.json').read_text())
        self.assertEqual(receipt['source_commit'], '1c4e1876ae560dce78bb4031f386544ad7f247b9')
        for name, record in receipt['files'].items():
            path = BASELINE / name
            with self.subTest(name=name):
                self.assertEqual(apt.sha256(path), record['sha256'])
                self.assertEqual(path.stat().st_size, record['bytes'])
                self.assertEqual(path.stat().st_mode & 0o777, int(record['mode'], 8) & 0o777)
        source = apt.validate_agent_apps_installer(BASELINE)
        config = apt.load_agent_computer_overlay(BASELINE)
        self.assertEqual((source['schema'], source['tag']), ('agpc-installer-source/v3', 'v0.3.0-96'))
        self.assertEqual((config['schema'], config['release']['tag']),
                         ('agent-computer-apt-overlay/v12', 'agent-computer-v0.3.0-85'))

    def test_exact_candidates_are_scoped_to_v13_and_complete_roots(self):
        config = config_fixture()
        apt.validate_full_overlay_config(config['release'], schema=config['schema'])
        for name in ('agpc-core', 'agpc-vmodel', 'agpc-manager'):
            bad = copy.deepcopy(config)
            item = next(p for p in bad['release']['packages'] if p['name'] == name)
            item['version'] += '~unreviewed'; item['asset'] = f"{name}_{item['version']}_{item['architecture']}.deb"
            with self.subTest(name=name), self.assertRaises(apt.PublishError):
                apt.validate_full_overlay_config(bad['release'], schema=bad['schema'])
        with self.assertRaises(apt.PublishError):
            apt.validate_full_overlay_config(config['release'], schema=apt.AGENT_COMPUTER_VIEW_SCHEMA)
        bad = copy.deepcopy(config); bad['release']['packages'].pop()
        with self.assertRaises(apt.PublishError):
            apt.validate_full_overlay_config(bad['release'], schema=bad['schema'])

    def test_only_core_composition_can_depend_on_ui_and_no_cycle(self):
        config = config_fixture()
        graph = {name: set() for name in apt.canonical_packages(config)}
        graph['agpc-core'] = set(apt.AGPC_CORE_DEPENDENCIES)
        apt.validate_dependency_graph(graph, config)
        for owner, edge in [('agent-sphere', 'agpc-manager'), ('agpc-vmodel', 'agpc-view'),
                            ('agpc-manager', 'agpc-core')]:
            changed = copy.deepcopy(graph); changed[owner].add(edge)
            with self.subTest(owner=owner), self.assertRaises(apt.PublishError):
                apt.validate_dependency_graph(changed, config)
        changed = copy.deepcopy(graph); changed['agpc-core'].remove('iagent')
        with self.assertRaises(apt.PublishError): apt.validate_dependency_graph(changed, config)

    def test_solver_requires_core_consumer_and_iagent_without_provider_upgrade(self):
        config = config_fixture()
        versions = {p['name']: p['version'] for p in config['release']['packages']}
        names = set(apt.core_components(config)) | {'agent-sphere'} | set(apt.installer_extra_roots(config))
        output = ''.join(f'Inst {name} ({versions[name]} fixture)\n' for name in sorted(names))
        solver.validate_plan(output, {'packages': []}, config)
        for missing in ('agpc-core', 'agpc-vmodel', 'iagent', 'agpc-manager', 'medge'):
            with self.subTest(missing=missing), self.assertRaises(apt.PublishError):
                solver.validate_plan('\n'.join(line for line in output.splitlines()
                                              if not line.startswith('Inst ' + missing + ' ')), {'packages': []}, config)
        self.assertIn('install agpc-core=' + apt.AGPC_CORE_VERSION + ' medge=3.3.0-2\n', solver.profile_simulation(config))
        self.assertIn('agpc-core=' + apt.AGPC_CORE_VERSION, solver.profile_simulation(config, full=True))
        self.assertEqual(versions['model-llm'], '0.1.0-3')

    def test_public_asset_mapping_preserves_original_versions_and_rejects_tildes(self):
        record = {'schema': 'reviewed-native-publication/v2', 'tag': 'agent-computer-v9.9.9-100',
                  'public_source_commit': 'GITHUB_SHA', 'title': 'Test', 'notes': 'Fixture',
                  'assets': [{'name': apt.overlay_asset_name('agpc-core', apt.AGPC_CORE_VERSION, 'amd64', apt.AGENT_COMPUTER_CORE_SCHEMA),
                              'sha256': 'a' * 64, 'source_tag': 'agpc-core-v0.1.0-core.20261106.1'}]}
        publish_component.validate(record, record['tag'])
        self.assertEqual(record['assets'][0]['name'], 'agpc-core_0.1.0.core.20261106.1_amd64.deb')
        config = config_fixture()
        core_record = next(p for p in config['release']['packages'] if p['name'] == 'agpc-core')
        self.assertEqual(core_record['version'], apt.AGPC_CORE_VERSION)
        core_record['asset'] = 'agpc-core_' + apt.AGPC_CORE_VERSION + '_amd64.deb'
        with self.assertRaisesRegex(apt.PublishError, 'asset'):
            apt.validate_full_overlay_config(config['release'], schema=config['schema'])
        for name in ('agpc-core_' + apt.AGPC_CORE_VERSION + '_amd64.deb', 'agpc-core_0.1.0~unreviewed_amd64.deb', 'other_1.0~preview_amd64.deb'):
            changed = copy.deepcopy(record); changed['assets'][0]['name'] = name
            with self.assertRaises(AssertionError): publish_component.validate(changed, changed['tag'])


class MeshEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        names = agpc_profiles.profile_files(BASELINE) | set(apt.WINDOWS_INSTALLERS) | {apt.WINDOWS_INSTALLER_SOURCE}
        for name in names: shutil.copy2(BASELINE / name, self.root / name)
        for name in ('agpc.sh', 'agpc-all.sh', 'agpc-apps.sh', 'agpc-core.sh'):
            receipt = self.root / name.replace('.sh', '.source.json')
            data = json.loads(receipt.read_text()); data['schema'] = apt.AGENT_MESH_INSTALLER_SCHEMA
            data['tag'] = 'v9.9.9-100'; data['source_commit'] = 'c' * 40
            if name == 'agpc-core.sh':
                data['asset'] = 'agpc-mesh.sh'
                (self.root / name).rename(self.root / data['asset'])
                receipt.unlink(); receipt = self.root / 'agpc-mesh.source.json'
            receipt.write_text(json.dumps(data))

    def test_mesh_source_identity_and_old_alias_signature_rejected(self):
        apt.validate_agent_apps_installer(self.root)
        self.assertIn('agpc-mesh.sh', apt.agent_installer_files(self.root))
        self.assertNotIn('agpc-core.sh', apt.agent_installer_files(self.root))
        self.assertEqual(agpc_profiles.profile_files(self.root), agpc_profiles.PROFILE_FILES | agpc_profiles.MESH_PROFILE_FILES)
        for name in (*apt.AGENT_CORE_INSTALLER_FILES, 'agpc-core.sh.asc', 'agpc-core.source.json.asc'):
            (self.root / name).write_text('obsolete')
            with self.subTest(name=name), self.assertRaisesRegex(apt.PublishError, 'inactive'):
                apt.validate_agent_apps_installer(self.root)
            (self.root / name).unlink()

    def test_current_index_links_follow_source_schema_and_exact_deb(self):
        (self.root / 'scripts').mkdir()
        shutil.copy2(BASELINE / 'scripts/native-index.html', self.root / 'scripts/native-index.html')
        config = config_fixture()
        (self.root / apt.AGENT_COMPUTER_OVERLAY_FILE).write_text(json.dumps(config))
        html = agpc_profiles.index_html(self.root).decode()
        self.assertIn('href="agpc-mesh.sh"', html)
        self.assertIn('agpc-mesh.source.json', html)
        self.assertNotIn('agpc-core.sh', html)
        self.assertIn('agpc-core_0.1.0.core.20261106.1_amd64.deb', html)
        self.assertIn('agpc-all.sh', html)
        self.assertEqual(agpc_profiles.index_html(BASELINE), (BASELINE / 'scripts/native-index.html').read_bytes())

    def test_native_promotion_removes_only_the_obsolete_current_alias(self):
        (self.root / 'scripts').mkdir()
        (self.root / 'scripts/native-index.html').write_text('agpc-core.sh')
        (self.root / apt.AGENT_COMPUTER_OVERLAY_FILE).write_text(json.dumps(config_fixture()))
        site = self.root / 'site'; site.mkdir()
        old = set(apt.AGENT_CORE_INSTALLER_FILES) | {name + '.asc' for name in apt.AGENT_CORE_INSTALLER_FILES}
        for name in old: (site / name).write_bytes(b'old current')
        historical = site / 'legacy/v0.3.0-96/agpc-core.sh'
        historical.parent.mkdir(parents=True); historical.write_bytes(b'old signed release')
        (site / 'unrelated.txt').write_bytes(b'preserved')
        files = {name: b'native fixture' for name in native.NATIVE_FILES}
        profiles = {name: (self.root / name).read_bytes() for name in
                    ('agpc.sh', 'agpc.source.json', 'agpc-mesh.sh', 'agpc-mesh.source.json')}
        def sign(root, target, names):
            for name in names: (target / (name + '.asc')).write_bytes(b'fixture signature')
        with patch.object(native, 'assemble', return_value=({}, {'version': 'fixture', 'linux_backend_sha256': 'a' * 64}, files)), \
             patch.object(agpc_profiles, 'activated_files', return_value=({'core': {}}, profiles)), \
             patch.object(native, 'sign_files', side_effect=sign):
            native.overlay(self.root, site, self.root / 'evidence.json')
        self.assertTrue(all(not (site / name).exists() for name in old))
        self.assertEqual(historical.read_bytes(), b'old signed release')
        self.assertEqual((site / 'unrelated.txt').read_bytes(), b'preserved')
        self.assertEqual((site / 'agpc-mesh.sh').read_bytes(), (site / 'agpc.sh').read_bytes())
        self.assertTrue((site / 'agpc-mesh.sh.asc').is_file())

    def test_mesh_receipt_must_share_all_other_source_coordinates(self):
        path = self.root / 'agpc-mesh.source.json'; old = json.loads(path.read_text())
        for key, value in [('source_commit', 'd' * 40), ('tag', 'v9.9.9-101'), ('profile', 'mesh')]:
            path.write_text(json.dumps({**old, key: value}))
            with self.subTest(key=key), self.assertRaises(apt.PublishError): apt.validate_agent_apps_installer(self.root)
        path.write_text(json.dumps(old))
        (self.root / 'agpc-mesh.sh').write_bytes((self.root / 'agpc.sh').read_bytes() + b'# drift\n')
        old['sha256'] = apt.sha256(self.root / 'agpc-mesh.sh'); path.write_text(json.dumps(old))
        with self.assertRaisesRegex(apt.PublishError, 'byte-identical'): apt.validate_agent_apps_installer(self.root)

    def test_activation_requires_v13_exact_manifest_not_renamed_v96(self):
        fixture = publication_tests.ProfilePublicationTests('test_completed_signed_cohort_binds_distinct_standard_full_and_apps')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        for record in fixture.records.values():
            record['schema'] = apt.AGENT_MESH_INSTALLER_SCHEMA
            (fixture.root / record['asset'].replace('.sh', '.source.json')).write_text(json.dumps(record))
        record = {**fixture.records['standard'], 'asset': 'agpc-mesh.sh'}
        (fixture.root / 'agpc-mesh.source.json').write_text(json.dumps(record))
        (fixture.root / 'agpc-mesh.sh').write_bytes((fixture.root / 'agpc.sh').read_bytes())
        fixture.manifest['installer_profiles']['agpc-mesh.sh'] = 'standard'
        fixture.manifest['assets'] += [{'name': 'agpc-mesh.sh', 'sha256': record['sha256']},
                                      {'name': 'uninstall.sh', 'sha256': apt.sha256(fixture.root / 'uninstall.sh')}]
        fixture.config['schema'] = apt.AGENT_COMPUTER_CORE_SCHEMA
        raw = json.dumps(fixture.config)
        for root in (fixture.root, fixture.site): (root / apt.AGENT_COMPUTER_OVERLAY_FILE).write_text(raw)
        fixture.manifest['aggregate_tag'] = fixture.config['release']['tag']
        fixture.manifest['overlay_sha256'] = agpc_profiles.digest(raw.encode())
        result, files = fixture.activate()
        self.assertIn('core', result); self.assertNotIn('mesh', result)
        self.assertIn('agpc-mesh.sh', files); self.assertNotIn('agpc-core.sh', files)
        fixture.config['schema'] = apt.AGENT_COMPUTER_VIEW_SCHEMA
        raw = json.dumps(fixture.config)
        for root in (fixture.root, fixture.site): (root / apt.AGENT_COMPUTER_OVERLAY_FILE).write_text(raw)
        fixture.manifest['overlay_sha256'] = agpc_profiles.digest(raw.encode())
        with self.assertRaisesRegex(ValueError, 'schema'): fixture.activate()


class CorePayloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name); self.tree = self.folder / 'tree'; self.tree.mkdir()
        self.config = config_fixture(); self.approved = {p['name']: p for p in self.config['release']['packages']}
        (self.tree / 'DEBIAN').mkdir()
        relationships = ', '.join(f"{name} ({'>=' if name == 'agpc-cdp' else '='} {version})"
                                   for name, version in apt.AGPC_CORE_DEPENDENCIES.items())
        self.control = ('Package: agpc-core\nVersion: ' + apt.AGPC_CORE_VERSION + '\nArchitecture: amd64\n'
                        'Maintainer: Test <test@example.invalid>\nDescription: Core fixture\nDepends: ' + relationships + '\n')
        (self.tree / 'DEBIAN/control').write_text(self.control)
        self.cohort = {'schema': 'agpc.core.package-cohort/v1', 'name': 'agpc-core', 'version': apt.AGPC_CORE_VERSION,
                       'architecture': 'amd64', 'kind': 'dependency-cohort', 'installer': 'agpc-mesh.sh',
                       'dependencies': [{'name': n, 'version': v, 'relation': '>=' if n == 'agpc-cdp' else '='}
                                        for n, v in apt.AGPC_CORE_DEPENDENCIES.items()],
                       'transitive_cohort_admitted': False, **{flag: False for flag in core.FLAGS}}
        proof = {'schema': 'agpc.core.package-source/v1', 'source': {'project': 1336,
                 'commit': self.approved['agpc-core']['provenance']['source_commit']}, **{flag: False for flag in core.FLAGS}}
        for name, value in [('usr/share/doc/agpc-core/README', 'Core fixture'),
                            ('usr/share/agpc-core/cohort.json', json.dumps(self.cohort)),
                            ('usr/share/doc/agpc-core/PROVENANCE.json', json.dumps(proof))]:
            path = self.tree / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value)

    def archive(self):
        for path in (self.tree, *self.tree.rglob('*')):
            path.chmod(0o755 if path.is_dir() or (path.parent.name == 'DEBIAN' and path.name in ('postinst', 'prerm')) else 0o644)
        deb = self.folder / 'core.deb'
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(self.tree), str(deb)], check=True, stdout=subprocess.DEVNULL)
        self.approved['agpc-core']['sha256'] = apt.sha256(deb)
        return deb

    def test_real_deb_readback_requires_metadata_only_false_admission(self):
        core.validate_core_package(self.archive(), self.approved)
        for field in ('release_admitted', 'runtime_ready', 'transitive_cohort_admitted'):
            changed = {**self.cohort, field: True}; (self.tree / 'usr/share/agpc-core/cohort.json').write_text(json.dumps(changed))
            with self.subTest(field=field), self.assertRaisesRegex(apt.PublishError, 'admission'):
                core.validate_core_package(self.archive(), self.approved)

    def test_no_runtime_hook_or_unreviewed_dependency_can_enter_core(self):
        for name in ('DEBIAN/postinst', 'DEBIAN/triggers', 'usr/bin/agpc-core'):
            path = self.tree / name; path.parent.mkdir(exist_ok=True, parents=True); path.write_text('unexpected\n')
            with self.subTest(name=name), self.assertRaises(apt.PublishError): core.validate_core_package(self.archive(), self.approved)
            path.unlink()
        (self.tree / 'DEBIAN/control').write_text(self.control.replace('iagent (= 1.0.0-1)', 'iagent (>= 1.0.0-1)'))
        with self.assertRaisesRegex(apt.PublishError, 'exactly'): core.validate_core_package(self.archive(), self.approved)


if __name__ == '__main__': unittest.main()
