"""Tiny CPU Qwen3/PEFT regression reproducing sampling-default override."""
import copy
import json
from pathlib import Path
from chiller_student.native_sft_data import require
from chiller_student.greedy_generation import generate_greedy


def run_generation_regression():
    import torch
    import transformers
    import peft
    from transformers import Qwen3Config,Qwen3ForCausalLM,GenerationConfig,LogitsProcessorList
    from peft import LoraConfig,get_peft_model
    from chiller_student.stability_probe_support import ScoreRecorder
    require(transformers.__version__=='4.51.3' and peft.__version__=='0.15.2','Use the pinned generation stack')
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(42)
        config=Qwen3Config(vocab_size=32,hidden_size=32,intermediate_size=64,num_hidden_layers=1,
            num_attention_heads=4,num_key_value_heads=2,head_dim=8,max_position_embeddings=128,
            use_sliding_window=False,pad_token_id=0,bos_token_id=1,eos_token_id=31)
        base=Qwen3ForCausalLM(config)
        model=get_peft_model(base,LoraConfig(r=2,lora_alpha=4,target_modules=['q_proj','v_proj'],
            lora_dropout=.2,task_type='CAUSAL_LM'),adapter_name='pilot')
        model.add_adapter('round2',LoraConfig(r=2,lora_alpha=4,target_modules=['q_proj','v_proj'],
            lora_dropout=.2,task_type='CAUSAL_LM'))
        # Reproduce the server's model-specific sampling defaults, unlike v1's test.
        model.generation_config=GenerationConfig(do_sample=True,temperature=.6,top_k=20,top_p=.95,
            bos_token_id=1,eos_token_id=31,pad_token_id=0)
        model.generation_config.transformers_version='4.51.3'
        base.generation_config=model.generation_config
        requested=GenerationConfig(max_new_tokens=12,do_sample=False,num_beams=1,repetition_penalty=1.,
            use_cache=True,eos_token_id=[31],pad_token_id=0,bos_token_id=None)
        legacy,_=base._prepare_generation_config(requested)
        require(legacy.do_sample is True and legacy.temperature==.6 and legacy.top_k==20 and legacy.top_p==.95,
                'Legacy default override was not reproduced')
        model.eval();model.requires_grad_(False)
        ids=torch.tensor([[1,4,7,2]]);attention=torch.ones_like(ids)
        # Actual old call: verify random selection diverges from the score argmax.
        observer=ScoreRecorder({})
        original_prepare=base._prepare_generation_config
        with torch.inference_mode():
            legacy_output=model.generate(input_ids=ids,attention_mask=attention,generation_config=requested,
                logits_processor=LogitsProcessorList([observer]))
        legacy_tokens=legacy_output[0,ids.shape[1]:].tolist()
        require(legacy_tokens!=[s['argmax_token_id'] for s in observer.steps], 'Tiny legacy call did not expose sampling mismatch')
        traces=[];callbacks=[]
        from contextlib import nullcontext
        for arm in ('round2','round2','base','base','round2','round2'):
            model.set_adapter('pilot' if arm=='base' else arm);model.eval();model.requires_grad_(False)
            obs=ScoreRecorder({});state=torch.get_rng_state().clone()
            with (model.disable_adapter() if arm=='base' else nullcontext()),torch.inference_mode():
                output=generate_greedy(model,generation_config=requested,on_prepared=callbacks.append,
                    input_ids=ids,attention_mask=attention,logits_processor=LogitsProcessorList([obs]))
            tokens=output[0,ids.shape[1]:].tolist()
            require(tokens==[s['argmax_token_id'] for s in obs.steps],'Guarded greedy argmax mismatch')
            require(torch.equal(state,torch.get_rng_state()),'Guarded greedy changed RNG')
            require(base._prepare_generation_config==original_prepare,'Observer was not restored')
            traces.append({'arm':arm,'tokens':tokens})
        for arm in ('round2','base'):
            require(len({tuple(t['tokens']) for t in traces if t['arm']==arm})==1,'Tiny repeats not identical')
        # Exception must also restore the instance method and preserve model defaults.
        def fail(_):raise RuntimeError('synthetic audit callback failure')
        try:
            generate_greedy(model,generation_config=requested,on_prepared=fail,input_ids=ids,attention_mask=attention)
        except RuntimeError as exc:require(str(exc)=='synthetic audit callback failure','Wrong negative case')
        else:raise ValueError('Negative callback should fail')
        require(base._prepare_generation_config==original_prepare,'Observer leaked after exception')
        require(model.generation_config.do_sample is True and requested.do_sample is False,'Original config mutated')
        return {'passed':True,'cpu_only':True,'torch_version':torch.__version__,'transformers_version':transformers.__version__,
            'peft_version':peft.__version__,'legacy_effective_do_sample':legacy.do_sample,
            'legacy_actual_tokens_differ_from_argmax':True,'fixed_generations':len(traces),
            'fixed_all_actual_modes_greedy':all(c['actual_generation_mode']=='greedy_search' and c['passed'] for c in callbacks),
            'fixed_rng_unchanged':True,'fixed_repeats_identical':True,'observer_restored_after_error':True,
            'fixed_traces':traces,'actual_prepared_config_example':callbacks[0],
            'scope':'Tiny random-weight CPU model with two LoRA adapters; not the real H100 Qwen3-8B result.'}


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();report=run_generation_regression()
    with args.output.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps({'passed':report['passed'],'cpu_only':True,'fixed_generations':report['fixed_generations']}))
