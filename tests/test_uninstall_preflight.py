"""Exercise native removal admission and exact APT actions without touching host packages."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

ROOT = Path(__file__).parents[1]
TEXT = (ROOT / 'uninstall.sh').read_text()
CODE = TEXT.split("<<'PY_UNINSTALL_PREFLIGHT'\n", 1)[1].split('\nPY_UNINSTALL_PREFLIGHT\n', 1)[0]

def engine():
    namespace = {'__name__': 'uninstall_fixture'}
    exec(compile(CODE, 'uninstall-engine', 'exec'), namespace)
    return namespace

class UninstallPreflightTest(unittest.TestCase):
    def setUp(self):
        self.module = engine()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.policy = {'fixture': {'version': '1.0-1', 'architecture': 'all', 'sha256': 'a' * 64,
                                  'hooks': {'prerm': None, 'postrm': None}, 'units': [], 'retained_payloads': []}}
        self.records = {'fixture': 'installed|1.0-1|all'}
        self.conffiles = {}
        self.listing = ''
        self.module['query'] = lambda name, field: self.conffiles.get(name, '') if field == '$' + '{Conffiles}' else self.records.get(name, '')
        self.module['run'] = lambda args, **kwargs: SimpleNamespace(stdout=self.listing)
        self.packages = {'fixture': {'version': '1.0-1', 'architecture': 'all'}}

    def inspect(self):
        return self.module['inspect'](self.policy, self.root)

    def test_policy_matches_reviewed_catalog_and_known_hooks(self):
        # The removal engine remains pinned to its current signed v0.3.0-50 policy
        # while the active installer cohort advances independently. Build the
        # exact historical catalog from the engine's own reviewed constants.
        policy = self.module['POLICY']
        current = {'schema': 'agent-computer-apt-overlay/v7', 'release': {
            'repository': 'motebus/download', 'tag': self.module['RELEASE_TAG'],
            'packages': [{'name': name, 'version': value['version'],
                          'architecture': value['architecture'],
                          'sha256': value['sha256']} for name, value in policy.items()]}}
        self.module['validate_catalog'](current)
        reviewed = list(self.module['POLICY'].values())
        reviewed += [item for variants in self.module['ALTERNATE_POLICY'].values() for item in variants]
        for package in reviewed:
            self.assertRegex(package['sha256'], '^[0-9a-f]{64}$')
            for digest in package['hooks'].values():
                self.assertTrue(digest is None or re.fullmatch('[0-9a-f]{64}', digest))
            self.assertTrue(all(re.fullmatch('[a-zA-Z0-9_.-]+[.](service|target|socket|timer)', u) for u in package['units']))

    def test_exact_reviewed_upgrade_alternatives_are_admitted(self):
        select = self.module['reviewed_policy']
        policy = self.module['POLICY']
        for name, variants in self.module['ALTERNATE_POLICY'].items():
            for expected in variants:
                self.assertIs(select(name, expected['version'], expected['architecture'], policy), expected)
            with self.assertRaisesRegex(RuntimeError, 'Unreviewed package version'):
                select(name, '999.0-1', variants[0]['architecture'], policy)
        with self.assertRaisesRegex(RuntimeError, 'Unreviewed package version'):
            select('moted', '3.6.2-1', 'arm64', policy)

    def test_installed_packages_are_selected_and_conffiles_preserved(self):
        conf = self.root / 'owner.conf'
        conf.write_text('owner content')
        self.conffiles['fixture'] = str(conf) + ' ' + 'b' * 32
        result = self.inspect()
        self.assertEqual(result['packages'], self.packages)
        self.assertEqual(result['retained'][str(conf)]['sha256'], hashlib.sha256(conf.read_bytes()).hexdigest())

    def test_residual_configuration_is_not_purged(self):
        for value in ('', 'not-installed||', 'config-files|0.1|amd64'):
            self.records['fixture'] = value
            self.assertEqual(self.inspect()['packages'], {})

    def test_partial_or_unreviewed_packages_are_rejected(self):
        for value in ('half-configured|1.0-1|all', 'installed|0.1|all', 'installed|1.0-1|arm64'):
            self.records['fixture'] = value
            with self.assertRaises(RuntimeError):
                self.inspect()

    def test_changed_or_new_removal_hooks_are_rejected(self):
        hook = self.root / 'fixture.prerm'
        hook.write_text('unexpected')
        with self.assertRaisesRegex(RuntimeError, 'Unexpected removal hook'):
            self.inspect()
        self.policy['fixture']['hooks']['prerm'] = hashlib.sha256(b'approved').hexdigest()
        with self.assertRaisesRegex(RuntimeError, 'differs from reviewed'):
            self.inspect()
        hook.write_bytes(b'approved')
        self.assertEqual(self.inspect()['packages'], self.packages)

    def test_locked_payload_and_legacy_transport_ownership_are_rejected(self):
        self.listing = '/etc/mote/example/example-mchat.env\n'
        with self.assertRaisesRegex(RuntimeError, 'Locked topology'):
            self.inspect()
        self.listing = ''
        self.policy = {'mote-transportd': self.policy['fixture']}
        self.records = {'mote-transportd': 'installed|1.0-1|all'}
        self.conffiles = {'mote-transportd': '/etc/mote/mote-chatd/mote-chatd-mchat.env ' + 'c' * 32 + ' obsolete'}
        with self.assertRaisesRegex(RuntimeError, 'owner migration'):
            self.inspect()

    def test_simulation_requires_exact_removals(self):
        validate = self.module['validate_plan']
        validate('Remv fixture [1.0-1]\n', self.packages)
        for plan in ('', 'Remv other [1.0-1]\n', 'Remv fixture [0.1]\n',
                     'Purg fixture [1.0-1]\n', 'Inst other (1)\n',
                     'Remv fixture [1.0-1]\nConf other (1)\n',
                     'Remv fixture [1.0-1]\nRemv fixture [1.0-1]\n'):
            with self.subTest(plan=plan), self.assertRaises(RuntimeError):
                validate(plan, self.packages)

    def test_actual_apt_protocol_cannot_expand_or_change_the_plan(self):
        validate = self.module['validate_protocol']
        prefix = 'VERSION 3\nAPT::Architecture=amd64\n\n'
        valid = 'fixture 1.0-1 all none > - - none **REMOVE**\n'
        validate(prefix + valid, self.packages)
        for payload in ('', 'VERSION 2\n\n' + valid, prefix,
                        prefix + valid + valid, prefix + valid.replace('fixture', 'other'),
                        prefix + valid.replace('1.0-1', '0.1'),
                        prefix + valid.replace('**REMOVE**', '**CONFIGURE**'),
                        prefix + valid.replace('all', 'amd64')):
            with self.subTest(payload=payload), self.assertRaises(RuntimeError):
                validate(payload, self.packages)

    def test_no_purge_or_unbounded_cleanup_command(self):
        ast.parse(CODE)
        self.assertNotIn('apt-get purge', TEXT)
        self.assertNotIn('apt-get autoremove', TEXT)
        self.assertNotIn('rm -rf', TEXT)
        self.assertIn('DPkg::Pre-Install-Pkgs::=', CODE)
        self.assertIn('APT::Get::Purge=false', CODE)

class NativeRemovalTransactionTest(unittest.TestCase):
    def test_real_apt_removal_uses_protocol_guard_and_retains_configuration(self):
        # All apt/dpkg state, logs, and files live under this disposable fixture.
        # Host apt configuration and maintainer scripts are never consumed.
        with tempfile.TemporaryDirectory(prefix='agpc-removal-test-') as folder:
            base = Path(folder)
            target = base / 'target'
            info = target / 'var/lib/dpkg'
            info.mkdir(parents=True)
            (info / 'status').write_text('')
            package = base / 'package'
            (package / 'DEBIAN').mkdir(parents=True)
            (package / 'etc').mkdir()
            (package / 'etc/agpc-removal-fixture.conf').write_text('retain owner settings\n')
            (package / 'etc/agpc-removal-fixture-mchat.env').write_text('retained topology fixture\n')
            (package / 'DEBIAN/conffiles').write_text('/etc/agpc-removal-fixture.conf\n')
            (package / 'DEBIAN/control').write_text('Package: agpc-removal-fixture\nVersion: 1.0-1\nArchitecture: all\nMaintainer: Fixture <fixture@example.invalid>\nDescription: isolated removal test\n')
            deb = base / 'fixture.deb'
            subprocess.run(['dpkg-deb', '--build', str(package), str(deb)], check=True, capture_output=True)
            subprocess.run(['dpkg', '--root=' + str(target), '--log=' + str(base / 'dpkg.log'),
                            '--force-not-root', '-i', str(deb)], check=True, capture_output=True)
            policy = {'agpc-removal-fixture': {'version': '1.0-1', 'architecture': 'all',
                      'sha256': hashlib.sha256(deb.read_bytes()).hexdigest(),
                      'hooks': {'prerm': None, 'postrm': None}, 'units': [], 'retained_payloads': ['/etc/agpc-removal-fixture-mchat.env']}}
            code = (CODE[:CODE.index('POLICY = ')] + 'POLICY = ' + repr(policy)
                    + '\nALTERNATE_POLICY = {}\n' + CODE[CODE.index('RELEASE_TAG = '):])
            code = code.replace("Path('/var/lib/dpkg/info')", 'Path(' + repr(str(info / 'info')) + ')')
            code = code.replace("Path('/var/lib/dpkg')", 'Path(' + repr(str(info)) + ')')
            code = code.replace("['dpkg-query', '-W'", "['dpkg-query', '--admindir=" + str(info) + "', '-W'")
            code = code.replace("['dpkg-query', '-L'", "['dpkg-query', '--admindir=" + str(info) + "', '-L'")
            code = code.replace('def retained_file(path):\n    path = Path(path)',
                                'def retained_file(path):\n    path = Path(' + repr(str(target)) + ') / str(path).lstrip("/")')
            stage = base / 'stage'
            stage.mkdir()
            (stage / 'engine.py').write_text(code)
            release = {'schema': 'agent-computer-apt-overlay/v7', 'release': {
                'repository': 'motebus/download', 'tag': engine()['RELEASE_TAG'],
                'packages': [dict(name=name, **{k:v for k,v in row.items() if k in ('version','architecture','sha256')}) for name,row in policy.items()]}}
            (stage / 'agent-computer-apt-overlay.json').write_text(json.dumps(release))
            apt = base / 'apt'
            for sub in ('etc', 'state/lists/partial', 'cache/archives/partial', 'log'):
                (apt / sub).mkdir(parents=True)
            config = base / 'apt.conf'
            config.write_text(
                'Dir::Etc "' + str(apt / 'etc') + '";\n'
                'Dir::State "' + str(apt / 'state') + '";\n'
                'Dir::State::status "' + str(info / 'status') + '";\n'
                'Dir::Cache "' + str(apt / 'cache') + '";\n'
                'Dir::Log "' + str(apt / 'log') + '";\n'
                'DPkg::Options { "--root=' + str(target) + '"; "--log=' + str(base / 'dpkg.log') + '"; "--force-not-root"; };\n')
            result = subprocess.run(['python3', str(stage / 'engine.py'), '--yes', str(stage)],
                                    env=dict(os.environ, APT_CONFIG=str(config), LC_ALL='C'),
                                    text=True, capture_output=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((stage / 'guard-ran').exists())
            self.assertEqual((target / 'etc/agpc-removal-fixture.conf').read_text(), 'retain owner settings\n')
            state = subprocess.run(['dpkg-query', '--admindir=' + str(info), '-W', '-f=' + '$' + '{db:Status-Status}', 'agpc-removal-fixture'],
                                   text=True, capture_output=True, check=True).stdout
            self.assertEqual(state, 'config-files')
            self.assertEqual((target / 'etc/agpc-removal-fixture-mchat.env').read_text(), 'retained topology fixture\n')
            diverted = subprocess.run(['dpkg-divert', '--admindir=' + str(info), '--truename', '/etc/agpc-removal-fixture-mchat.env'],
                                      check=True, capture_output=True, text=True).stdout.strip()
            self.assertEqual(diverted, '/etc/agpc-removal-fixture-mchat.env')
