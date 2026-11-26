"""Frozen retrospective120 model comparison. Inference only; no API calls.

The audited student answers are reused, never regenerated or selected again.
This executable runs only the two unadapted open-weight baseline arms.
"""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone

from student_tools.native_sft_data import require, token_digest
from student_tools.paired_support import sha, save
from student_tools.joint_physics_support import canonical_hash

PURPOSE = 'physics120_six_system_comparison_20261122_v1'
BASE8 = '/root/epfs/chiller_student_baseline_kit_v1/models/Qwen3-8B'
BASE14 = '/root/epfs/chiller_comparison_models/Qwen3-14B-40c0698'


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf8').splitlines() if line.strip()]


def verify(path):
    path = path.resolve(); root = path.parent
    m = json.loads(path.read_text(encoding='utf8'))
    require(m['purpose'] == PURPOSE and m['training_run'] is False, 'Wrong package')
    require(len(m['files']) == len({f['path'] for f in m['files']}), 'Duplicate file')
    for f in m['files']:
        raw = root / f['path']; p = raw.resolve()
        require(p.is_relative_to(root) and not raw.is_symlink(), 'Unsafe package path')
        require(p.stat().st_size == f['bytes'] and sha(p) == f['sha256'], 'Changed file: ' + f['path'])
    rows = read_jsonl(root / 'data/model_inputs120.jsonl')
    require(len(rows) == len({r['case_id'] for r in rows}) == 120, 'Expected exactly120 cases')
    parents = {r['parent_source_record_id'] for r in rows}; kinds = {r['question_kind'] for r in rows}
    require(len(parents) == 8 and len(kinds) == 15 and 'metrics' not in kinds, 'Scope drift')
    require(len({(r['parent_source_record_id'], r['question_kind']) for r in rows}) == 120, 'Incomplete8x15 matrix')
    original = {r['case_id']: r for r in read_jsonl(root / 'checks/original_model_inputs128.jsonl')}
    for r in rows:
        require(r['request_sha256'] == canonical_hash(r['request']), 'Request hash mismatch')
        require(r['request'] == original[r['case_id']]['request'], 'Original messages changed')
        require(r['prompt_reference'] == original[r['case_id']]['prompt_reference'], 'Native prompt changed')
        require([v['role'] for v in r['request']['messages']] == ['system', 'user'] and r['request']['tools'] is None, 'Targets/tools in input')
    refs = read_jsonl(root / 'reference/student_records120.jsonl')
    reviews = read_jsonl(root / 'reference/student_editorial120.jsonl')
    require([r['case_id'] for r in refs] == [r['case_id'] for r in rows] == [r['case_id'] for r in reviews], 'Student identity mismatch')
    import hashlib
    for r, answer, review in zip(rows, refs, reviews):
        require(answer['request_sha256'] == r['request_sha256'], 'Student request changed')
        digest = hashlib.sha256(answer['completion']['content'].encode('utf8')).hexdigest()
        require(digest == review['raw_content_sha256'], 'Student answer changed')
    require(sum(r['editor_content_correct_and_complete'] for r in reviews) == 116, 'Inherited labels changed')
    protocol = json.loads((root / 'comparison_protocol.json').read_text(encoding='utf8'))
    require(protocol['posthoc_subset'] and not protocol['new_independent_test'], 'Subset provenance hidden')
    require(protocol['student_response_origin'] == 'reuse_audited_original128_subset', 'Do not rerun student')
    require(protocol['local_generation']['max_new_tokens'] == 2048 and not protocol['local_generation']['do_sample'], 'Decoding changed')
    return root, m, rows


def summarize(rows, records, judges):
    """Missing/failed outputs stay in the denominator; automatic checks != accuracy."""
    from student_tools.targeted_task_support import score
    by = {r['case_id']: r for r in records}; expected = {r['case_id'] for r in rows}
    require(len(by) == len(records) and set(by) <= expected, 'Duplicate/unexpected answers')
    scored = []
    for row in rows:
        answer = by.get(row['case_id'])
        if answer is None:
            scored.append({'case_id': row['case_id'], 'recorded': False, 'finite_joint_pass': False, 'semantic_review': 'missing_answer'})
            continue
        require(answer['request_sha256'] == row['request_sha256'], 'Answer/request identity mismatch')
        s = score(answer['completion'], row, judges[row['case_id']])
        joint = bool(s['original_frozen_v7_score']['aligned_safe_protocol_passed'] and s['required_fact_coverage_passed'] and answer['completion']['finish_reason'] == 'stop')
        scored.append({'case_id': row['case_id'], 'recorded': True, 'finite_joint_pass': joint, 'score': s, 'semantic_review': 'pending'})
    return scored, {'expected': 120, 'answers': len(records), 'complete': len(records) == 120,
        'finite_protocol_and_citation_passes': sum(r['finite_joint_pass'] for r in scored),
        'content_correct_and_complete': None, 'domain_accuracy': None, 'manual_review_required': True,
        'fallback_counted_as_success': False, 'retries': 0, 'training_run': False,
        'new_independent_test': False, 'page_tested': False, 'deployment_approved': False}


