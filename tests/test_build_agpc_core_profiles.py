"""The new producer preserves historical bytes and binds every changed package."""
import ast
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
import build_agpc_core_profiles as producer
import publish_apt as apt
import publish_component
import test_agpc_core_profiles as fixtures

ROOT = Path(__file__).resolve().parents[1]


def policy_engine(raw):
    code = raw.decode().split("<<'PY_UNINSTALL_PREFLIGHT'\n", 1)[1].split('\nPY_UNINSTALL_PREFLIGHT\n', 1)[0]
    values = {'__name__': 'fixture'}
    exec(compile(code, 'fixture-removal', 'exec'), values)
    return values


class CoreProducerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.baseline = fixtures.BASELINE
        self.folder = Path(self.temp.name); self.bundle = self.folder / 'components'; self.bundle.mkdir()
        config = fixtures.config_fixture()
        self.inputs = {'schema': producer.INPUT_SCHEMA, 'installer_tag': 'v9.9.9-100',
                       'aggregate_tag': config['release']['tag'], 'baseline_source_commit': json.loads((self.baseline / 'FIXTURE.json').read_text())['source_commit'],
                       'baseline_files': {name: apt.sha256(self.baseline / name) for name in producer.BASELINE_FILES},
                       'components': []}
        approved = {p['name']: p for p in config['release']['packages']}
        fixture = fixtures.CorePayloadTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        deb = fixture.archive(); approved['agpc-core']['sha256'] = apt.sha256(deb)
        shutil.copy2(deb, self.bundle / approved['agpc-core']['asset'])
        for name in producer.COMPONENTS:
            package = approved[name]
            if name != 'agpc-core':
                tree = self.folder / name; (tree / 'DEBIAN').mkdir(parents=True)
                (tree / 'DEBIAN/control').write_text(f"Package: {name}\nVersion: {package['version']}\nArchitecture: {package['architecture']}\nMaintainer: Test <test@example.invalid>\nDescription: Original fixture\n")
                if name == 'agpc-mesh':
                    path = tree / 'usr/lib/systemd/system/agpc-mesh.service'; path.parent.mkdir(parents=True); path.write_text('[Unit]\nDescription=Fixture\n')
                    path = tree / 'usr/share/agpc-mesh/bootstrap/agpc-mesh-mchat.env'; path.parent.mkdir(parents=True); path.write_text('fixture\n')
                if name == 'agpc-vmodel':
                    (tree / 'DEBIAN/prerm').write_text('#!/bin/sh\nexit 0\n'); (tree / 'DEBIAN/prerm').chmod(0o755)
                for node in (tree, *tree.rglob('*')):
                    node.chmod(0o755 if node.is_dir() or node.name == 'prerm' else 0o644)
                path = self.bundle / package['asset']
                subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(tree), str(path)], check=True, stdout=subprocess.DEVNULL)
                package['sha256'] = apt.sha256(path)
            self.inputs['components'].append({'package': package, 'source_tag': name + '-v9.9.9-100', 'main_job_id': 101})

    def build(self):
        result = self.folder / 'output'
        producer.build(self.baseline, self.inputs, result, 'c' * 40, self.bundle)
        return result

    def test_five_explicit_overrides_preserve_all_other_cohort_bytes(self):
        old, new = producer.validate_inputs(self.baseline, self.inputs)
        previous = {p['name']: p for p in old['release']['packages']}
        current = {p['name']: p for p in new['release']['packages']}
        self.assertEqual({n: p for n, p in current.items() if n not in producer.COMPONENTS},
                         {n: p for n, p in previous.items() if n not in producer.COMPONENTS})
        self.assertEqual(new['release']['external_prerequisites'], old['release']['external_prerequisites'])
        self.assertEqual(new['release']['retention_packages'], old['release']['retention_packages'])
        for key, value in [('installer_tag', 'v0.3.0-96'), ('aggregate_tag', 'agent-computer-v0.3.0-85'),
                           ('baseline_files', {}), ('components', self.inputs['components'][:-1])]:
            with self.subTest(key=key), self.assertRaises(apt.PublishError):
                producer.validate_inputs(self.baseline, {**self.inputs, key: value})
        bad = copy.deepcopy(self.inputs); bad['components'][0]['package']['provenance']['source_ref'] = 'refs/heads/candidate'
        with self.assertRaises(apt.PublishError): producer.validate_inputs(self.baseline, bad)

    def test_cli_rejects_branch_ci_and_wrong_original_commit_before_network(self):
        args = ['producer', str(ROOT), str(ROOT / 'scripts/agpc-core-profile-release-input.json'), str(self.folder / 'never')]
        with patch.object(sys, 'argv', args), patch.dict(producer.os.environ, {'CI_COMMIT_BRANCH': 'candidate', 'CI_COMMIT_REF_PROTECTED': 'true'}), \
             patch.object(producer.urllib.request, 'urlopen') as network:
            with self.assertRaisesRegex(apt.PublishError, 'protected main'): producer.main()
            network.assert_not_called()
        with patch.object(sys, 'argv', args), patch.dict(producer.os.environ, {'CI_COMMIT_BRANCH': 'main', 'CI_COMMIT_REF_PROTECTED': 'true', 'CI_COMMIT_SHA': 'a' * 40}), \
             patch.object(producer.subprocess, 'check_output', return_value='b' * 40), \
             patch.object(producer.urllib.request, 'urlopen') as network:
            with self.assertRaisesRegex(apt.PublishError, 'exact clean'): producer.main()
            network.assert_not_called()

    def test_original_component_corruption_stops_before_output(self):
        item = self.inputs['components'][0]['package']
        (self.bundle / item['asset']).write_bytes(b'corrupt')
        with self.assertRaises(apt.PublishError): self.build()
        self.assertFalse((self.folder / 'output').exists())

    def test_all_four_new_receipts_and_manifest_bind_real_mesh_full_bytes(self):
        result = self.build(); manifest = json.loads((result / 'release-manifest.json').read_text())
        self.assertEqual(manifest['installer_profiles'], producer.PROFILES)
        self.assertEqual(manifest['overlay_sha256'], apt.sha256(result / apt.AGENT_COMPUTER_OVERLAY_FILE))
        self.assertEqual(manifest['native_profile_acceptance'], 'required-before-pages-deploy')
        self.assertFalse((result / 'agpc-core.sh').exists())
        self.assertEqual((result / 'agpc-mesh.sh').read_bytes(), (result / 'agpc.sh').read_bytes())
        self.assertEqual((result / 'agpc-apps.sh').read_bytes(), (self.baseline / 'agpc-apps.sh').read_bytes())
        for name, profile in producer.PROFILES.items():
            source = json.loads((result / name.replace('.sh', '.source.json')).read_text())
            self.assertEqual((source['schema'], source['tag'], source['source_commit'], source['profile']),
                             (apt.AGENT_MESH_INSTALLER_SCHEMA, self.inputs['installer_tag'], 'c' * 40, profile))
            self.assertEqual(source['sha256'], apt.sha256(result / name))
        record = json.loads((result / 'aggregate-component-release.json').read_text())
        publish_component.validate(record, record['tag'])

    def test_exact_selection_guards_preserve_owner_cdp_and_historical_mcp(self):
        result = self.build()
        for name in ('agpc.sh', 'agpc-mesh.sh', 'agpc-all.sh'):
            text = (result / name).read_text()
            selection = next(line for line in text.splitlines() if line.startswith('packages=('))
            selected = subprocess.check_output(['bash', '-c', 'cdp_version=0.2.0-2+home.1\n' + selection + '\nprintf "%s\\n" "${packages[@]}"'], text=True).splitlines()
            self.assertIn('agpc-core=' + apt.AGPC_CORE_VERSION, selected)
            self.assertIn('agpc-vmodel=' + apt.AGPC_VMODEL_VERSION, selected)
            self.assertIn('iagent=1.0.0-1', selected)
            self.assertEqual(selected.count('medge=3.3.0-2'), 1)
            selection_block = text[text.index('\npackages=('):text.index('\nlegacy_apps_version=-')]
            for existing in ('installed', 'not-installed'):
                script = 'dpkg-query() { printf \"%s\\n\" ' + existing + '; }\ncdp_version=0.2.0-2\n' + selection_block + '\nprintf \"%s\\n\" \"${packages[@]}\"'
                packages = subprocess.check_output(['bash', '-c', script], text=True).splitlines()
                self.assertEqual(packages.count('medge=3.3.0-2'), 1)
            self.assertIn('agpc-cdp=0.2.0-2+home.1', selected)
            self.assertIn("'3.0.0-3|amd64|install ok installed'", text)  # Historical MCP version is not Mesh.
            floor = next(line for line in text.splitlines() if line.startswith('declare -A floor='))
            guards = text.split("        [[ $new != - ]] || fail 'missing target version'", 1)[1].split('        if [[ $name == mote-transportd', 1)[0]
            for version, accepted in [(apt.AGPC_CORE_VERSION, True), (apt.AGPC_CORE_VERSION + '+other', False)]:
                check = subprocess.run(['bash', '-c', 'fail() { exit 42; }\n' + floor + '\nname=agpc-core; old=-; new=$1\n' + guards, 'fixture', version])
                self.assertEqual(check.returncode == 0, accepted)

    def test_uninstaller_pins_new_original_hooks_and_retains_old_policy(self):
        result = self.build()
        old = policy_engine((self.baseline / 'uninstall.sh').read_bytes())
        current = policy_engine((result / 'uninstall.sh').read_bytes())
        overlay = json.loads((result / apt.AGENT_COMPUTER_OVERLAY_FILE).read_text())
        current['validate_catalog'](overlay)
        for name in set(old['POLICY']) - set(producer.COMPONENTS):
            self.assertEqual(current['POLICY'][name], old['POLICY'][name])
        for name in ('agpc-manager', 'agpc-view', 'agpc-mesh'):
            self.assertIn(old['POLICY'][name], current['ALTERNATE_POLICY'][name])
        self.assertEqual(current['POLICY']['agpc-core']['hooks'], {'prerm': None, 'postrm': None})
        self.assertEqual(current['POLICY']['agpc-vmodel']['hooks']['prerm'], producer.sha(b'#!/bin/sh\nexit 0\n'))
        self.assertIn('/usr/share/agpc-mesh/bootstrap/agpc-mesh-mchat.env', current['POLICY']['agpc-mesh']['retained_payloads'])
        overlay['release']['packages'][-1]['sha256'] = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'pin differs'): current['validate_catalog'](overlay)


if __name__ == '__main__': unittest.main()
