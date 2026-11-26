"""Teacher batch06 corrective SFT continuing the audited balanced epoch1 checkpoint.

Two fixed epochs; paired generation before and after each epoch in one process.
No teacher, service change, hidden retry, automatic selection or deployment.
"""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import traceback

from student_tools.native_sft_data import encode_sample, FinalOnlyCollator, require, token_digest
from student_tools.teacher_physics_support import (
    PURPOSE, verify_package, training_order, TraceCollator, score_selection, summarize,
    canonical_hash, score_completion, sha, save, decode_completion, explanation_renderer,
)


def adapter_exact(model, directory, output, stage):
    from peft import get_peft_model_state_dict
    from safetensors.torch import load_file
    from student_tools.adapter_precision import compare_adapter_tensors
    current = get_peft_model_state_dict(model)
    stored = load_file(str(directory / 'adapter_model.safetensors'), device='cpu')
    report = compare_adapter_tensors(current, stored)
    save(output / (stage + '_adapter_exact.json'), report)
    require(report['exact_fp32'] and report['equal_tensors'] == 504, 'Adapter FP32 equality failed: ' + stage)
    print('ADAPTER_EXACT: ' + stage + ' 504/504 FP32 tensors identical', flush=True)
    return stored


def evaluate_arm(model, tokenizer, prompts, rows, judges, records, output, arm, *, device='cuda:0', max_new_tokens=2048, write_summary=True, score_fn=None):
    """Temporarily freeze the same single adapter; preserve training RNG/mode."""
    import torch
    from transformers import GenerationConfig, LogitsProcessorList
    from torch.nn.attention import sdpa_kernel, SDPBackend
    from student_tools.greedy_generation import generate_greedy
    from student_tools.stability_probe_support import ScoreRecorder, rng_snapshot, module_snapshot
    render_answer = explanation_renderer()
    device_type = torch.device(device).type

    original_training = model.training
    original_cache = model.config.use_cache
    original_checkpointing = model.is_gradient_checkpointing
    flags = [(p, p.requires_grad) for p in model.parameters()]
    model.gradient_checkpointing_disable()
    model.eval(); model.requires_grad_(False); model.config.use_cache = True
    arm_rng = rng_snapshot()
    eos = model.generation_config.eos_token_id
    eos = [eos] if isinstance(eos, int) else list(eos)
    require(tokenizer.eos_token_id in eos, 'Native EOS differs')
    config = GenerationConfig(max_new_tokens=max_new_tokens, do_sample=False, num_beams=1, num_return_sequences=1,
        repetition_penalty=1., use_cache=True, eos_token_id=eos, pad_token_id=tokenizer.pad_token_id,
        bos_token_id=tokenizer.bos_token_id, return_dict_in_generate=False)
    try:
        with (output / (arm + '_records.jsonl')).open('x', encoding='utf-8') as stream:
            for row in rows:
                cid, ids = row['case_id'], prompts[row['case_id']]
                tensor = torch.tensor([ids], dtype=torch.long, device=device)
                observer, prepared = ScoreRecorder({}), []
                before, mode_before = rng_snapshot(), module_snapshot(model)
                start = time.perf_counter()
                with torch.inference_mode(), torch.autocast(device_type, dtype=torch.bfloat16), sdpa_kernel(backends=[SDPBackend.MATH]):
                    generated = generate_greedy(model, input_ids=tensor, attention_mask=torch.ones_like(tensor),
                        generation_config=config, logits_processor=LogitsProcessorList([observer]), on_prepared=prepared.append)
                if device_type == 'cuda': torch.cuda.synchronize()
                seconds = time.perf_counter() - start
                require(generated[0, :len(ids)].tolist() == ids, 'Generation changed prompt')
                completion = decode_completion(tokenizer, generated[0, len(ids):].tolist(), eos, max_new_tokens=max_new_tokens)
                after, mode_after = rng_snapshot(), module_snapshot(model)
                require(completion['completion_token_ids'] == [s['argmax_token_id'] for s in observer.steps], 'Generation was not observed greedy argmax')
                require(before == after and mode_before == mode_after, 'Inference changed RNG or module state')
                # Reviewer-only fields are consumed here, AFTER generation.
                score = score_fn(completion, row, judges[cid]) if score_fn is not None else (
                    score_selection(completion, row, judges[cid]) if row['family'] == 'selection' else score_completion(completion, judges[cid], render_answer))
                record = {'case_id': cid, 'arm': arm, 'family': row['family'], 'evaluation_group': row['evaluation_group'],
                          'request_sha256': row['request_sha256'], 'prompt_tokens': len(ids),
                          'prompt_token_ids_sha256': token_digest(ids), 'completion': completion, 'score': score,
                          'generation_seconds': seconds, 'actual_generation_config': prepared[0], 'score_trace': observer.steps,
                          'rng_before': before, 'rng_after': after, 'state_before': mode_before, 'state_after': mode_after,
                          'all_parameters_frozen_for_generation': True, 'teacher_calls': 0, 'retries': 0,
                          'response_origin': 'fresh_generation'}
                records.append(record)
                stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n'); stream.flush()
                print(arm + ' ' + cid + ': protocol=' + str(score['protocol_passed']), flush=True)
                del tensor, generated
        require(rng_snapshot() == arm_rng, 'Evaluation changed training RNG')
    finally:
        model.config.use_cache = original_cache
        for parameter, flag in flags: parameter.requires_grad_(flag)
        if original_checkpointing: model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
        model.train(original_training)
    if write_summary:
        save(output / (arm + '_summary.json'), summarize(records, rows))


