"""TMP-only session metadata tests; no native runner or package operation."""
import copy
import hashlib
import json
import os
from pathlib import Path
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
