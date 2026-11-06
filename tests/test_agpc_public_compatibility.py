"""New Core publication support retains the older public profile contracts."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import agpc_profiles
import publish_agpc_apt
import publish_apt
import validate_agent_sphere_apt
import test_agpc_native_publication as historical
import test_agpc_core_profiles as core_fixture

ROOT = Path(__file__).resolve().parents[1]


class PublicCompatibilityTests(unittest.TestCase):
    def test_current_root_uses_exact_legacy_inventory_and_alias_validation(self):
        record = publish_apt.validate_agent_apps_installer(ROOT)
        self.assertEqual((record['schema'], record['tag']), ('agpc-installer-source/v2', 'v0.3.0-46'))
        self.assertEqual(publish_apt.agent_installer_files(ROOT), publish_apt.AGENT_INSTALLER_FILES)
        self.assertEqual(agpc_profiles.profile_files(ROOT), agpc_profiles.LEGACY_PROFILE_FILES)
        self.assertNotIn('agpc-mesh.sh', publish_apt.agent_installer_files(ROOT))

    def test_legacy_aliases_cannot_activate_a_modern_cohort(self):
        fixture = historical.ProfilePublicationTests('test_completed_signed_cohort_binds_distinct_standard_and_full')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for schema in ('agent-computer-apt-overlay/v8', 'agent-computer-apt-overlay/v12',
                       'agent-computer-apt-overlay/v13'):
            with self.subTest(schema=schema):
                fixture.config['schema'] = schema
                (fixture.site / 'agent-computer-apt-overlay.json').write_text(json.dumps(fixture.config))
                with self.assertRaisesRegex(ValueError, 'activated'):
                    fixture.activate()

    def test_historical_index_retains_its_exact_transition_package(self):
        data = b'Package: agent-apps\nVersion: 0.3.0-1\n\nPackage: agpc-core\nVersion: fixture\n\n'
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            path = site / 'dists/stable/main/binary-amd64'; path.mkdir(parents=True)
            for retire in (False, True):
                with self.subTest(retire=retire), patch.object(publish_agpc_apt.subprocess, 'check_output',
                                                              side_effect=[data, b'fixture release']):
                    publish_agpc_apt.index(site, retire_packages=retire)
                    actual = (path / 'Packages').read_bytes()
                    self.assertEqual(b'Package: agent-apps\n' in actual, not retire)
                    self.assertIn(b'Package: agpc-core\n', actual)

    def test_full_solver_selects_schema_owned_ultra_root(self):
        old = {'schema': publish_apt.AGENT_COMPUTER_PROFILE_SCHEMA}
        new = {'schema': publish_apt.AGENT_COMPUTER_ULTRA_SCHEMA}
        self.assertIn('install agent-sphere agent-ultra ', validate_agent_sphere_apt.profile_simulation(old, full=True))
        self.assertIn('install agent-sphere agpc-ultra ', validate_agent_sphere_apt.profile_simulation(new, full=True))

    def test_legacy_aggregate_tag_still_must_equal_public_source(self):
        config = json.loads((ROOT / publish_apt.AGENT_COMPUTER_OVERLAY_FILE).read_text())
        self.assertEqual(config['schema'], publish_apt.AGENT_COMPUTER_PROFILE_SCHEMA)
        metadata = {'tagName': config['release']['tag'], 'isDraft': False,
                    'assets': [{'name': item['asset']} for item in publish_apt.overlay_packages(config)]}
        original_run = publish_apt.run
        def gh(*args, **kwargs):
            if args[0] == 'dpkg': return original_run(*args, **kwargs)
            return json.dumps(metadata if args[:3] == ('gh', 'release', 'view') else {'sha': 'f' * 40})
        with tempfile.TemporaryDirectory() as directory, patch.object(publish_apt, 'run', side_effect=gh) as calls:
            with self.assertRaisesRegex(publish_apt.PublishError, 'source commit'):
                publish_apt.download_agent_computer_overlay(ROOT, Path(directory) / 'download')
            self.assertEqual(len([c for c in calls.call_args_list if c.args[0] == 'gh']), 2)
            self.assertIn('/commits/', calls.call_args_list[-1].args[-1])

    def test_modern_cohort_uses_canonical_provenance_exact_assets_and_actual_hashes(self):
        config = core_fixture.config_fixture()
        metadata = {'tagName': config['release']['tag'], 'isDraft': False,
                    'assets': [{'name': item['asset']} for item in publish_apt.overlay_packages(config)]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def write_config(value):
                (root / publish_apt.AGENT_COMPUTER_OVERLAY_FILE).write_text(json.dumps(value))
            write_config(config)
            original_run = publish_apt.run
            def gh(*args, **kwargs):
                if args[0] == 'dpkg': return original_run(*args, **kwargs)
                if args[:3] == ('gh', 'release', 'view'): return json.dumps(metadata)
                self.assertEqual(args[:3], ('gh', 'release', 'download'))
                destination = Path(args[args.index('--dir') + 1])
                for item in publish_apt.overlay_packages(config):
                    (destination / item['asset']).write_bytes(b'tampered original package')
                return ''
            with patch.object(publish_apt, 'run', side_effect=gh) as calls:
                with self.assertRaisesRegex(publish_apt.PublishError, 'digest mismatch'):
                    publish_apt.download_agent_computer_overlay(root, root / 'bad-bytes')
                self.assertTrue(all('/commits/' not in ' '.join(call.args) for call in calls.call_args_list))
            metadata['assets'].pop()
            with patch.object(publish_apt, 'run', side_effect=gh) as calls:
                with self.assertRaisesRegex(publish_apt.PublishError, 'missing an approved asset'):
                    publish_apt.download_agent_computer_overlay(root, root / 'missing-asset')
                self.assertEqual(len([c for c in calls.call_args_list if c.args[0] == 'gh']), 1)
            bad = copy.deepcopy(config)
            bad['release']['packages'][0]['provenance']['build_status'] = 'failed'
            write_config(bad)
            with patch.object(publish_apt, 'run', wraps=publish_apt.run) as calls:
                with self.assertRaisesRegex(publish_apt.PublishError, 'successful main CI'):
                    publish_apt.download_agent_computer_overlay(root, root / 'bad-provenance')
                self.assertTrue(all(call.args[0] != 'gh' for call in calls.call_args_list))
