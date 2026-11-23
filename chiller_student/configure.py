"""Bind existing backup files to this checkout without copying or changing weights."""
import argparse
import json
import os
import secrets
from pathlib import Path

from chiller_student.deployment import ROOT, LOCAL_CONFIG, discover_backup, verify_weights


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-root', type=Path, required=True)
    parser.add_argument('--full-hash', action='store_true')
    parser.add_argument('--url', default='http://127.0.0.1:28081')
    args = parser.parse_args()
    if LOCAL_CONFIG.exists():
        parser.error('Local configuration already exists. Preserve it; edit its model paths explicitly if needed.')
    base, adapter = discover_backup(args.model_root)
    result = verify_weights(base, adapter, full=args.full_hash, progress=lambda s: print(s, flush=True))
    credential = ROOT / '.student_credentials/student-service.token'
    credential.parent.mkdir(exist_ok=True)
    if not credential.exists():
        fd = os.open(credential, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(secrets.token_urlsafe(32))
    data = {'model_dir': str(base), 'adapter_dir': str(adapter), 'student_url': args.url,
            'token_file': str(credential), 'scope': 'single_row_physics_explanation'}
    LOCAL_CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'configured': True, 'candidate': 'focused1186',
                      'base_shards_hashed': result['all_base_weight_shards_hashed'],
                      'weights_copied': False, 'GPU_loaded': False, 'training_run': False}))


if __name__ == '__main__':
    main()
