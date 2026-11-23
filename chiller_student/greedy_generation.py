"""Pinned Transformers 4.51.3 greedy decoding with actual prepared-config audit.

An explicit GenerationConfig(False) alone is insufficient: model defaults can
replace values equal to global defaults. Disable that merge and pass kwargs.
The instance-local observer is serial-only and is restored even on failure.
"""
import copy
from types import MethodType
from chiller_student.native_sft_data import require


def public_config(config):
    return {k:v for k,v in config.to_dict().items() if not k.startswith('_') and k!='transformers_version'}


def generate_greedy(model, *, generation_config, on_prepared, **kwargs):
    require(generation_config.do_sample is False,'Requested config must disable sampling')
    require(generation_config.num_beams==1 and generation_config.num_return_sequences==1,'Greedy batch-one mode required')
    require(not any(k in kwargs for k in ('use_model_defaults','do_sample','num_beams','num_return_sequences')),
            'Generation controls belong to this guarded wrapper')
    core=model.get_base_model() if hasattr(model,'get_base_model') else model
    requested=generation_config.to_dict()
    expected=copy.deepcopy(generation_config)
    token_defaults={}
    for key in ('bos_token_id','eos_token_id','pad_token_id','decoder_start_token_id'):
        if getattr(expected,key) is None:
            value=getattr(model.generation_config,key)
            if value is not None:
                setattr(expected,key,copy.deepcopy(value));token_defaults[key]=value
    expected_dict=public_config(expected)
    had_override='_prepare_generation_config' in core.__dict__
    previous_override=core.__dict__.get('_prepare_generation_config')
    original=core._prepare_generation_config
    calls=[]

    def checked_prepare(instance,config,use_model_defaults=None,**model_kwargs):
        require(not calls,'Unexpected repeated generation-config preparation')
        effective,unused=original(config,use_model_defaults,**model_kwargs)
        actual=public_config(effective)
        differences={k:{'expected':expected_dict.get(k),'actual':actual.get(k)}
                     for k in set(expected_dict)|set(actual) if expected_dict.get(k)!=actual.get(k)}
        mode=effective.get_generation_mode().value
        audit={'requested_generation_config':requested,'resolved_expected_generation_config':expected.to_dict(),
               'actual_prepared_generation_config':effective.to_dict(),'actual_generation_mode':mode,
               'use_model_defaults':use_model_defaults,'explicit_do_sample_kwarg':model_kwargs.get('do_sample'),
               'resolved_token_defaults':token_defaults,'unexpected_differences':differences,
               'passed':not differences and mode=='greedy_search' and use_model_defaults is False and model_kwargs.get('do_sample') is False,
               'audit_point':'Actual GenerationMixin preparation inside generate, before any model forward/token choice'}
        calls.append(audit)
        on_prepared(audit)
        require(audit['passed'],'Actual generation config is not the frozen greedy request')
        return effective,unused

    core._prepare_generation_config=MethodType(checked_prepare,core)
    try:
        result=model.generate(generation_config=expected,use_model_defaults=False,
            do_sample=False,num_beams=1,num_return_sequences=1,**kwargs)
        require(len(calls)==1 and calls[0]['passed'],'Generation bypassed prepared-config guard')
        return result
    finally:
        if had_override:core._prepare_generation_config=previous_override
        else:delattr(core,'_prepare_generation_config')
