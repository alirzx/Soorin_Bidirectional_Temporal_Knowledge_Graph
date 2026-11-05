import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from soorin.services.artifacts import verify, snapshot_path
from soorin.services.cpu_models import MODELS, initialize


class ArtifactTests(unittest.TestCase):
    def test_missing_and_partial_cache_is_preserved_without_loading(self):
        with tempfile.TemporaryDirectory() as cache, patch('soorin.services.cpu_models.Engine.load', side_effect=AssertionError('weights forbidden')):
            root = snapshot_path(cache, *MODELS['ner'])
            blobs = root.parent.parent / 'blobs'
            blobs.mkdir(parents=True)
            (blobs / 'partial.incomplete').write_bytes(b'synthetic')
            result = verify('ner', cache)
            self.assertEqual(result['status'], 'MODEL_ARTIFACT_DOWNLOAD_INCOMPLETE')
            self.assertEqual(result['partial_blobs_preserved'], 1)
            self.assertTrue((blobs / 'partial.incomplete').exists())

    def test_manifest_size_hash_and_identity_checks(self):
        import hashlib
        with tempfile.TemporaryDirectory() as cache:
            root = snapshot_path(cache, *MODELS['ner'])
            root.mkdir(parents=True)
            files = []
            for name in ['config.json', 'tokenizer_config.json', 'tokenizer.json', 'model.safetensors']:
                (root / name).write_bytes(b'synthetic')
                files.append({'path': name, 'size': 9, 'sha256': hashlib.sha256(b'synthetic').hexdigest()})
            model, revision = MODELS['ner']
            manifest = root / 'soorin-artifacts-v1.json'
            manifest.write_text(json.dumps({'model': model, 'revision': revision, 'files': files}))
            self.assertEqual(verify('ner', cache, hashes=True)['status'], 'PASS')
            (root / 'model.safetensors').write_bytes(b'corrupted')
            self.assertIn('checksum:model.safetensors', verify('ner', cache, hashes=True)['issues'])

    def test_legacy_init_is_download_only(self):
        with patch('soorin.services.artifacts.download', return_value={'cache': '/synthetic'}) as mock, patch('soorin.services.cpu_models.Engine.load', side_effect=AssertionError('weights forbidden')):
            self.assertEqual(initialize('ner', '/cache'), '/synthetic')
            mock.assert_called_once_with('ner', '/cache')
