"""Explicit optional download of a pinned Qwen3-14B; never loads or trains it."""
import argparse
import json
import shutil
from pathlib import Path
from student_tools.physics120_comparison import verify, BASE14
from student_tools.paired_support import sha, save
from student_tools.native_sft_data import require


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path, default=Path('bundle_manifest.json'))
    p.add_argument('--destination', type=Path, default=Path(BASE14))
    p.add_argument('--download', action='store_true', required=True)
    a = p.parse_args(); root, m, _ = verify(a.bundle)
    dest = a.destination.expanduser().resolve(); spec = m['local_models']['qwen14b']
    require(not dest.exists(), 'Preserve existing model directory; return message for verification')
    ancestor = dest.parent
    while not ancestor.exists(): ancestor = ancestor.parent
    require(shutil.disk_usage(ancestor).free >= 40 * 2**30, 'Need40GiB free before pinned14B download')
    from huggingface_hub import snapshot_download
    dest.mkdir(parents=True)
    snapshot_download(repo_id=spec['repo'], revision=spec['revision'], local_dir=str(dest), allow_patterns=list(spec['files_sha256']), max_workers=2)
    for name, h in spec['files_sha256'].items():
        print('HASH_CHECK: ' + name, flush=True)
        require(sha(dest / name) == h, 'Downloaded file mismatch: ' + name)
    save(dest / 'comparison_download_verified.json', {'repo': spec['repo'], 'revision': spec['revision'], 'files_sha256': spec['files_sha256'], 'training_run': False})
    print('Pinned14B download verified. No model loaded; no inference or training.')


if __name__ == '__main__': main()
