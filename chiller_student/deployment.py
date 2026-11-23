"""Local paths and frozen weight verification; never downloads or trains models."""
from pathlib import Path
import hashlib
import json
import os

from chiller_student.focused_contract import IDENTITY

ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONFIG = ROOT / '.student.local.json'
MANIFEST = ROOT / 'deployment/focused1186.json'


def read_manifest():
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if manifest['service_identity'] != IDENTITY or manifest['adapter_files_sha256']['adapter_model.safetensors'] != IDENTITY['adapter_model_sha256']:
        raise ValueError('Deployment identity differs from frozen focused1186')
    return manifest


def local_config():
    if not LOCAL_CONFIG.is_file():
        return {}
    value = json.loads(LOCAL_CONFIG.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Local student configuration must be an object')
    return value


def discover_backup(root):
    root = Path(root).expanduser().resolve()
    base = root / 'Qwen3-8B'
    adapters = list((root / 'chiller_focused_task_sft_kit_v1/results').glob('focused_task_*/adapter_focused_epoch1'))
    if not base.is_dir() or len(adapters) != 1:
        raise ValueError('Expected Qwen3-8B plus one focused_task_*/adapter_focused_epoch1 in model root')
    return base, adapters[0].resolve()


def resolve_paths(model_dir=None, adapter_dir=None):
    cfg = local_config()
    model_dir = model_dir or os.environ.get('CHILLER_BASE_MODEL_DIR') or cfg.get('model_dir')
    adapter_dir = adapter_dir or os.environ.get('CHILLER_ADAPTER_DIR') or cfg.get('adapter_dir')
    if not model_dir or not adapter_dir:
        raise ValueError('Supply --model-dir and --adapter-dir, or first run python -m chiller_student.configure --model-root PATH')
    return Path(model_dir).expanduser().resolve(), Path(adapter_dir).expanduser().resolve()


def file_hash(path):
    value = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def verify_weights(model_dir, adapter_dir, *, full=True, progress=None):
    manifest = read_manifest()
    groups = [(model_dir, manifest['tokenizer_files_sha256']),
              (model_dir, {'config.json': manifest['base_config_sha256'], 'generation_config.json': manifest['base_generation_config_sha256']}),
              (adapter_dir, manifest['adapter_files_sha256'])]
    if full:
        groups.insert(0, (model_dir, manifest['base_weights_sha256']))
    verified = []
    for folder, expected in groups:
        folder = Path(folder).resolve()
        for name, expected_hash in expected.items():
            path = (folder / name).resolve()
            if not path.is_relative_to(folder) or not path.is_file():
                raise ValueError('Missing or unsafe model file: ' + name)
            if progress:
                progress('HASH_CHECK: ' + name)
            actual = file_hash(path)
            if actual != expected_hash:
                raise ValueError('Weight/config mismatch: ' + name)
            verified.append({'name': name, 'sha256': actual, 'bytes': path.stat().st_size})
    index = json.loads((Path(model_dir) / 'model.safetensors.index.json').read_text(encoding='utf-8'))
    if set(index['weight_map'].values()) != set(manifest['base_weights_sha256']):
        raise ValueError('Base shard index differs from frozen Qwen3-8B')
    return {'valid': True, 'all_base_weight_shards_hashed': full, 'files': verified,
            'service_identity': IDENTITY, 'GPU_loaded': False, 'training_run': False}
