import copy
import importlib.util
from pathlib import Path
import unittest

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
