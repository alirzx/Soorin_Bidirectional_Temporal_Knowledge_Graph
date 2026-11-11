import unittest
from soorin.ops.models import smoke
from soorin.services.cpu_models import MODELS

class SmokeTests(unittest.TestCase):
    def test_smoke_validates_revision_dimension_repeatability_and_local_origin(self):
        def request(path,body=None):
            if path=='/ready':return {'ready':True,'model':'@'.join(MODELS['embedding'])}
            return {'data':[{'embedding':[1.0]+[0.0]*1023},{'embedding':[0.0,1.0]+[0.0]*1022}]}
        result=smoke('embedding','http://127.0.0.1:2811',request=request)
        self.assertTrue(result['repeatable'])
        self.assertEqual(result['dimension'],1024)
        for url in ['https://external.example','http://user:secret@localhost:2811','http://localhost:2811?token=secret']:
            with self.assertRaises(ValueError):smoke('embedding',url,request=request)
        def wrong(path,body=None):
            return request(path) if path=='/ready' else {'data':[{'embedding':[1.0]}]}
        with self.assertRaises(ValueError):smoke('embedding','http://127.0.0.1:2811',request=wrong)
