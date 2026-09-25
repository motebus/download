import subprocess
from pathlib import Path
import unittest
from unittest import mock
from test_publish_apt import publish_apt as p


class GatewayDistributionTest(unittest.TestCase):
    def approved(self):
        return {name: {"version": version, "asset": name + '.deb'} for name, version in
                (("mote-mcpd", "3.3.0-1"), ("mote-secd", "1.1.0-1"))}

    def validate(self, fields, approved=None):
        with mock.patch.object(p, 'package_field', side_effect=lambda asset, field: fields.get(field, '')):
            p.validate_mcp_gateway_dependencies(Path('/unused'), approved or self.approved())

    def test_embedded_gateway_requires_independent_compatible_s(self):
        fields = {'Depends': 'libc6 (>= 2.36), mote-secd (>= 1.1.0-1)',
                  'Breaks': 'mote-mcp-ultra (<< 0.3.0)', 'Replaces': 'mote-mcp-ultra (<< 0.3.0)'}
        self.validate(fields)
        for field, value in [('Depends', 'libc6'), ('Depends', 'mote-secd (>= 1.0.0-1)'),
                             ('Breaks', ''), ('Replaces', ''),
                             ('Recommends', 'mote-mcp-ultra'), ('Suggests', 'inboxd')]:
            with self.subTest(field=field, value=value), self.assertRaises((ValueError, RuntimeError, SystemExit, subprocess.CalledProcessError)):
                self.validate({**fields, field: value})

    def test_retired_bundle_absent_from_new_profile_but_historical_loop_is_preserved(self):
        self.assertNotIn('mote-mcp-ultra', p.AGENT_PROFILE_SPHERE_COMPONENTS)
        self.assertNotIn('mote-mcp-ultra', p.AGENT_PROFILE_REDISTRIBUTABLE)
        self.assertIn('mote-mcp-ultra', p.AGENT_LOOP_SPHERE_COMPONENTS)
        self.assertIn('mote-mcp-ultra', p.AGENT_LOOP_REDISTRIBUTABLE)
        with self.assertRaises((ValueError, RuntimeError, SystemExit, subprocess.CalledProcessError)):
            self.validate({}, {**self.approved(), 'mote-mcp-ultra': {}})