def preflight(args, m):
    require(sys.version_info[:2] == (3, 11) and os.environ.get('CONDA_DEFAULT_ENV') == 'chiller-sft-v1', 'Use existing chiller-sft-v1/Python3.11')
    require(os.environ.get('CUBLAS_WORKSPACE_CONFIG') == ':4096:8', 'Set CUBLAS_WORKSPACE_CONFIG before launch')
    versions = {k: importlib.metadata.version(k) for k in m['required_versions']}
    require(versions == m['required_versions'], 'Environment changed; do not upgrade')
    require(int(os.environ.get('WORLD_SIZE', '1')) == 1, 'One process only')
    require(shutil.disk_usage(args.output).free >= 4 * 2**30, 'Need4GiB output disk')
    save(args.output / 'environment.json', {'versions': versions, 'python': platform.python_version(), 'spec_hash': '5befcb78'})
    check = subprocess.run([sys.executable, '-m', 'pip', 'check'], capture_output=True, text=True, timeout=60)
    save(args.output / 'pip_check.json', {'returncode': check.returncode, 'stdout': check.stdout, 'stderr': check.stderr})
    require(check.returncode == 0, 'Dependency conflicts; preserve report')
    import torch
    from transformers import set_seed
    from student_tools.greedy_generation_regression import run_generation_regression
    require(torch.version.cuda == '12.4' and torch.cuda.is_available() and torch.cuda.device_count() == 1 and torch.cuda.is_bf16_supported(), 'Need one BF16 cu124 GPU')
    free, total = torch.cuda.mem_get_info(0)
    inventory = subprocess.run(['nvidia-smi'], capture_output=True, text=True, timeout=20)
    save(args.output / 'gpu_preflight.json', {'name': torch.cuda.get_device_name(0), 'free_GiB': free / 2**30, 'total_GiB': total / 2**30, 'nvidia_smi': inventory.stdout, 'no_processes_stopped': True})
    require(free >= 60 * 2**30, 'Need60GiB free; do not kill unknown services; return report')
    torch.use_deterministic_algorithms(True); torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False; torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False; torch.backends.cuda.enable_flash_sdp(False)
    torch.backends.cuda.enable_mem_efficient_sdp(False); torch.backends.cuda.enable_math_sdp(True)
    set_seed(42)
    x = torch.randn(8, 8, generator=torch.Generator().manual_seed(42))
    with torch.autocast('cuda', dtype=torch.bfloat16): y = x.cuda() @ x.cuda().T
    torch.cuda.synchronize()
    require(y.isfinite().all().item() and torch.allclose(y.float().cpu(), x @ x.T, atol=.1, rtol=.02), 'BF16 GPU witness failed')
    save(args.output / 'gpu_witness.json', {'passed': True, 'max_abs_error': float((y.float().cpu() - x @ x.T).abs().max())})
    del x, y
    save(args.output / 'generation_regression.json', run_generation_regression())
    require(args.model_dir.is_dir() and not (args.model_dir / 'adapter_config.json').exists(), 'Unadapted base required')
    spec = m['local_models'][args.arm]; hashes = {}
    for name, digest in spec['files_sha256'].items():
        path = args.model_dir / name
        require(path.resolve().is_relative_to(args.model_dir), 'Unsafe model path')
        print('HASH_CHECK: ' + name, flush=True); hashes[name] = sha(path)
        require(hashes[name] == digest, 'Model file mismatch: ' + name)
    index = json.loads((args.model_dir / 'model.safetensors.index.json').read_text(encoding='utf8'))
    require(set(index['weight_map'].values()) == {n for n in hashes if n.endswith('.safetensors')}, 'Shard index mismatch')
    save(args.output / 'model_identity.json', {'arm': args.arm, 'repo': spec['repo'], 'revision': spec['revision'], 'files_sha256': hashes, 'adapter_loaded': False})
    return hashes


