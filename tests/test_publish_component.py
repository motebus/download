import copy
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('publish_component', Path(__file__).resolve().parents[1] / 'scripts/publish_component.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class ReviewedPublication(unittest.TestCase):
    def setUp(self):
        self.tag = 'cx-mesh-v2.0.0-1'
        self.record = {'schema':'reviewed-native-publication/v1','tag':self.tag,
                       'public_source_commit':'a'*40,'title':'CX Mesh','notes':'Reviewed candidate',
                       'assets':[{'name':'cx-mesh_2.0.0-1_amd64.deb','sha256':'b'*64,
                                  'source_tag':'candidate-cx-mesh-v2.0.0-1'}]}

    def test_exact_record(self):
        module.validate(self.record, self.tag)

    def test_unsafe_or_unbound_assets(self):
        for key, value in [('name','../payload.deb'),('name','payload*'),('sha256','bad'),
                           ('source_tag',self.tag),('source_tag','../release')]:
            with self.subTest(key=key,value=value):
                changed = copy.deepcopy(self.record)
                changed['assets'][0][key] = value
                with self.assertRaises(AssertionError):module.validate(changed,self.tag)
        self.record['assets'] *= 2
        with self.assertRaises(AssertionError):module.validate(self.record,self.tag)

    def test_wrong_tag_or_unknown_fields(self):
        with self.assertRaises(AssertionError):module.validate(self.record,'cx-mesh-v9.0.0-1')
        self.record['command'] = 'unreviewed'
        with self.assertRaises(AssertionError):module.validate(self.record,self.tag)

    def context(self):
        return {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'motebus/download',
                'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
                'GITHUB_WORKFLOW_REF': 'motebus/download/.github/workflows/publish-component.yml@refs/heads/main',
                'GITHUB_SHA': 'c'*40}

    def current_record(self):
        record = copy.deepcopy(self.record)
        record.update(schema='reviewed-native-publication/v2', public_source_commit='GITHUB_SHA')
        return record

    def test_current_workflow_commit_is_exact_and_not_a_moving_ref(self):
        record = self.current_record()
        module.validate(record, self.tag)
        self.assertEqual(module.public_source_commit(record, self.context()), 'c'*40)

    def test_current_workflow_rejects_forks_branches_events_and_missing_context(self):
        for key, value in [('GITHUB_ACTIONS', 'false'), ('GITHUB_REPOSITORY', 'fork/download'),
                           ('GITHUB_REF', 'refs/heads/feature'), ('GITHUB_EVENT_NAME', 'pull_request'),
                           ('GITHUB_WORKFLOW_REF', 'motebus/download/.github/workflows/other.yml@refs/heads/main'),
                           ('GITHUB_SHA', 'main'), ('GITHUB_SHA', '')]:
            with self.subTest(key=key, value=value):
                context = self.context()
                context[key] = value
                with self.assertRaises(AssertionError):module.public_source_commit(self.current_record(), context)
        with self.assertRaises(AssertionError):module.public_source_commit(self.current_record(), {})

    def test_v2_requires_explicit_workflow_commit_policy(self):
        for value in ['main', 'refs/heads/main', 'a'*40, None]:
            with self.subTest(value=value):
                record = self.current_record()
                record['public_source_commit'] = value
                with self.assertRaises(AssertionError):module.validate(record, self.tag)

    def test_existing_v1_exact_commit_is_preserved(self):
        self.assertEqual(module.public_source_commit(self.record, {}), 'a'*40)

    def test_public_main_movement_stops_before_publication(self):
        with mock.patch.object(module, 'run', return_value='{"commit":{"sha":"' + 'c'*40 + '"}}'):
            module.check_public_main('c'*40)
        with mock.patch.object(module, 'run', return_value='{"commit":{"sha":"' + 'd'*40 + '"}}'):
            with self.assertRaises(AssertionError):module.check_public_main('c'*40)
