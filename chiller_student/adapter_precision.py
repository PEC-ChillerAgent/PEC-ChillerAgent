"""Load a further PEFT 0.15.2 pure-LoRA adapter without a BF16 copy destination.

The base stays BF16. Only the newly allocated LoRA A/B modules are promoted,
BEFORE load_adapter copies the saved FP32 state. Never round the reference,
relax equality, merge weights, or rewrite a checkpoint.
"""
from collections import Counter
from chiller_student.native_sft_data import require


def add_fp32_adapter_then_load(model, adapter_dir, adapter_name, expected_layers=252, emit=None):
    import torch
    from peft import LoraConfig

    require(adapter_name not in model.peft_config, 'Adapter already exists: '+adapter_name)
    config = LoraConfig.from_pretrained(str(adapter_dir), local_files_only=True)
    require(config.peft_type == 'LORA' and config.bias == 'none' and not config.modules_to_save,
            'Precision loader only supports pure LoRA without modified base/bias/modules')
    require(not config.use_dora and not config.use_rslora and not getattr(config, 'lora_bias', False),
            'Unsupported LoRA variant')
    require(config.init_lora_weights is True or config.init_lora_weights == 'gaussian',
            'Base-mutating or nonstandard initialization is not supported')
    config.inference_mode = True
    # add_adapter follows the BF16 base dtype; no checkpoint values copied yet.
    model.add_adapter(adapter_name, config, low_cpu_mem_usage=False)
    layers = [m for m in model.modules() if hasattr(m, 'lora_A') and adapter_name in m.lora_A]
    require(len(layers) == expected_layers, 'Unexpected new adapter layer count')
    before = Counter()
    for layer in layers:
        require(adapter_name in layer.lora_B and not layer.merged, 'Incomplete or merged LoRA layer')
        for collection in (layer.lora_A, layer.lora_B):
            module = collection[adapter_name]
            require(set(dict(module.named_parameters())) == {'weight'}, 'Only A/B weights are supported')
            require(not module.weight.is_meta, 'Meta adapter is not supported by this loader')
            before[str(module.weight.dtype)] += 1
            # Do not call model.float(): that would also convert the 8B base.
            module.to(dtype=torch.float32)
    params = [collection[adapter_name].weight for layer in layers for collection in (layer.lora_A, layer.lora_B)]
    require(all(p.dtype == torch.float32 for p in params), 'Copy destination is not FP32')
    devices = {str(p.device) for p in params}
    require(len(devices) == 1, 'Single-device inference required')
    report = {'adapter':adapter_name, 'layers':len(layers), 'tensors':len(params),
              'allocated_dtypes_before_promotion':dict(before), 'copy_destination_dtype':'torch.float32',
              'promoted_before_checkpoint_load':True, 'device':next(iter(devices)),
              'base_cast_to_fp32':False, 'low_cpu_mem_usage':False}
    if emit: emit('before_checkpoint_copy', report)
    # The adapter is already registered, so PEFT does not create BF16 modules again.
    result = model.load_adapter(str(adapter_dir), adapter_name=adapter_name, is_trainable=False,
                                torch_device=next(iter(devices)), local_files_only=True,
                                autocast_adapter_dtype=True, low_cpu_mem_usage=False)
    report = dict(report, missing_keys=list(result.missing_keys), unexpected_keys=list(result.unexpected_keys))
    if emit: emit('after_checkpoint_copy', report)
    require(not result.missing_keys and not result.unexpected_keys, 'Adapter state keys did not load exactly')
    model.requires_grad_(False)
    model.eval()
    return report


def compare_adapter_tensors(loaded, saved):
    """Diagnostic evidence; only exact FP32 equality is accepted by the caller."""
    import torch
    common = sorted(set(loaded) & set(saved))
    report = {'loaded_tensors':len(loaded), 'saved_tensors':len(saved),
              'missing_keys':sorted(set(saved)-set(loaded)), 'unexpected_keys':sorted(set(loaded)-set(saved)),
              'loaded_dtypes':dict(Counter(str(t.dtype) for t in loaded.values())),
              'saved_dtypes':dict(Counter(str(t.dtype) for t in saved.values())),
              'equal_tensors':0, 'different_tensors':0, 'nonfinite_tensors':0,
              'shape_mismatches':[], 'differences':[], 'maximum_absolute_difference':0.0,
              'all_differences_match_fp32_bf16_fp32':None}
    rounded_matches = []
    for key in common:
        actual = loaded[key].detach().cpu()
        expected = saved[key].detach().cpu()
        if actual.shape != expected.shape:
            report['shape_mismatches'].append(key)
            continue
        if not torch.isfinite(actual).all().item() or not torch.isfinite(expected).all().item():
            report['nonfinite_tensors'] += 1
            continue
        if torch.equal(actual, expected):
            report['equal_tensors'] += 1
            continue
        report['different_tensors'] += 1
        rounded = expected.to(torch.bfloat16).to(torch.float32)
        match = actual.dtype == torch.float32 and expected.dtype == torch.float32 and torch.equal(actual, rounded)
        rounded_matches.append(match)
        maximum = float((actual.float()-expected.float()).abs().max())
        report['maximum_absolute_difference'] = max(maximum, report['maximum_absolute_difference'])
        report['differences'].append({'key':key,'max_abs_difference':maximum,
                                      'equals_fp32_bf16_fp32_reference':match})
    if rounded_matches:report['all_differences_match_fp32_bf16_fp32'] = all(rounded_matches)
    report['exact_fp32'] = (set(loaded) == set(saved) and bool(saved)
                           and report['equal_tensors'] == len(saved)
                           and all(t.dtype == torch.float32 for t in list(loaded.values())+list(saved.values())))
    return report
