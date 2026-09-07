import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = (Path(__file__).parents[1] / 'sphere.sh').read_text()
REPAIR = SCRIPT.split("<<'PY_EDGE_REPAIR'\n", 1)[1].split('\nPY_EDGE_REPAIR', 1)[0]
FUNCTION = SCRIPT.split('repair_edge_signing_key() {', 1)[1].split('\n}\n\nif ! apt-get', 1)[0]
ERROR = SCRIPT.split("<<'PY_EDGE_ERROR'\n", 1)[1].split('\nPY_EDGE_ERROR', 1)[0]
KEY = '/etc/apt/keyrings/microsoft-edge.gpg'
EDGE = 'https://packages.microsoft.com/repos/edge/'


class EdgeAptRepairTest(unittest.TestCase):
    def setUp(self):
        self.previous_umask = os.umask(0o022)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.parts = self.root / 'etc/apt/sources.list.d'
        self.parts.mkdir(parents=True)
        self.key = self.root / 'verified.gpg'
        self.key.write_bytes(b'verified-key-fixture')

    def tearDown(self):
        self.temp.cleanup()
        os.umask(self.previous_umask)

    def repair(self):
        return subprocess.run([sys.executable, '-', str(self.root), str(self.key)],
                              input=REPAIR, text=True, capture_output=True)

    def test_list_source_is_scoped_backed_up_and_repeatable(self):
        source = self.parts / 'microsoft-edge.list'
        original = '# Edge\ndeb [arch=amd64 signed-by=/missing.gpg] ' + EDGE + ' stable main\n'
        unrelated = 'deb https://example.invalid/ubuntu noble main\n'
        source.write_text(original + unrelated)
        result = self.repair()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(source.read_text(), '# Edge\ndeb [arch=amd64 signed-by=' + KEY + '] ' + EDGE + ' stable main\n' + unrelated)
        self.assertEqual((self.root / KEY.lstrip('/')).read_bytes(), self.key.read_bytes())
        backup = next((self.root / 'var/backups').iterdir())
        self.assertEqual((backup / '1').read_text(), original + unrelated)
        revised = source.read_bytes()
        self.assertEqual(self.repair().returncode, 0)
        self.assertEqual(source.read_bytes(), revised)

    def test_deb822_replaces_inline_key_and_preserves_other_stanza(self):
        source = self.parts / 'microsoft-edge.sources'
        other = 'Types: deb\nURIs: https://example.invalid/repo\nSuites: noble\nComponents: main\nSigned-By: /other.gpg\n'
        source.write_text('Types: deb\nURIs: ' + EDGE + '\nSuites: stable\nComponents: main\n'
                          'Signed-By: -----BEGIN PGP PUBLIC KEY BLOCK-----\n .\n old-key\n -----END PGP PUBLIC KEY BLOCK-----\n\n' + other)
        result = self.repair()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Signed-By: ' + KEY, source.read_text())
        self.assertNotIn('old-key', source.read_text())
        self.assertTrue(source.read_text().endswith(other))

    def test_unsafe_or_unrelated_sources_are_not_modified(self):
        for content in [
            '# deb ' + EDGE + ' stable main\n',
            'deb https://example.invalid/repo stable main\n',
            'deb [trusted=yes] ' + EDGE + ' stable main\n',
            'Types: deb\nURIs: ' + EDGE + '\nSuites: stable\nEnabled: no\nComponents: main\n',
            'Types: deb\nURIs: ' + EDGE + ' https://other.invalid\nSuites: stable\nComponents: main\n',
            'Types: deb\nURIs: ' + EDGE + '\nSuites: stable\nTrusted: yes\nComponents: main\n',
        ]:
            with self.subTest(content=content):
                source = self.parts / ('edge.sources' if content.startswith('Types:') else 'edge.list')
                source.write_text(content)
                result = self.repair()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(source.read_text(), content)
                self.assertFalse((self.root / KEY.lstrip('/')).exists())
                source.unlink()

    def test_symlink_or_writable_source_is_rejected_before_key_change(self):
        outside = self.root / 'outside'
        outside.write_text('deb ' + EDGE + ' stable main\n')
        source = self.parts / 'edge.list'
        source.symlink_to(outside)
        self.assertNotEqual(self.repair().returncode, 0)
        source.unlink()
        source.write_bytes(outside.read_bytes())
        source.chmod(0o666)
        self.assertNotEqual(self.repair().returncode, 0)
        self.assertFalse((self.root / KEY.lstrip('/')).exists())

    def test_wrong_fingerprint_or_invalid_signature_never_reaches_source_mutation(self):
        wrapper = r'''
set -euo pipefail
curl() { return 0; }
gpg() {
  if [[ " $* " == *' --show-keys '* ]]; then
    printf 'pub:::::::::\nfpr:::::::::%s:\n' "$TEST_FINGERPRINT"
  fi
}
gpgv() { return "$TEST_SIGNATURE_STATUS"; }
python3() { printf MUTATED >"$TEMP_DIR/mutation"; }
repair_edge_signing_key() {
''' + FUNCTION + '\n}\nrepair_edge_signing_key\n'
        for fingerprint, status in [('WRONG', '0'), ('BC528686B50D79E339D3721CEB3E94ADBE1229CF', '1')]:
            with self.subTest(fingerprint=fingerprint):
                result = subprocess.run(['bash'], input=wrapper, text=True, capture_output=True,
                                        env={**os.environ, 'TEMP_DIR': str(self.root),
                                             'TEST_FINGERPRINT': fingerprint, 'TEST_SIGNATURE_STATUS': status})
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / 'mutation').exists())

    def test_only_edge_signature_errors_trigger_repair_on_both_ubuntu_versions(self):
        for prefix in ['GPG error', 'OpenPGP signature verification failed']:
            for url, expected in [(EDGE, 0), ('https://other.invalid/repo', 1)]:
                log = self.root / 'apt.log'
                log.write_text(f'W: {prefix}: {url} stable InRelease: NO_PUBKEY example\n')
                result = subprocess.run([sys.executable, '-', str(log)], input=ERROR, text=True)
                self.assertEqual(result.returncode, expected)


if __name__ == '__main__':
    unittest.main()
