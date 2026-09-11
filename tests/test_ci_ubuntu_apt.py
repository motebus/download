"""Mirror selection preserves APT trust, suites and non-Ubuntu sources."""
from pathlib import Path
import subprocess
import tempfile
import unittest

HELPER = Path(__file__).parents[1] / 'scripts/configure-ci-ubuntu-apt.sh'


class CiAptTest(unittest.TestCase):
    def test_deb822_and_list_preserve_trust_and_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = root / 'etc/apt/sources.list.d'; sources.mkdir(parents=True)
            original = ('Types: deb\nURIs: https://archive.ubuntu.com/ubuntu\n'
                        'Suites: noble noble-updates\nComponents: main universe\n'
                        'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n')
            ubuntu = sources / 'ubuntu.sources'; ubuntu.write_text(original)
            legacy = root / 'etc/apt/sources.list'
            legacy.write_text('deb http://security.ubuntu.com/ubuntu noble-security main\n')
            other = sources / 'agpc.sources'
            signed = 'Types: deb\nURIs: file:/repo\nSigned-By: /repo/medge-archive-keyring.gpg\n'
            other.write_text(signed)
            subprocess.run(['bash', str(HELPER), str(root)], check=True, capture_output=True)
            self.assertEqual(ubuntu.read_text(), original.replace('archive.ubuntu.com', 'azure.archive.ubuntu.com'))
            self.assertEqual(legacy.read_text(), 'deb http://azure.archive.ubuntu.com/ubuntu noble-security main\n')
            self.assertEqual(other.read_text(), signed)
            config = (root / 'etc/apt/apt.conf.d/99-agpc-ci-downloads').read_text()
            self.assertIn('Acquire::http::Timeout "30";', config)
            self.assertNotIn('AllowInsecure', config)
            self.assertNotIn('Unauthenticated', config)


if __name__ == '__main__':
    unittest.main()
