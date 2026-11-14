"""Pinned artifact preparation. This module never imports an inference runtime."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import time


def snapshot_path(cache: str, model: str, revision: str) -> Path:
    return Path(cache) / ('models--' + model.replace('/', '--')) / 'snapshots' / revision


def verify(role: str, cache: str, *, hashes: bool = False) -> dict:
    from .cpu_models import MODELS
    model, revision = MODELS[role]
    root = snapshot_path(cache, model, revision)
    manifest_path = root / 'soorin-artifacts-v1.json'
    issues = []
    files = []
    manifest = None
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text())
            if not isinstance(manifest, dict):
                raise ValueError('invalid_manifest')
            if (manifest.get('model'), manifest.get('revision')) != (model, revision):
                issues.append('manifest_identity_mismatch')
        except (ValueError, OSError):
            issues.append('manifest_invalid')
    else:
        issues.append('manifest_missing')
    required = ['config.json', 'tokenizer_config.json']
    if role == 'embedding':
        required += ['modules.json', '1_Pooling/config.json']
    for name in required:
        if not (root / name).is_file():
            issues.append('missing:' + name)
    if not any((root / name).is_file() for name in ('tokenizer.json', 'vocab.txt', 'sentencepiece.bpe.model')):
        issues.append('tokenizer_missing')
    if not any(root.glob('*.safetensors')) and not (root / 'pytorch_model.bin').is_file():
        issues.append('weights_missing')
    entries = manifest.get('files', []) if isinstance(manifest, dict) else []
    if not entries:
        issues.append('manifest_files_missing')
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        issues.append('manifest_entries_invalid')
        entries = []
    listed = {entry.get('path') for entry in entries if isinstance(entry.get('path'), str)}
    for name in required:
        if name not in listed:
            issues.append('manifest_omits:' + name)
    for path in root.glob('*.safetensors'):
        if path.name not in listed:
            issues.append('manifest_omits:' + path.name)
    if not any(name.endswith(('.safetensors', '.bin')) for name in listed):
        issues.append('manifest_weights_missing')
    for entry in entries:
        name = entry.get('path', '')
        path = root / name
        if not isinstance(name, str) or not name or Path(name).is_absolute() or '..' in Path(name).parts:
            issues.append('manifest_path_invalid')
            continue
        size = path.stat().st_size if path.is_file() else 0
        if not size or size != entry.get('size'):
            issues.append('size_or_missing:' + name)
        digest = entry.get('sha256')
        git_digest = entry.get('git_blob_sha1')
        if hashes and digest and size:
            with path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != digest:
                issues.append('checksum:' + name)
        if hashes and git_digest and not digest and size:
            h = hashlib.sha1(('blob ' + str(size) + '\0').encode())
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(block)
            if h.hexdigest() != git_digest:
                issues.append('checksum:' + name)
        files.append({'path': name, 'bytes': size, 'checksum_available': bool(digest or git_digest)})
    if not entries and root.is_dir():
        files = [{'path': str(path.relative_to(root)), 'bytes': path.stat().st_size,
                  'checksum_available': False} for path in sorted(root.rglob('*')) if path.is_file()]
    incomplete = sum(1 for _ in (root.parent.parent / 'blobs').glob('*.incomplete'))
    return {'stage': 'artifact_integrity', 'role': role, 'model': model, 'revision': revision,
            'cache': str(root), 'status': ('PASS' if not issues else 'MODEL_ARTIFACT_DOWNLOAD_INCOMPLETE' if any(i.startswith(('missing:', 'weights_missing', 'tokenizer_missing', 'size_or_missing:')) for i in issues) else 'ARTIFACT_VERIFICATION_INCOMPLETE'),
            'hashes_checked': hashes, 'files': files, 'issues': issues,
            'partial_blobs_preserved': incomplete, 'model_loading': 'NOT RUN', 'model_inference': 'NOT RUN'}


def _retryable_download_error(exc: Exception) -> bool:
    """Retry transient Hub/CDN failures, never auth, bad pins, or bad inputs."""
    from requests.exceptions import RequestException
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if isinstance(exc, RequestException):
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        return status is None or status in {408, 429, 500, 502, 503, 504}
    # hf-xet's Rust client may surface its network failures as RuntimeError.
    # Restrict these retries to known transient transfer diagnostics.
    if isinstance(exc, RuntimeError):
        message = str(exc).lower()
        return any(term in message for term in (
            'timed out', 'timeout', 'connection reset', 'connection error',
            'network error', 'dns error', 'too many requests', 'service unavailable',
            'http 429', 'http 502', 'http 503', 'http 504'))
    return False


def _bounded_attempts(name: str, fn):
    try:
        retries = int(os.environ.get('SOORIN_HF_RETRIES', '3'))
    except ValueError as exc:
        raise ValueError('SOORIN_HF_RETRIES must be an integer') from exc
    if not 0 <= retries <= 8:
        raise ValueError('SOORIN_HF_RETRIES must be between 0 and 8')
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt >= retries or not _retryable_download_error(exc):
                raise
            wait = min(30, 5 * 2**attempt)
            print(f'HF {name} transient failure ({type(exc).__name__}); '
                  f'retrying {attempt + 1}/{retries} after {wait}s',
                  flush=True)
            time.sleep(wait)


def download(role: str, cache: str) -> dict:
    """Download pinned files with bounded retries, retaining resumable blobs."""
    from .cpu_models import MODELS
    from huggingface_hub import HfApi, snapshot_download
    model, revision = MODELS[role]
    info = _bounded_attempts(
        'metadata',
        lambda: HfApi().model_info(model, revision=revision, files_metadata=True, timeout=30),
    )
    if info.sha != revision:
        raise ValueError('artifact_revision_mismatch')
    siblings = info.siblings
    safe_weights = any(row.rfilename.endswith('.safetensors') and '/' not in row.rfilename for row in siblings)
    rows = [row for row in siblings if not row.rfilename.startswith(('onnx/', 'imgs/', 'openvino/'))
            and (row.rfilename.endswith(('.json', '.model', '.txt'))
                 or (row.rfilename.endswith('.safetensors') if safe_weights else row.rfilename == 'pytorch_model.bin'))]
    path = Path(_bounded_attempts(
        'snapshot',
        lambda: snapshot_download(model, revision=revision, cache_dir=cache,
                                  allow_patterns=[row.rfilename for row in rows], max_workers=2)))
    entries = []
    for row in rows:
        lfs = row.lfs
        digest = getattr(lfs, 'sha256', None) if lfs else None
        entries.append({'path': row.rfilename, 'size': row.size, 'sha256': digest, 'git_blob_sha1': row.blob_id})
    manifest = {'schema_version': 'soorin.model-artifacts.v1', 'model': model,
                'revision': revision, 'files': entries}
    temp = path / 'soorin-artifacts-v1.json.tmp'
    temp.write_text(json.dumps(manifest, indent=2) + '\n')
    temp.replace(path / 'soorin-artifacts-v1.json')
    return verify(role, cache)
