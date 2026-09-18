import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ContainerOptionsTests(unittest.TestCase):
    def test_runtime_never_uses_privileged_host_access(self):
        options = json.loads((ROOT / 'scripts/agpc-ubuntu/runtime-options.json').read_text())
        args = options['docker_run_args']
        self.assertEqual(args[args.index('--cgroupns') + 1], 'private')
        self.assertIn('writable-cgroups=true', args)
        self.assertIn('no-new-privileges=true', args)
        self.assertFalse(options['privileged'])
        for key in ('host_mounts', 'cap_add', 'published_ports'):
            self.assertEqual(options[key], [])
        for forbidden in ('--privileged', '--cap-add', '-v', '--volume', '--mount', '--pid', '--network', '-p'):
            self.assertNotIn(forbidden, args)
        self.assertEqual(options['required_cgroup_version'], '2')


if __name__ == '__main__':
    unittest.main()
