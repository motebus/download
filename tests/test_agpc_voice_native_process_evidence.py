"""Diagnostic binding and non-interference checks; no native package execution."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('voice_process_diagnostics',
    ROOT / 'scripts/collect_agpc_voice_native_process_evidence.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProcessEvidenceTests(unittest.TestCase):
    def test_cli_both_native_targets_keep_fixed_paths_and_actual_host_binding(self):
        for version in ('24.04','26.04'):
            with self.subTest(version=version), \
                    patch.object(sys,'argv',['collect.py','--mode','fresh']), \
                    patch.object(module.os,'geteuid',return_value=0), \
                    patch.object(module.platform,'freedesktop_os_release',return_value={'ID':'ubuntu','VERSION_ID':version}), \
                    patch.object(module.platform,'machine',return_value='x86_64'), \
                    patch.object(module.platform,'node',return_value='actual-runner'), \
                    patch.object(module,'collect',return_value={'observations':[]}) as collect, \
                    patch.object(sys,'stdout',new=io.StringIO()):
                module.main()
                collect.assert_called_once_with(module.PACKET,module.RUNS,module.PROCESSES,'fresh',module.os.environ,'actual-runner')

    def test_cli_refuses_other_os_architecture_and_nonroot_before_reading(self):
        for uid,os_id,version,arch in ((1000,'ubuntu','26.04','x86_64'),
                (0,'debian','26.04','x86_64'),(0,'ubuntu','25.10','x86_64'),(0,'ubuntu','26.04','aarch64')):
            with self.subTest(uid=uid,os_id=os_id,version=version,arch=arch), \
                    patch.object(sys,'argv',['collect.py','--mode','fresh']), \
                    patch.object(module.os,'geteuid',return_value=uid), \
                    patch.object(module.platform,'freedesktop_os_release',return_value={'ID':os_id,'VERSION_ID':version}), \
                    patch.object(module.platform,'machine',return_value=arch), \
                    patch.object(module,'collect') as collect:
                with self.assertRaisesRegex(ValueError,'Root on disposable'):module.main()
                collect.assert_not_called()

    def setUp(self):
        self.source = b'{"source":"fixture"}\n'
        self.github = dict(module.FIXED, GITHUB_RUN_ID='42', GITHUB_RUN_ATTEMPT='1',
                           GITHUB_SHA='a' * 40)
        self.session = dict(schema='agpc.voice-native-entry-ci-session/v1', mode='fresh',
            host='native-runner', github=self.github, source_commit='b' * 40,
            source_manifest_sha256=hashlib.sha256(self.source).hexdigest())
        self.state = dict(self.session, execution_id='42-1-fresh',
            runtime_sha256={name: 'c' * 64 for name in module.RUNTIME_FILES},
            authorization_sha256='d' * 64, status='held')
        self.binding = {k: self.state[k] for k in module.BINDING}

    def validate(self, **changes):
        return module.validate_binding(changes.get('session', self.session),
            changes.get('state', self.state), changes.get('source', self.source),
            changes.get('mode', 'fresh'), changes.get('env', self.github),
            changes.get('host', 'native-runner'))

    def test_held_session_can_be_observed_without_clearing(self):
        self.assertEqual(self.validate(), ('42-1-fresh', self.binding))
        self.assertEqual(self.state['status'], 'held')

    def test_session_producer_runtime_closure_is_accepted_for_every_mode(self):
        producer_spec = importlib.util.spec_from_file_location('voice_session_producer',
            ROOT/'scripts/prepare_agpc_voice_native_entry_session.py')
        producer = importlib.util.module_from_spec(producer_spec)
        producer_spec.loader.exec_module(producer)
        # Derive the independent producer's inventory, not the collector's
        # constant: the old seven-module collector rejected real nine-module runs.
        pins = {Path(name).name: 'c'*64 for name in producer.FILES if name.startswith('src/')}
        self.assertEqual(len(pins), 9)
        self.assertTrue({'native_voice_plan.py', 'native_voice_preserve.py'} <= pins.keys())
        self.assertEqual(set(module.MODES), set(producer.MODES))
        for mode in producer.MODES:
            state = dict(self.state, mode=mode, execution_id='42-1-'+mode, runtime_sha256=pins)
            session = dict(self.session, mode=mode)
            with self.subTest(mode=mode):
                execution, binding = self.validate(session=session, state=state, mode=mode)
                self.assertEqual(execution, '42-1-'+mode)
                self.assertEqual(binding['runtime_sha256'], pins)
                for missing in ('native_voice_plan.py', 'native_voice_preserve.py'):
                    with self.assertRaisesRegex(ValueError, 'Incomplete process binding'):
                        self.validate(session=session, state=dict(state,
                            runtime_sha256={k:v for k,v in pins.items() if k != missing}), mode=mode)

    def test_other_run_attempt_mode_host_and_workflow_refused(self):
        cases = [dict(env={**self.github, 'GITHUB_RUN_ID': '43'}),
                 dict(env={**self.github, 'GITHUB_RUN_ATTEMPT': '2'}),
                 dict(mode='upgrade'), dict(host='another-host'),
                 dict(env={**self.github, 'GITHUB_REF': 'refs/heads/feature'})]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.validate(**case)

    def test_wrong_source_or_manifest_refused(self):
        for case in (dict(source=self.source + b'\n'),
                     dict(state={**self.state, 'source_commit': 'e' * 40})):
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.validate(**case)

    def test_execution_path_and_incomplete_binding_refused(self):
        for state in ({**self.state, 'execution_id': '../elsewhere'},
                      {**self.state, 'runtime_sha256': {}}):
            with self.subTest(state=state), self.assertRaises(ValueError):
                self.validate(state=state)

    def test_missing_replaced_and_invalid_runtime_pins_refused(self):
        pins = self.state['runtime_sha256']
        missing = {k: v for k, v in pins.items() if k != 'native_voice_dialplan.py'}
        replaced = {**missing, 'unrelated.py': 'c' * 64}
        invalid = {**pins, 'native_voice_dialplan.py': 'not-a-digest'}
        for runtime in (missing, replaced, invalid):
            with self.subTest(runtime=runtime), self.assertRaises(ValueError):
                self.validate(state={**self.state, 'runtime_sha256': runtime})

    def observation(self):
        return dict(schema='agpc.package-process-observation/v1',
                    test_binding=self.binding, state='held-quiescent',
                    reason='direct-exit-unverified', fault_classes=['PackageProcessHeld'],
                    argv=['/usr/bin/apt-get', 'private-argument'],
                    environment={'PRIVATE': 'not-exported'}, extra='not-exported')

    def test_projection_keeps_failure_but_excludes_command_environment(self):
        projected = module.project(json.dumps(self.observation()).encode(), self.binding)
        self.assertEqual(projected['reason'], 'direct-exit-unverified')
        self.assertEqual(projected['fault_classes'], ['PackageProcessHeld'])
        self.assertNotIn('argv', projected)
        self.assertNotIn('environment', projected)
        self.assertNotIn('extra', projected)

    def test_foreign_process_observation_refused(self):
        record = self.observation()
        record['test_binding'] = {**self.binding, 'execution_id': '41-1-fresh'}
        with self.assertRaisesRegex(ValueError, 'Foreign'):
            module.project(json.dumps(record).encode(), self.binding)

    def test_collection_does_not_rewrite_hold_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, runs, processes = root/'packet', root/'runs', root/'processes'
            packet.mkdir(); processes.mkdir()
            current = runs/'42-1-fresh'; current.mkdir(parents=True)
            (packet/'CI-SESSION.json').write_text(json.dumps(self.session))
            (packet/'SOURCE.json').write_bytes(self.source)
            state_raw = json.dumps(self.state).encode()
            (current/'admission-state.json').write_bytes(state_raw)
            raw = json.dumps(self.observation()).encode()
            (processes/('operation-' + 'f'*32 + '.json')).write_bytes(raw)
            # Offline fixture paths are not root-owned; trust is tested separately.
            with patch.object(module, 'trusted', side_effect=lambda p, **kw: p):
                result = module.collect(packet, runs, processes, 'fresh', self.github, 'native-runner')
                self.assertEqual(len(result['observations']), 1)
                self.assertEqual(result['observations'][0]['sha256'], hashlib.sha256(raw).hexdigest())
                self.assertFalse(result['holds_cleared'])
                self.assertEqual((current/'admission-state.json').read_bytes(), state_raw)
                with self.assertRaises(FileExistsError):
                    module.collect(packet, runs, processes, 'fresh', self.github, 'native-runner')

    def test_symlink_and_oversized_leaf_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            leaf = Path(tmp)/'record'
            leaf.write_bytes(b'x' * 65537)
            with self.assertRaises(ValueError):
                module.trusted(leaf)
            link = Path(tmp)/'link'
            link.symlink_to(leaf)
            with self.assertRaises(ValueError):
                module.trusted(link)

    def test_workflow_always_retains_original_tar_after_diagnostic_refusal(self):
        text = (ROOT/'.github/workflows/verify-agpc-voice-native-entry.yml').read_text()
        export = text.split('- name: Export only this run')[1].split('- name: Retain CI evidence')[0]
        self.assertIn('if: always()', export)
        self.assertLess(export.index('|| diagnostic_exit=$?'), export.index('sudo tar'))
        self.assertLess(export.index('sudo tar'), export.index('exit "$diagnostic_exit"'))


if __name__ == '__main__':
    unittest.main()