def preflight(args, manifest, *, initialization='balanced_epoch1_exact'):
    require(sys.version_info[:2] == (3, 11) and os.environ.get('CONDA_DEFAULT_ENV') == 'chiller-sft-v1', 'Use existing chiller-sft-v1/Python3.11')
    require(os.environ.get('CUBLAS_WORKSPACE_CONFIG') == ':4096:8', 'Set CUBLAS_WORKSPACE_CONFIG before launch')
    require(int(os.environ.get('WORLD_SIZE', '1')) == 1, 'Single-process run only')
    versions = {k: importlib.metadata.version(k) for k in manifest['required_versions']}
    require(versions == manifest['required_versions'], 'Environment changed; do not upgrade')
    require(shutil.disk_usage(args.output).free >= 4 * 2**30, 'Need at least4GiB output disk')
    save(args.output / 'environment.json', {'versions': versions, 'python': platform.python_version(), 'spec_hash': '5befcb78'})
    check = subprocess.run([sys.executable, '-m', 'pip', 'check'], capture_output=True, text=True, timeout=60)
    save(args.output / 'pip_check.json', {'returncode': check.returncode, 'stdout': check.stdout, 'stderr': check.stderr})
    require(check.returncode == 0, 'Dependency conflicts; preserve report')
    import torch
    from transformers import set_seed
    from student_tools.greedy_generation_regression import run_generation_regression
    require(torch.version.cuda == '12.4' and torch.cuda.is_available() and torch.cuda.device_count() == 1 and torch.cuda.is_bf16_supported(), 'Need one BF16 cu124 GPU; no CPU fallback')
    free, total = torch.cuda.mem_get_info(0)
    inventory = subprocess.run(['nvidia-smi'], capture_output=True, text=True, timeout=20)
    save(args.output / 'gpu_preflight.json', {'name': torch.cuda.get_device_name(0), 'free_GiB': free / 2**30,
         'total_GiB': total / 2**30, 'required_free_GiB': 60, 'nvidia_smi': inventory.stdout, 'no_processes_stopped': True})
    require(free >= 60 * 2**30, 'Need60GiB free; this package does not stop services. Return the report if busy.')
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.deterministic = True; torch.backends.cudnn.benchmark = False
    torch.backends.cuda.matmul.allow_tf32 = False; torch.backends.cudnn.allow_tf32 = False
    torch.backends.cuda.enable_flash_sdp(False); torch.backends.cuda.enable_mem_efficient_sdp(False)
    torch.backends.cuda.enable_math_sdp(True)
    set_seed(42)
    x = torch.randn(8, 8, generator=torch.Generator().manual_seed(42))
    with torch.autocast('cuda', dtype=torch.bfloat16): y = x.cuda() @ x.cuda().T
    torch.cuda.synchronize()
    require(y.isfinite().all().item() and torch.allclose(y.float().cpu(), x @ x.T, atol=.1, rtol=.02), 'GPU BF16 witness failed')
    save(args.output / 'gpu_witness.json', {'passed': True, 'max_abs_error': float((y.float().cpu() - x @ x.T).abs().max())})
    del x, y
    save(args.output / 'generation_regression.json', run_generation_regression())
    require(args.model_dir.is_dir() and not (args.model_dir / 'adapter_config.json').exists(), 'Original base directory required')
    require(args.adapter_dir.is_dir(), 'Preserved balanced epoch1 adapter directory missing')
    expected_base = {**manifest['base_weights_sha256'], **manifest['tokenizer_files_sha256'],
                     'config.json': manifest['base_config_sha256'], 'generation_config.json': manifest['base_generation_config_sha256']}
    stats, hashes = {}, {}
    for directory, expected in [(args.model_dir, expected_base), (args.adapter_dir, manifest['adapter_files_sha256'])]:
        for name, digest in expected.items():
            path = (directory / name).resolve()
            require(path.is_relative_to(directory), 'Unsafe weight path')
            print('HASH_CHECK: ' + name, flush=True)
            hashes[str(path)] = sha(path)
            require(hashes[str(path)] == digest, 'Weight/config mismatch: ' + name)
            stats[str(path)] = (path.stat().st_size, path.stat().st_mtime_ns)
    index = json.loads((args.model_dir / 'model.safetensors.index.json').read_text(encoding='utf-8'))
    require(set(index['weight_map'].values()) == set(manifest['base_weights_sha256']), 'Shard index changed')
    config = json.loads((args.adapter_dir / 'adapter_config.json').read_text(encoding='utf-8'))
    require(config['peft_type'] == 'LORA' and config['r'] == 16 and config['lora_alpha'] == 32
            and config['lora_dropout'] == .05 and config['bias'] == 'none' and not config.get('modules_to_save'), 'Unexpected initial LoRA')
    save(args.output / 'weights_verified.json', {'file_sha256': hashes, 'initialization': initialization,
         'historical_adapters_stacked': False, 'original_weights_rewritten': False, 'revision_independently_authenticated': False})
    return stats


