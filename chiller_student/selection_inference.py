"""Pinned single-adapter inference backend; loaded lazily on the user's GPU."""
import importlib.metadata,json,os,sys,time
from pathlib import Path
from chiller_student.native_sft_data import require,token_digest
from chiller_student.paired_support import read,save,sha,decode_completion
from chiller_student.greedy_generation import generate_greedy
from chiller_student.adapter_precision import compare_adapter_tensors
from chiller_student.selection_http import validate_api_body
from chiller_student.stability_probe_support import ScoreRecorder,rng_snapshot,module_snapshot


class SelectionEngine:
    backend_kind='real_qwen3_8b_bf16_lora_fp32'
    validate_request=staticmethod(validate_api_body)
    adapter_name='student'
    service_scope='Evidence-grounded inference; not autonomous tool planning.'
    def __init__(self,manifest,model_dir,adapter_dir,output):
        require(sys.version_info[:2]==(3,11),'Use the pinned Python3.11 inference environment')
        require(os.environ.get('CUBLAS_WORKSPACE_CONFIG')==':4096:8','Set CUBLAS_WORKSPACE_CONFIG before process startup')
        require(int(os.environ.get('WORLD_SIZE','1'))==1,'Single-process development service only')
        versions={k:importlib.metadata.version(k) for k in manifest['required_versions']}
        require(versions==manifest['required_versions'],'Environment drift; do not upgrade')
        import torch
        from transformers import AutoModelForCausalLM,AutoTokenizer,GenerationConfig,set_seed
        from peft import PeftModel
        from chiller_student.greedy_generation_regression import run_generation_regression
        self.output=Path(output);self.manifest=manifest;self.adapter_dir=Path(adapter_dir).expanduser().resolve()
        model_dir=Path(model_dir).expanduser().resolve()
        require(model_dir.is_dir() and self.adapter_dir.is_dir() and model_dir!=self.adapter_dir,'Model/adapter paths missing or equal')
        require(not self.output.resolve().is_relative_to(model_dir) and not self.output.resolve().is_relative_to(self.adapter_dir),'Never write into weights')
        require(torch.version.cuda=='12.4' and torch.cuda.is_available() and torch.cuda.device_count()==1 and torch.cuda.is_bf16_supported(),'One assigned BF16 cu124 GPU required')
        free,total=torch.cuda.mem_get_info(0)
        save(self.output/'gpu_preflight.json',{'name':torch.cuda.get_device_name(0),'free_GiB':free/2**30,'total_GiB':total/2**30})
        require(free>=60*2**30,'Need60GiB free; no processes are stopped by this program')
        torch.use_deterministic_algorithms(True);torch.backends.cudnn.deterministic=True
        torch.backends.cudnn.benchmark=False;torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
        set_seed(42)
        x=torch.randn(8,8,generator=torch.Generator().manual_seed(42))
        with torch.autocast('cuda',dtype=torch.bfloat16):y=x.cuda()@x.cuda().T
        torch.cuda.synchronize();require(y.isfinite().all().item() and torch.allclose(y.float().cpu(),x@x.T,atol=.1,rtol=.02),'GPU witness failed')
        save(self.output/'gpu_witness.json',{'passed':True,'max_abs_error':float((y.float().cpu()-x@x.T).abs().max())});del x,y
        save(self.output/'generation_regression.json',run_generation_regression())
        checks=[(model_dir,manifest['base_weights_sha256']),
                (model_dir,manifest['tokenizer_files_sha256']),
                (model_dir,{'config.json':manifest['base_config_sha256'],'generation_config.json':manifest['base_generation_config_sha256']}),
                (self.adapter_dir,manifest['adapter_files_sha256'])]
        hashes={};self.weight_stats={}
        for folder,expected in checks:
            for name,digest in expected.items():
                p=(folder/name).resolve();require(p.is_relative_to(folder),'Unsafe model file path')
                print('HASH_CHECK: '+name,flush=True);actual=sha(p);require(actual==digest,'Weight/config hash changed: '+name)
                hashes[str(p)]=actual;self.weight_stats[str(p)]=(p.stat().st_size,p.stat().st_mtime_ns)
        index=read(model_dir/'model.safetensors.index.json')
        require(set(index['weight_map'].values())==set(manifest['base_weights_sha256']),'Wrong base shard index')
        config=read(self.adapter_dir/'adapter_config.json')
        require(config['peft_type']=='LORA' and config['r']==16 and config['lora_alpha']==32 and config.get('bias')=='none' and not config.get('modules_to_save'),'Wrong pure LoRA config')
        save(self.output/'weights_verified.json',{'file_sha256':hashes,'matches_frozen_candidate':True})
        self.tokenizer=AutoTokenizer.from_pretrained(str(model_dir),local_files_only=True,trust_remote_code=False)
        base=AutoModelForCausalLM.from_pretrained(str(model_dir),torch_dtype=torch.bfloat16,attn_implementation='sdpa',device_map={'':'cuda:0'},local_files_only=True,trust_remote_code=False,use_safetensors=True)
        self.model=PeftModel.from_pretrained(base,str(self.adapter_dir),adapter_name=self.adapter_name,is_trainable=False,local_files_only=True,autocast_adapter_dtype=True)
        self.model.set_adapter(self.adapter_name);self.model.eval();self.model.requires_grad_(False);self.model.config.use_cache=True
        self.verify_adapter('start')
        self.check_mode()
        eos=self.model.generation_config.eos_token_id;eos=[eos] if isinstance(eos,int) else list(eos)
        require(self.tokenizer.eos_token_id in eos,'Tokenizer EOS missing from generation EOS');self.eos=eos
        self.generation=GenerationConfig(max_new_tokens=2048,do_sample=False,num_beams=1,repetition_penalty=1.,use_cache=True,
            eos_token_id=eos,pad_token_id=self.tokenizer.pad_token_id,bos_token_id=self.tokenizer.bos_token_id,return_dict_in_generate=False)
        save(self.output/'model_setup.json',{'versions':versions,'backend':self.backend_kind,'base_dtype':str(base.dtype),
            'adapter':self.adapter_name,'all_parameters_frozen':True,'runtime_profile':'strict_math','max_new_tokens':2048,
            'training_run':False,'scope':self.service_scope})

    def check_mode(self):
        layers=[m for m in self.model.modules() if hasattr(m,'lora_A')]
        require(len(layers)==252 and all(set(m.lora_A)==set(m.lora_B)=={self.adapter_name} and list(m.active_adapters)==[self.adapter_name] and not m.disable_adapters and not m.merged for m in layers),'Wrong single adapter mode')
        require(all(not p.requires_grad for p in self.model.parameters()),'Inference parameters must be frozen')

    def verify_adapter(self,stage):
        from peft import get_peft_model_state_dict
        from safetensors.torch import load_file
        loaded=get_peft_model_state_dict(self.model,adapter_name=self.adapter_name)
        saved=load_file(str(self.adapter_dir/'adapter_model.safetensors'),device='cpu')
        report=compare_adapter_tensors(loaded,saved)
        save(self.output/('adapter_tensor_check_'+stage+'.json'),report)
        require(report['exact_fp32'] and len(saved)==504,'Adapter not504 exact FP32 tensors')
        print('ADAPTER_EXACT: '+self.adapter_name+' 504/504 FP32 identical ('+stage+')',flush=True)
        return report

    def complete(self,body):
        import torch
        from torch.nn.attention import sdpa_kernel,SDPBackend
        from transformers import LogitsProcessorList
        self.validate_request(body);self.check_mode()
        ids=self.tokenizer.apply_chat_template(body['messages'],tools=None,enable_thinking=False,tokenize=True,add_generation_prompt=True)
        require(len(ids)+2048<=8192,'Context budget exceeded; refuse truncation')
        tensor=torch.tensor([ids],dtype=torch.long,device='cuda:0');observer=ScoreRecorder({});prepared=[]
        before=rng_snapshot();state_before=module_snapshot(self.model)
        start=time.perf_counter()
        with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16),sdpa_kernel(backends=[SDPBackend.MATH]):
            output=generate_greedy(self.model,input_ids=tensor,attention_mask=torch.ones_like(tensor),generation_config=self.generation,
                logits_processor=LogitsProcessorList([observer]),on_prepared=prepared.append)
        torch.cuda.synchronize();elapsed=time.perf_counter()-start
        require(output[0,:len(ids)].tolist()==ids,'Generation changed input')
        completion=decode_completion(self.tokenizer,output[0,len(ids):].tolist(),self.eos)
        after=rng_snapshot();state_after=module_snapshot(self.model)
        require(completion['completion_token_ids']==[s['argmax_token_id'] for s in observer.steps],'Greedy observer mismatch')
        require(before==after and state_before==state_after,'Inference RNG/module drift');self.check_mode()
        return {'completion':completion,'prompt_tokens':len(ids),'prompt_token_ids_sha256':token_digest(ids),
            'generation_seconds':elapsed,'actual_generation_config':prepared[0],'score_trace':observer.steps,
            'rng_before':before,'rng_after':after,'state_before':state_before,'state_after':state_after,
            'training_run':False,'model_selection_repaired':False,'domain_accuracy':None}

    def finish(self):
        self.verify_adapter('end');self.check_mode()
        require(all((Path(p).stat().st_size,Path(p).stat().st_mtime_ns)==v for p,v in self.weight_stats.items()),'Weight files changed')
        return {'adapter_exact_at_end':True,'weight_file_size_mtime_unchanged':True,'full_weights_rehashed_after':False}