def run(args, root, m, rows, records):
    hashes = preflight(args, m)
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed
    from student_tools.teacher_physics_sft import evaluate_arm
    from student_tools.focused_holdout_support import generation_only_score
    tok = AutoTokenizer.from_pretrained(str(args.model_dir), local_files_only=True, trust_remote_code=False)
    controls = read_jsonl(root / 'checks/warmup_controls4.jsonl'); prompts = {}
    for row in controls + rows:
        ids = tok.apply_chat_template(row['request']['messages'], tools=None, enable_thinking=False, tokenize=True, add_generation_prompt=True)
        require({'prompt_tokens': len(ids), 'token_ids_sha256': token_digest(ids)} == row['prompt_reference'], 'Native template drift')
        require(len(ids) + 2048 <= 8192, 'No context truncation permitted')
        prompts[row['case_id']] = ids
    save(args.output / 'native_prompts.json', {'passed': True, 'cases': 124, 'tokenizer_identity': m['local_models'][args.arm]['files_sha256']['tokenizer_config.json'], 'judges_in_input': False})
    save(args.output / 'actual_requests.json', rows)
    set_seed(42)
    model = AutoModelForCausalLM.from_pretrained(str(args.model_dir), torch_dtype=torch.bfloat16, attn_implementation='sdpa', device_map={'': 0}, local_files_only=True, trust_remote_code=False, use_safetensors=True)
    model.eval(); model.requires_grad_(False); model.config.use_cache = True
    require(not hasattr(model, 'peft_config') and all(not p.requires_grad and p.grad is None for p in model.parameters()), 'Unexpected adapter/gradients')
    probes = {n: p.detach().reshape(-1)[:64].cpu().clone() for n, p in model.named_parameters()}
    dummy = {r['case_id']: None for r in controls + rows}
    warmup = []
    evaluate_arm(model, tok, prompts, controls, dummy, warmup, args.output, 'warmup', write_summary=False, score_fn=generation_only_score)
    save(args.output / 'warmup_status.json', {'answers': len(warmup), 'not_quality_cases': True, 'not_historical_exact_output_controls': True})
    args.registry_dir.mkdir(parents=True, exist_ok=True)
    marker = args.registry_dir / (PURPOSE + '_' + args.arm + '.once.json')
    # Exclusive creation prevents a second quality attempt, even in another copy.
    with marker.open('x', encoding='utf8') as f:
        json.dump({'purpose': PURPOSE, 'arm': args.arm, 'output': str(args.output), 'created_UTC': datetime.now(timezone.utc).isoformat(), 'model_revision': m['local_models'][args.arm]['revision']}, f, indent=2)
    save(args.output / 'evaluation_started.json', {'registry': str(marker), 'quality_answers_planned': 120})
    def marked_rows():
        with (args.output / 'quality_attempts.jsonl').open('x', encoding='utf8') as stream:
            for row in rows:
                stream.write(json.dumps({'case_id': row['case_id'], 'request_sha256': row['request_sha256'], 'attempt': 1}) + '\n')
                stream.flush()
                yield row
    evaluate_arm(model, tok, prompts, marked_rows(), dummy, records, args.output, args.arm, write_summary=False, score_fn=generation_only_score)
    require(len(records) == 120 and all(p.grad is None and not p.requires_grad for p in model.parameters()), 'Incomplete inference or gradients')
    require(all(torch.equal(probes[n], p.detach().reshape(-1)[:64].cpu()) for n, p in model.named_parameters()), 'Frozen tensor probes changed')
    require(all(sha(args.model_dir / n) == h for n, h in hashes.items()), 'Original model files changed')
    save(args.output / 'weights_after.json', {'all_files_rehashed_equal': True, 'frozen_tensor_probes_equal': True, 'optimizer_created': False})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path, default=Path('bundle_manifest.json'))
    p.add_argument('--arm', choices=['base8b', 'qwen14b'], default='base8b')
    p.add_argument('--model-dir', type=Path)
    p.add_argument('--registry-dir', type=Path, default=Path('/root/epfs/chiller_student_evaluation_registry'))
    p.add_argument('--output', type=Path, required=True)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--run', action='store_true'); mode.add_argument('--validate-package-only', action='store_true')
    a = p.parse_args(); a.model_dir = (a.model_dir or Path(BASE8 if a.arm == 'base8b' else BASE14)).expanduser().resolve()
    a.output = a.output.expanduser().resolve(); a.registry_dir = a.registry_dir.expanduser().resolve()
    require(not a.output.exists() and not a.output.is_relative_to(a.model_dir), 'Use a new output outside weights')
    root, m, rows = verify(a.bundle); a.output.mkdir(parents=True)
    save(a.output / 'run_manifest.json', {'purpose': PURPOSE, 'arm': a.arm, 'bundle_sha256': sha(a.bundle), 'training_run': False, 'API_calls': 0, 'evaluation_requested': a.run})
    if a.validate_package_only:
        save(a.output / 'package_check.json', {'passed': True, 'cases': 120, 'student_reused': 120, 'models_loaded': 0, 'GPU_used': False, 'API_calls': 0, 'registry_created': False})
        print('PASS:120 original requests;120 unchanged student records;no GPU/model/API/registry.'); return
    require(not a.registry_dir.is_relative_to(a.model_dir), 'Registry must be outside weights')
    marker = a.registry_dir / (PURPOSE + '_' + a.arm + '.once.json')
    require(not marker.exists(), 'This arm already started; return existing run, do not delete registry')
    os.environ['HF_HUB_OFFLINE'] = '1'; os.environ['TRANSFORMERS_OFFLINE'] = '1'
    import fcntl
    (root / 'results').mkdir(exist_ok=True)
    records = []; error = None
    with (root / 'results/.comparison_gpu.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            run(a, root, m, rows, records)
        except Exception as exc:
            error = exc
            save(a.output / 'error.json', {'type': type(exc).__name__, 'message': str(exc), 'traceback': traceback.format_exc(), 'answers_saved': len(records), 'automatic_retry': False})
        finally:
            judges = {j['case_id']: j for j in read_jsonl(root / 'checks/judge_only120.jsonl')}
            scored, summary = summarize(rows, records, judges)
            save(a.output / 'finite_scores.json', scored); save(a.output / 'summary.json', summary)
    print(json.dumps(summary), flush=True)
    if error is not None: raise error


if __name__ == '__main__': main()