def run(args, root, manifest, plan, rows, evaluation, judges, records):
    stats = preflight(args, manifest)
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM, Trainer, TrainingArguments, TrainerCallback, set_seed
    from peft import PeftModel, get_peft_model_state_dict
    from torch.utils.data import SequentialSampler
    tokenizer = AutoTokenizer.from_pretrained(str(args.model_dir), local_files_only=True, trust_remote_code=False)
    tokenizer.padding_side = 'right'
    encoded, checks, prompts = {}, [], {}
    for row in rows:
        features, check = encode_sample(tokenizer, row)
        encoded[row['sample_id']] = features; checks.append(check)
    for row in evaluation:
        ids = tokenizer.apply_chat_template(row['request']['messages'], tools=None, enable_thinking=False, tokenize=True, add_generation_prompt=True)
        require({'prompt_tokens': len(ids), 'token_ids_sha256': token_digest(ids)} == row['prompt_reference'], 'Eval native prompt drift')
        require(len(ids) + 2048 <= 8192, 'Context overflow; no truncation permitted')
        prompts[row['case_id']] = ids
    require(checks == [json.loads(l) for l in (root / 'checks/native_encoding_reference.jsonl').read_text(encoding='utf-8').splitlines()], 'Training encoding differs from preparation')
    save(args.output / 'encoding_check.json', {'checks': checks, 'eval_prompts': {cid: {'tokens': len(ids), 'sha256': token_digest(ids)} for cid, ids in prompts.items()},
         'new_gradients_exclude_declared_parents': True, 'judges_or_eval_targets_supervised': False})
    save(args.output / 'actual_eval_requests.json', evaluation)
    set_seed(42)
    base = AutoModelForCausalLM.from_pretrained(str(args.model_dir), torch_dtype=torch.bfloat16,
        attn_implementation='sdpa', device_map={'': 0}, local_files_only=True, trust_remote_code=False, use_safetensors=True)
    model = PeftModel.from_pretrained(base, str(args.adapter_dir), is_trainable=True, local_files_only=True, autocast_adapter_dtype=True)
    require(set(model.peft_config) == {'default'}, 'One adapter only')
    initial = adapter_exact(model, args.adapter_dir, args.output, 'initial_balanced_epoch1')
    trainable = {n: p for n, p in model.named_parameters() if p.requires_grad}
    require(len(trainable) == 504 and all('lora_' in n and p.dtype == torch.float32 for n, p in trainable.items()), 'Unexpected trainable parameters/dtypes')
    require(all(p.dtype == torch.bfloat16 for n, p in model.named_parameters() if n not in trainable), 'Base dtype changed')
    frozen_probes = {n: p.detach().reshape(-1)[:64].cpu().clone() for n, p in model.named_parameters() if not p.requires_grad}
    save(args.output / 'model_setup.json', {'initial_adapter': str(args.adapter_dir), 'initial_adapter_sha256': manifest['adapter_files_sha256']['adapter_model.safetensors'],
         'trainable_tensors': len(trainable), 'trainable_parameters': sum(p.numel() for p in trainable.values()),
         'base_dtype': 'bfloat16', 'adapter_dtype': 'float32', 'historical_adapters_stacked': False,
         'only_one_adapter_trained': True, 'new_optimizer': True, 'gradient_checkpointing': True})
    evaluate_arm(model, tokenizer, prompts, evaluation, judges, records, args.output, 'balanced_before')
    prior_controls = json.loads((root / 'checks/before_control_tokens.json').read_text(encoding='utf-8'))
    for record in records:
        cid = record['case_id']
        if cid in prior_controls:
            require(record['completion']['completion_token_ids'] == prior_controls[cid]['tokens']
                    and record['request_sha256'] == prior_controls[cid]['request_sha256'], 'Starting adapter control differs: ' + cid)
    require(len(prior_controls) == 52, 'Expected52 prior output controls')
    save(args.output / 'before_control_reproduction.json', {'matched_starting_adapter_outputs':52,
         'same_numeric_gate_as_starting_run':True, 'prior_errors_preserved':True})
    adapter_exact(model, args.adapter_dir, args.output, 'after_before_generation')
    order = training_order(rows)
    collator = FinalOnlyCollator(tokenizer.pad_token_id)
    tracing = TraceCollator(collator, order, 2, args.output / 'training_sample_trace.jsonl')
    # Verify the delivered collator preserves supervision and masks padding.
    features = [encoded[max(encoded, key=lambda k: len(encoded[k]['input_ids']))], encoded[min(encoded, key=lambda k: len(encoded[k]['input_ids']))]]
    padding = collator(features)
    for i, feature in enumerate(features):
        n = len(feature['labels'])
        require(padding['labels'][i, :n].tolist() == feature['labels'] and (padding['labels'][i, n:] == -100).all().item(), 'Padding labels changed')
    del padding
    destination = args.output
    saved_epochs = []

    class Audit(TrainerCallback):
        gradients = 0
        def on_pre_optimizer_step(self, args_, state, control, model=None, **kwargs):
            gradients = [p.grad for p in trainable.values() if p.grad is not None]
            require(bool(gradients) and torch.stack([torch.isfinite(g).all() for g in gradients]).all().item(), 'Nonfinite/missing gradient')
            require(all(p.grad is None for n, p in model.named_parameters() if n not in trainable), 'Frozen base received gradient')
            norm = float(torch.stack([torch.linalg.vector_norm(g.detach().float()) for g in gradients]).norm().item())
            require(math.isfinite(norm) and norm > 0, 'Zero/nonfinite adapter gradient')
            self.gradients += 1
            with (destination / 'gradient_checks.jsonl').open('a', encoding='utf-8') as f:
                f.write(json.dumps({'step': state.global_step + 1, 'tensors': len(gradients), 'norm_after_clipping': norm}) + '\n')
        def on_log(self, args_, state, control, logs=None, **kwargs):
            if logs:
                require(all(math.isfinite(float(logs[k])) for k in ('loss', 'grad_norm', 'train_loss') if k in logs), 'Nonfinite training log')
                with (destination / 'trainer_logs.jsonl').open('a', encoding='utf-8') as f:
                    f.write(json.dumps(logs, allow_nan=False) + '\n')
        def on_step_end(self, args_, state, control, **kwargs):
            print('TEACHER_SFT_STEP ' + str(state.global_step) + '/' + str(plan['optimizer_steps']), flush=True)
        def on_epoch_end(self, args_, state, control, model=None, **kwargs):
            epoch = len(saved_epochs) + 1
            require(epoch in (1, 2) and state.global_step == len(order) * epoch, 'Unexpected epoch boundary')
            require(tracing.seen == order * epoch, 'Training visit trace differs')
            directory = destination / ('adapter_teacher_epoch' + str(epoch))
            model.save_pretrained(str(directory), safe_serialization=True)
            stored = adapter_exact(model, directory, destination, 'epoch' + str(epoch) + '_serialized')
            changed = sum(not torch.equal(stored[k], initial[k]) for k in stored)
            require(changed > 0, 'No adapter update')
            files = {p.name: {'sha256': sha(p), 'bytes': p.stat().st_size} for p in directory.iterdir() if p.is_file()}
            save(destination / ('epoch' + str(epoch) + '_adapter_manifest.json'), {'epoch': epoch, 'step': state.global_step,
                 'adapter_dir': str(directory), 'files': files, 'changed_tensors_vs_starting_adapter': changed, 'fp32_serialization_exact': True})
            saved_epochs.append(epoch)
            evaluate_arm(model, tokenizer, prompts, evaluation, judges, records, destination, 'teacher_epoch' + str(epoch))
            adapter_exact(model, directory, destination, 'epoch' + str(epoch) + '_after_generation')

    class OrderedTrainer(Trainer):
        def _get_train_sampler(self, *args_, **kwargs): return SequentialSampler(self.train_dataset)

    model.config.use_cache = False
    callback = Audit()
    training = TrainingArguments(output_dir=str(destination / 'trainer'), max_steps=plan['optimizer_steps'], num_train_epochs=2,
        per_device_train_batch_size=1, gradient_accumulation_steps=1, learning_rate=5e-6, lr_scheduler_type='constant',
        warmup_steps=0, weight_decay=0., max_grad_norm=1., bf16=True, fp16=False, tf32=False,
        gradient_checkpointing=True, gradient_checkpointing_kwargs={'use_reentrant': False}, optim='adamw_torch',
        logging_strategy='steps', logging_steps=1, logging_nan_inf_filter=False, save_strategy='no', eval_strategy='no',
        report_to=[], disable_tqdm=True, seed=42, data_seed=42, dataloader_num_workers=0,
        dataloader_pin_memory=False, remove_unused_columns=False, label_names=['labels'], save_safetensors=True)
    trainer = OrderedTrainer(model=model, args=training, train_dataset=[{'sample_id': sid, **encoded[sid]} for sid in order],
                             data_collator=tracing, callbacks=[callback])
    save(destination / 'training_started.json', {'purpose': PURPOSE, 'started_utc': datetime.now(timezone.utc).isoformat(),
         'training_run': True, 'continue_balanced_epoch1': True, 'fresh_base_and_new_adapter': False,
         'new_optimizer': True, 'selected_ids': order, 'max_steps': plan['optimizer_steps'], 'epochs': 2,
         'learning_rate': 5e-6, 'evaluation_cases_in_gradients': 0, 'teacher_calls': 0})
    torch.cuda.reset_peak_memory_stats()
    start = time.perf_counter()
    result = trainer.train()
    torch.cuda.synchronize()
    seconds = time.perf_counter() - start
    require(trainer.state.global_step == callback.gradients == plan['optimizer_steps'], 'Incomplete training steps')
    require(saved_epochs == [1, 2] and tracing.seen == order * 2, 'Incomplete epoch/visits')
    for n, p in model.named_parameters():
        if n in frozen_probes: require(torch.equal(p.detach().reshape(-1)[:64].cpu(), frozen_probes[n]), 'Frozen base sample changed')
    for name, stat in stats.items():
        file = Path(name)
        require((file.stat().st_size, file.stat().st_mtime_ns) == stat, 'Original weight file changed')
    require({name: sha(args.adapter_dir / name) for name in manifest['adapter_files_sha256']} == manifest['adapter_files_sha256'], 'Starting adapter files changed')
    # Re-open the final checkpoint with the FP32-before-copy protection previously
    # required for second adapters. This is a reload check, not joint inference.
    from student_tools.adapter_precision import add_fp32_adapter_then_load, compare_adapter_tensors
    from safetensors.torch import load_file
    model.eval(); model.requires_grad_(False); model.gradient_checkpointing_disable(); model.config.use_cache = True
    probe = torch.tensor([prompts[evaluation[0]['case_id']]], dtype=torch.long, device='cuda:0')
    with torch.inference_mode(), torch.autocast('cuda', dtype=torch.bfloat16):
        before = model(input_ids=probe, attention_mask=torch.ones_like(probe), use_cache=False).logits[0, -1].detach().cpu()
    final_dir = destination / 'adapter_teacher_epoch2'
    add_fp32_adapter_then_load(model, final_dir, 'reload_joint', emit=lambda stage, report: save(destination / ('reload_' + stage + '.json'), report))
    report = compare_adapter_tensors(get_peft_model_state_dict(model, adapter_name='reload_joint'), load_file(str(final_dir / 'adapter_model.safetensors'), device='cpu'))
    require(report['exact_fp32'] and report['equal_tensors'] == 504, 'Reloaded FP32 tensors differ')
    model.set_adapter('reload_joint'); model.eval(); model.requires_grad_(False)
    with torch.inference_mode(), torch.autocast('cuda', dtype=torch.bfloat16):
        after = model(input_ids=probe, attention_mask=torch.ones_like(probe), use_cache=False).logits[0, -1].detach().cpu()
    require(torch.equal(before, after), 'Reload changed logits')
    save(destination / 'reload_check.json', {'tensors': report, 'next_token_logits_exact': True, 'two_adapters_active_together': False})
    summary = summarize(records, evaluation)
    require(summary['complete'], 'Missing paired generations')
    summary.update(training_run=True, optimizer_steps=trainer.state.global_step, completed_epochs=2,
        finite_gradient_checks=callback.gradients, train_visit_order_verified=True, evaluation_cases_in_gradients=0,
        frozen_parameter_sample_probes_unchanged=True, original_weight_file_metadata_unchanged=True,
        starting_adapter_files_rehashed_after_training=True, base_weights_rehashed_after_training=False,
        serialized_adapters_fp32_exact=True, reload_check_passed=True, training_and_epoch_eval_seconds=seconds,
        peak_allocated_GiB=torch.cuda.max_memory_allocated()/2**30, peak_reserved_GiB=torch.cuda.max_memory_reserved()/2**30,
        trainer_metrics=result.metrics, automatic_checkpoint_selection=False,
        next_step='Return review ZIP for semantic review and regression comparison. Preserve both adapters. No automatic serving change.')
    save(destination / 'teacher_summary.json', summary)
    print(json.dumps({'complete': True, 'optimizer_steps': trainer.state.global_step, 'answers': len(records),
                      'training_run': True, 'deployment_approved': False}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=Path('bundle_manifest.json'))
    parser.add_argument('--model-dir', type=Path, default=Path('/root/epfs/chiller_student_baseline_kit_v1/models/Qwen3-8B'))
    parser.add_argument('--adapter-dir', type=Path, default=Path('/root/epfs/chiller_balanced_physics_sft_kit_v1/results/balanced_physics_sft_20261116_084056_8685/adapter_balanced_epoch1'))
    parser.add_argument('--output', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--run', action='store_true')
    mode.add_argument('--validate-package-only', action='store_true')
    args = parser.parse_args()
    args.output = args.output.expanduser().resolve()
    args.model_dir = args.model_dir.expanduser().resolve(); args.adapter_dir = args.adapter_dir.expanduser().resolve()
    require(not args.output.exists(), 'Use a NEW output directory; preserve prior runs')
    require(not args.output.is_relative_to(args.model_dir) and not args.output.is_relative_to(args.adapter_dir), 'Never write inside existing weights')
    root, manifest, plan, rows, evaluation, judges = verify_package(args.bundle)
    args.output.mkdir(parents=True)
    save(args.output / 'run_manifest.json', {'purpose': PURPOSE, 'bundle_sha256': sha(args.bundle), 'validate_package_only': args.validate_package_only,
         'training_requested': args.run, 'planned_steps': plan['optimizer_steps'], 'planned_answers': plan['planned_answers'],
         'model_dir': str(args.model_dir), 'adapter_dir': str(args.adapter_dir), 'independent_test': False})
    if args.validate_package_only:
        save(args.output / 'package_check.json', {'passed': True, 'train_rows': len(rows), 'eval_cases': len(evaluation),
             'model_calls': 0, 'training_run': False, 'tokenizer_or_gpu_loaded': False})
        print('Package passed: ' + str(len(rows)) + ' train rows, ' + str(len(evaluation)) + ' eval cases; no framework/GPU/model loaded.')
        return
    os.environ['HF_HUB_OFFLINE'] = '1'; os.environ['TRANSFORMERS_OFFLINE'] = '1'
    records = []
    try:
        run(args, root, manifest, plan, rows, evaluation, judges, records)
    except Exception as exc:
        save(args.output / 'teacher_error.json', {'error_type': type(exc).__name__, 'error': str(exc), 'traceback': traceback.format_exc(),
             'training_started': (args.output / 'training_started.json').exists(), 'answers_saved': len(records), 'automatic_retry': False})
        save(args.output / 'incomplete_summary.json', summarize(records, evaluation))
        raise


if __name__ == '__main__': main()

