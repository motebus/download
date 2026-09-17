"""Validate embedded bootstrap code without changing Windows or Linux."""
import ast
import configparser
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).parents[1]

def scripts():
    for name in ('agpc-win.ps1', 'agpc.ps1'):
        text = (ROOT / name).read_text()
        for label, shell in re.findall(r"\$script:(\w+Linux) = @'\n(.*?)\n'@", text, re.S):
            yield name, label, shell

class WindowsEmbeddedCodeTests(unittest.TestCase):
    def test_embedded_bash_and_python_parse(self):
        found = []
        for name, label, shell in scripts():
            found.append((name, label))
            with self.subTest(script=name, section=label):
                subprocess.run(['bash', '-n'], input=shell, text=True, check=True)
                for python in re.findall(r"<<'PY'\n(.*?)\nPY", shell, re.S):
                    ast.parse(python)
        self.assertEqual(found, [('agpc-win.ps1', 'PrepareLinux'),
                                 ('agpc-win.ps1', 'InstallLinux'),
                                 ('agpc.ps1', 'UpdateLinux')])

    def test_systemd_edit_preserves_existing_configuration_and_is_idempotent(self):
        shell = next(shell for _, label, shell in scripts() if label == 'PrepareLinux')
        code = re.findall(r"<<'PY'\n(.*?)\nPY", shell, re.S)[0]
        cases = [
            ('', '[boot]\nsystemd=true'),
            ('[boot]\nsystemd=false\n[automount]\nenabled=false\n', 'enabled=false'),
            ('# retained\n[boot]\n# option\n[interop]\nenabled=true\n', '# retained'),
            ('[network]\ngenerateHosts=false\n[boot]\nsystemd=false', 'generateHosts=false'),
            ('[boot]\ncommand=echo-ready', 'command=echo-ready'),
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'wsl.conf'
            selected = code.replace("p=Path('/etc/wsl.conf')", "p=Path(" + repr(str(path)) + ")")
            for source, preserved in cases:
                with self.subTest(source=source):
                    path.write_text(source)
                    exec(compile(selected, 'wsl-config', 'exec'), {})
                    result = path.read_text()
                    parsed = configparser.ConfigParser()
                    parsed.read_string(result)
                    self.assertEqual(parsed['boot']['systemd'], 'true')
                    self.assertIn(preserved, result)
                    exec(compile(selected, 'wsl-config', 'exec'), {})
                    self.assertEqual(path.read_text(), result)
