import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import publish_voice_mote as voice
import publish_native as native


class BootstrapTests(unittest.TestCase):
    def shell(self, code):
        return subprocess.run(['bash', '-c', 'source ' + shlex.quote(str(ROOT / 'voice-mote.sh')) + '\n' + code], capture_output=True, text=True)

    def test_help_and_version_do_not_require_root(self):
        for option, expected in [('--help', 'bootstrap'), ('--version', '0.1.0-bootstrap.1')]:
            p = subprocess.run(['bash', str(ROOT / 'voice-mote.sh'), option], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn(expected, p.stdout)

    def test_invalid_arguments_stop_before_platform(self):
        for args in ['--unknown', '--agpc-verify', '--agpc-verify relative']:
            r = self.shell('platform_check() { echo MUTATED; }; main ' + args)
            self.assertNotEqual(r.returncode, 0)
            self.assertNotIn('MUTATED', r.stdout)

    def test_native_readiness_rejects_local_partial_and_malformed_reports(self):
        for report in ['{}', 'invalid', '{"state":"ready-with-gates","live_verified":false}',
                       '{"state":"ready","live_verified":true,"scope":"local-precheck"}',
                       '{"state":"ready","live_verified":"true"}']:
            r = self.shell('printf %s ' + shlex.quote(report) + ' | validate_ready_report')
            self.assertNotEqual(r.returncode, 0, report)
        r = self.shell('printf %s ' + shlex.quote('{"state":"ready","live_verified":true,"scope":"full"}') + ' | validate_ready_report')
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_failed_readiness_never_reaches_package_transaction(self):
        r = self.shell('platform_check() { :; }; verify_agpc() { die "not ready"; }; install_voice() { echo MUTATED; }; main')
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('MUTATED', r.stdout)

    def test_untrusted_checker_cannot_execute(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder, 'checker')
            p.write_text('#!/bin/sh\necho MUTATED\n')
            p.chmod(0o777)
            r = self.shell('agpc_verify=' + shlex.quote(str(p)) + '; verify_agpc')
            self.assertNotEqual(r.returncode, 0)
            self.assertNotIn('MUTATED', r.stdout)

    def test_failed_custom_checker_stops(self):
        r = self.shell('agpc_verify=/approved; trusted_checker() { :; }; timeout() { return 7; }; verify_agpc')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('verification failed', r.stderr)

    def transaction(self, candidate='1.0', audit='', check=True, fail=''):
        return self.shell('''
check_only=%s; assume_yes=true
dpkg() { printf '%%s' %s; }
apt-cache() { printf 'Candidate: %%s\\n' %s; }
apt-get() {
  echo "APT:$*"
  case "$*" in *%s*) %s ;; esac
}
install_voice
''' % ('true' if check else 'false', shlex.quote(audit), shlex.quote(candidate), fail or 'IMPOSSIBLE', 'return 9' if fail else ':'))

    def test_incomplete_dpkg_never_calls_apt(self):
        r = self.transaction(audit='broken package')
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('APT:', r.stdout)

    def test_missing_candidate_never_installs(self):
        r = self.transaction(candidate='(none)')
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('install voice-mote', r.stdout)

    def test_check_only_simulates_without_update_or_install(self):
        r = self.transaction()
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = [x for x in r.stdout.splitlines() if x.startswith('APT:')]
        self.assertEqual(len(calls), 2)
        self.assertIn('--simulate --no-remove install voice-mote', calls[1])
        self.assertNotIn(' update', r.stdout)
        self.assertNotIn('capability verification completed', r.stdout)

    def test_update_failure_never_installs(self):
        r = self.transaction(check=False, fail='update')
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('install voice-mote', r.stdout)

    def test_simulation_failure_never_installs(self):
        r = self.transaction(check=False, fail='--simulate')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout.count('install voice-mote'), 1)


class PublicationTests(unittest.TestCase):
    def test_signed_overlay_preserves_other_downloads(self):
        with tempfile.TemporaryDirectory() as folder:
            site = Path(folder, 'site'); site.mkdir()
            (site / 'agpc.sh').write_bytes(b'existing agpc')
            (site / 'InRelease').write_bytes(b'existing signed index')
            def sign(root, target, names):
                for name in names:
                    (target / (name + '.asc')).write_bytes(b'fixture signature')
            evidence = Path(folder, 'evidence.json')
            with patch.object(native, 'sign_files', side_effect=sign):
                voice.overlay(ROOT, site, evidence)
            self.assertEqual((site / 'agpc.sh').read_bytes(), b'existing agpc')
            self.assertEqual((site / 'InRelease').read_bytes(), b'existing signed index')
            record = json.loads((site / 'voice-mote.source.json').read_text())
            self.assertFalse(record['voice_mote_ready'])
            self.assertFalse(record['runtime_included'])
            self.assertEqual(record['files']['voice-mote.sh']['sha256'], native.file_digest(site / 'voice-mote.sh'))
            self.assertEqual(json.loads(evidence.read_text())['preserved_files'], 2)

    def test_unrelated_change_rejected(self):
        with self.assertRaises(ValueError):
            native.verify_preservation({'agpc.sh': 'a'}, {'agpc.sh': 'b'}, voice.ALLOWED)

    def test_rebuild_workflow_preserves_voice_downloads(self):
        workflow = (ROOT / '.github/workflows/publish-apt.yml').read_text()
        self.assertIn('python3 scripts/publish_voice_mote.py . apt-site', workflow)
        dedicated = (ROOT / '.github/workflows/publish-voice-mote.yml').read_text()
        self.assertIn('group: medge-apt-pages', dedicated)
        self.assertIn('--restore', dedicated)


if __name__ == '__main__':
    unittest.main()
