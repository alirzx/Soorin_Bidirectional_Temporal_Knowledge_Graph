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

    def test_download_uses_metadata_and_cache_without_model_runtime(self):
        from types import SimpleNamespace
        from soorin.services.artifacts import download
        with tempfile.TemporaryDirectory() as cache:
            model, revision = MODELS['ner']
            root = snapshot_path(cache, model, revision)
            root.mkdir(parents=True)
            rows = []
            for name in ['config.json', 'tokenizer_config.json', 'tokenizer.json', 'model.safetensors']:
                (root / name).write_bytes(b'synthetic')
                rows.append(SimpleNamespace(rfilename=name, size=9, lfs=None, blob_id=None))
            calls = []
            fake = SimpleNamespace(HfApi=lambda: SimpleNamespace(model_info=lambda *a, **k: SimpleNamespace(sha=revision, siblings=rows)),
                                   snapshot_download=lambda *a, **k: calls.append(k) or str(root))
            with patch.dict('sys.modules', {'huggingface_hub': fake}), patch('soorin.services.cpu_models.Engine.load', side_effect=AssertionError('weights forbidden')):
                self.assertEqual(download('ner', cache)['status'], 'PASS')
            self.assertEqual(calls[0]['revision'], revision)
            self.assertNotIn('pytorch_model.bin', calls[0]['allow_patterns'])

    def test_transient_transfer_retry_reuses_pinned_cache(self):
        from soorin.services.artifacts import download
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as cache:
            model, revision = MODELS['ner']
            root = snapshot_path(cache, model, revision)
            root.mkdir(parents=True)
            rows = []
            for name in ('config.json', 'tokenizer_config.json', 'tokenizer.json', 'model.safetensors'):
                (root / name).write_bytes(b'synthetic')
                rows.append(SimpleNamespace(rfilename=name, size=9, lfs=None, blob_id=None))
            calls = []
            def flaky_snapshot(*args, **kwargs):
                calls.append(kwargs)
                if len(calls) == 1:
                    raise TimeoutError('synthetic CDN timeout')
                return str(root)
            hub = SimpleNamespace(HfApi=lambda: SimpleNamespace(
                model_info=lambda *a, **kw: SimpleNamespace(sha=revision, siblings=rows)),
                snapshot_download=flaky_snapshot)
            with patch.dict('sys.modules', {'huggingface_hub': hub}), \
                 patch('soorin.services.artifacts.time.sleep') as sleep, \
                 patch.dict('os.environ', {'SOORIN_HF_RETRIES': '2'}):
                self.assertEqual(download('ner', cache)['status'], 'PASS')
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(c['revision'] == revision and c['cache_dir'] == cache for c in calls))
            sleep.assert_called_once_with(5)

    def test_non_transient_download_error_does_not_retry(self):
        from soorin.services.artifacts import _bounded_attempts
        with patch('soorin.services.artifacts.time.sleep') as sleep:
            with self.assertRaisesRegex(ValueError, 'artifact_revision_mismatch'):
                _bounded_attempts('snapshot', lambda: (_ for _ in ()).throw(
                    ValueError('artifact_revision_mismatch')))
            sleep.assert_not_called()

    def test_retries_are_explicitly_bounded(self):
        from soorin.services.artifacts import _bounded_attempts
        with patch.dict('os.environ', {'SOORIN_HF_RETRIES': '99'}):
            with self.assertRaisesRegex(ValueError, 'between 0 and 8'):
                _bounded_attempts('metadata', lambda: None)

    def test_malformed_manifest_is_not_certified(self):
        with tempfile.TemporaryDirectory() as cache:
            root = snapshot_path(cache, *MODELS['ner'])
            root.mkdir(parents=True)
            (root / 'soorin-artifacts-v1.json').write_text('[]')
            self.assertNotEqual(verify('ner', cache)['status'], 'PASS')
