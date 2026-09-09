"""Run only the read-only preflight with a fake dpkg-query; never run uninstall."""
from pathlib import Path
import ast
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / 'uninstall.sh').read_text()
CODE = TEXT.split("<<'PY_UNINSTALL_PREFLIGHT'\n", 1)[1].split('\nPY_UNINSTALL_PREFLIGHT\n', 1)[0]


class UninstallPreflightTest(unittest.TestCase):
    def run_preflight(self, states=None, conffiles=None, broken=False):
        # An isolated child runs the exact embedded code; its subprocess entry
        # point is replaced before evaluation. No real dpkg or host files run.
        prefix = '''
import subprocess,types
states=STATES
conffiles=CONFFILES
broken=BROKEN
calls=[]
def query_fixture(args, **kwargs):
    assert args[:2] == ['dpkg-query','-W'], 'unexpected process action'
    assert len(args) == 4, 'unexpected query arguments'
    calls.append(args)
    package=args[-1]
    if broken:
        return types.SimpleNamespace(returncode=2,stdout='',stderr='fixture DPKG error')
    if args[2] == '-f=${db:Status-Status}':
        value=states.get(package)
    elif args[2] == '-f=${Conffiles}':
        value=conffiles.get(package)
    else:
        raise AssertionError('unexpected DPKG field')
    return types.SimpleNamespace(returncode=1 if value is None else 0,stdout=value or '',stderr='')
subprocess.run=query_fixture
'''.replace('STATES',repr(states or {})).replace('CONFFILES',repr(conffiles or {})).replace('BROKEN',repr(broken))
        return subprocess.run([sys.executable,'-'],input=prefix+CODE+'\nprint("preflight passed")\n',
                              text=True,capture_output=True,check=False)

    def test_legacy_or_empty_host_remains_supported(self):
        result=self.run_preflight(conffiles={'mote-chatd':' /etc/mote/mote-chatd/mote-chatd-deb.env '+('a'*32)+'\n'})
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('preflight passed',result.stdout)

    def test_each_current_composition_identity_blocks(self):
        for package in ('agent-sphere','agent-apps','mote-transportd','agos','mote-vault-sync','mote-vault-syncd','model-router','model-grid','model-llm','cx-agent'):
            for state in ('installed','config-files','unpacked','half-configured','half-installed','triggers-pending'):
                with self.subTest(package=package,state=state):
                    result=self.run_preflight(states={package:state})
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn(package,result.stderr)
                    self.assertIn('no packages, services, configuration or vaults were changed',result.stderr)
                    self.assertNotIn('preflight passed',result.stdout)

    def test_not_installed_records_are_not_a_false_block(self):
        result=self.run_preflight(states={'agent-sphere':'not-installed','agent-apps':''})
        self.assertEqual(result.returncode,0,result.stderr)

    def test_active_and_obsolete_legacy_topology_ownership_block(self):
        path='/etc/mote/mote-chatd/mote-chatd-mchat.env'
        for package in ('mote-chatd','mote-transportd','schatd','chatd'):
            for suffix in ('',' obsolete'):
                with self.subTest(package=package,suffix=suffix):
                    result=self.run_preflight(conffiles={package:' '+path+' '+('a'*32)+suffix+'\n'})
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn('protected legacy configuration ownership',result.stderr)
                    self.assertIn('owner migration is required',result.stderr)

    def test_dpkg_inspection_error_stops_preflight(self):
        result=self.run_preflight(broken=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('could not inspect DPKG',result.stderr)

    def test_no_identity_contents_or_mutating_commands_are_accessed(self):
        parsed=ast.parse(CODE)
        calls=[n for n in ast.walk(parsed) if isinstance(n,ast.Call)]
        for call in calls:
            self.assertFalse(isinstance(call.func,ast.Name) and call.func.id in {'open','exec','eval'})
        self.assertNotIn('apt-get',CODE)
        self.assertNotIn('systemctl',CODE)
        self.assertNotIn('os.remove',CODE)
        self.assertNotIn('read_text',CODE)

    def test_preflight_precedes_all_uninstaller_mutation_and_network(self):
        end=TEXT.index('\nPY_UNINSTALL_PREFLIGHT\n')
        for later in ('TEMP_DIR="$(mktemp', 'install -d -m 0700', "curl --proto", 'apt-get --simulate purge', 'apt-get purge -y'):
            self.assertLess(end,TEXT.index(later))
        self.assertIn('medge-public-release/v19',TEXT[end:])
        self.assertIn('"${#APPROVED_PACKAGES[@]}" -eq 18',TEXT[end:])


if __name__ == '__main__':
    unittest.main(verbosity=2)
