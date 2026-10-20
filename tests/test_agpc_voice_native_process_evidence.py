"""Diagnostic binding and non-interference checks; no native package execution."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('voice_process_diagnostics',
    ROOT / 'scripts/collect_agpc_voice_native_process_evidence.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProcessEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.source = b'{"source":"fixture"}\n'
        self.github = dict(module.FIXED, GITHUB_RUN_ID='42', GITHUB_RUN_ATTEMPT='1',
                           GITHUB_SHA='a' * 40)
        self.session = dict(schema='agpc.voice-native-entry-ci-session/v1', mode='fresh',
            host='native-runner', github=self.github, source_commit='b' * 40,
            source_manifest_sha256=hashlib.sha256(self.source).hexdigest())
        self.state = dict(self.session, execution_id='42-1-fresh',
            runtime_sha256={str(i): 'c' * 64 for i in range(6)},
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
