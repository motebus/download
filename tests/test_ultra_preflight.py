"""Retired provider state is narrowly admitted and bound across the APT lock."""
from pathlib import Path
import subprocess
import unittest
from unittest import mock

SOURCE = (Path(__file__).parents[1] / 'agpc.sh').read_text()
CODE = SOURCE.split("python3 - <<'ULTRA_PREFLIGHT'\n", 1)[1].split('\nULTRA_PREFLIGHT\n', 1)[0]

class UltraPreflightTests(unittest.TestCase):
    def classify(self, record='', status=0):
        with mock.patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], status, record, '')), mock.patch('builtins.print') as output:
            try:
                exec(compile(CODE, 'ultra_preflight', 'exec'), {})
            except SystemExit as e:
                if e.code != 0:
                    raise
            return output.call_args.args[0]

    def test_reviewed_versions_and_retained_configuration(self):
        for version in ('0.1.0-1','0.2.0-1','0.2.1-1','0.2.1-2'):
            for state, label in [('install ok installed','installed'), ('deinstall ok config-files','config-files')]:
                self.assertTrue(self.classify(f'{version}|amd64|{state}\n /etc/mote-mcpd/providers.d/ultra.yaml abc').startswith(label+':'+version+':'))
        self.assertEqual(self.classify('', 1), 'absent')

    def test_unknown_partial_and_query_error_fail_closed(self):
        for record in ('0.2.1-3|amd64|install ok installed','0.2.1-1|arm64|install ok installed','0.2.1-1|amd64|install ok unpacked','garbage'):
            with self.assertRaises(SystemExit): self.classify(record)
        with self.assertRaises(SystemExit): self.classify('', 2)

    def test_metadata_drift_changes_binding(self):
        self.assertNotEqual(self.classify('0.2.1-1|amd64|install ok installed\n file abc'), self.classify('0.2.1-1|amd64|install ok installed\n file def'))
