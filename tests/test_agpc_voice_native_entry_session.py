"""TMP-only session metadata tests; no native runner or package operation."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prepare_agpc_voice_native_entry_session as session


class NativeEntrySessionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.packet = Path(temporary.name) / 'packet'
        self.packet.mkdir(mode=0o755)
        self.commit = 'a' * 40
        self.environment = dict(session.FIXED, GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='2', GITHUB_SHA='b' * 40)
        self.source = dict(schema='agpc.voice-native-entry-ci-source/v1', installer_commit=self.commit,
            files=[], **{k: False for k in ('production_gate', 'published', 'native_acceptance',
                'normal_installer_transaction', 'production_admission', 'historical_L1_admission',
                'secrets_included', 'host_mutated')})
        for name in sorted(session.FILES):
            path = self.packet / name
            path.parent.mkdir(parents=True, exist_ok=True)
            for directory in (path.parent, *path.parent.parents):
                if directory == self.packet or self.packet in directory.parents:
                    directory.chmod(0o755)
            raw = ('offline fixture ' + name).encode()
            path.write_bytes(raw); path.chmod(0o644)
            self.source['files'].append(dict(path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
        self.save_source()
        self.real_lstat = Path.lstat
        self.bad_owner = None

    def save_source(self):
        raw = json.dumps(self.source).encode()
        (self.packet / 'SOURCE.json').write_bytes(raw)
        (self.packet / 'SOURCE.json').chmod(0o644)
        self.manifest_sha = hashlib.sha256(raw).hexdigest()

    def fixture_stat(self, path, *args, **kwargs):
        info = list(self.real_lstat(path, *args, **kwargs))
        info[4] = 123 if path == self.bad_owner else 0
        # Parent /tmp is a test location, not the production fixed ancestry.
        # Within the packet retain real file type/mode/link metadata.
        if path in self.packet.parents:
            info[0] = stat.S_IFDIR | 0o755
        return os.stat_result(info)

    def prepare(self, mode='fresh'):
        with patch.object(session.os, 'geteuid', return_value=0), \
             patch.object(Path, 'lstat', lambda path, **kw: self.fixture_stat(path, **kw)), \
             patch.object(session.platform, 'node', return_value='disposable-fixture'), \
             patch.object(session.time, 'time', return_value=1000):
            return session.prepare(self.packet, mode, self.commit, self.manifest_sha, self.environment)

    def reject(self, reason='.'):
        with self.assertRaisesRegex(ValueError, reason):
            self.prepare()
        self.assertFalse((self.packet / 'CI-SESSION.json').exists())

    def test_exact_root_private_bounded_session_is_generated_once(self):
        result = self.prepare()
        self.assertEqual(result, dict(schema='agpc.voice-native-entry-ci-session/v1',
            scope='inactive-canonical-entry-lifecycle', mode='fresh', github=self.environment,
            host='disposable-fixture', source_commit=self.commit, source_manifest_sha256=self.manifest_sha,
            not_before=1000, expires_at=2800))
        path = self.packet / 'CI-SESSION.json'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(path.read_bytes()), result)
        with self.assertRaisesRegex(ValueError, 'Unexpected file or existing'):
            self.prepare()
        self.assertEqual(json.loads(path.read_bytes()), result)

    def test_upgrade_mode_has_its_own_session_identity(self):
        self.assertEqual(self.prepare('upgrade')['mode'], 'upgrade')

    def test_isolated_predecessor_upgrade_has_a_distinct_session_identity(self):
        result = self.prepare('upgrade-l1-isolation')
        self.assertEqual(result['mode'], 'upgrade-l1-isolation')
        self.assertEqual(json.loads((self.packet / 'CI-SESSION.json').read_bytes()), result)
        self.assertEqual(len(self.source['files']), 13)

    def test_unknown_modes_are_rejected_before_reading_the_bundle(self):
        for mode in (None, True, [], 'rollback', 'upgrade-latest', '../upgrade',
                     'office117.20261015.2+l1isolation.2'):
            with self.subTest(mode=mode), patch.object(session, 'trusted') as trusted:
                with self.assertRaisesRegex(ValueError, 'Exact mode/source/manifest'):
                    self.prepare(mode)
                trusted.assert_not_called()
                self.assertFalse((self.packet / 'CI-SESSION.json').exists())

    def test_workflow_matrix_and_evidence_export_cover_exact_session_modes(self):
        workflow = (ROOT / '.github/workflows/verify-agpc-voice-native-entry.yml').read_text()
        matrix = re.findall(r'^\s+mode: \[([^\]]+)\]$', workflow, re.MULTILINE)
        export = re.findall(r'case "\$TEST_MODE" in ([^\)]+)\)', workflow)
        self.assertEqual(len(matrix), 1)
        self.assertEqual(len(export), 1)
        modes = ('fresh', 'upgrade', 'upgrade-l1-isolation')
        self.assertEqual(session.MODES, modes)
        self.assertEqual(tuple(item.strip() for item in matrix[0].split(',')), modes)
        self.assertEqual(tuple(export[0].split('|')), modes)

    def test_neither_predecessor_may_be_missing_from_the_root_bundle(self):
        original = copy.deepcopy(self.source)
        for filename in ('agpc-voice_0.1.0~office117.20261015.2+l1isolation.2+sipauth.1+radio909.1+continuous117.1_all.deb',
                         'agpc-voice_0.1.0~office117.20261015.2+l1isolation.2_all.deb'):
            with self.subTest(filename=filename):
                self.source = copy.deepcopy(original)
                self.source['files'] = [record for record in self.source['files']
                                        if record['path'] != 'packages/' + filename]
                self.save_source()
                self.reject('Exact session bundle')

    def test_old_or_untrusted_workflow_context_is_rejected(self):
        for key, value in [('GITHUB_REF', 'refs/heads/feature'), ('RUNNER_ENVIRONMENT', 'self-hosted'),
                           ('GITHUB_RUN_ID', '0'), ('GITHUB_RUN_ATTEMPT', '../1'), ('GITHUB_SHA', 'main'),
                           ('GITHUB_WORKFLOW_REF', session.FIXED['GITHUB_WORKFLOW_REF'].replace('-entry.yml', '.yml'))]:
            with self.subTest(key=key), patch.dict(self.environment, {key: value}):
                self.reject('workflow context')

    def test_source_hash_and_root_copied_files_are_rechecked(self):
        with patch.object(self, 'manifest_sha', 'f' * 64):
            self.reject('manifest differs')
        (self.packet / 'agpc-voice.sh').write_bytes(b'replaced after staging')
        self.reject('bundle differs')

    def test_changed_source_identity_or_acceptance_claim_fails(self):
        for field, value in [('installer_commit', 'b' * 40), ('production_gate', True),
                             ('normal_installer_transaction', True)]:
            original = copy.deepcopy(self.source)
            self.source[field] = value
            self.save_source()
            self.reject('Closed source')
            self.source = original

    def test_symlink_hardlink_permissions_and_ownership_fail_closed(self):
        path = self.packet / 'agpc-voice.sh'
        original = path.read_bytes()
        target = self.packet / 'other'
        path.rename(target); path.symlink_to(target)
        self.reject('Untrusted')
        path.unlink(); target.rename(path)
        os.link(path, target)
        self.reject('regular file')
        target.unlink()
        path.chmod(0o666)
        self.reject('Untrusted')
        path.chmod(0o644)
        self.bad_owner = path
        self.reject('Untrusted')
        self.assertEqual(path.read_bytes(), original)

    def test_extra_file_and_traversal_record_cannot_enter_session(self):
        extra = self.packet / 'private-config'
        extra.write_bytes(b'fixture')
        extra.chmod(0o644)
        self.reject('Unexpected file')
        extra.unlink()
        self.source['files'][0]['path'] = '../outside'
        self.save_source()
        self.reject('Exact session bundle')


if __name__ == '__main__':
    unittest.main()
