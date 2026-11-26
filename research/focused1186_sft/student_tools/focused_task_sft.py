"""One focused teacher32 SFT from retained1058:815 rows,1186 fixed visits."""
import argparse,json,math,os,time,traceback
from pathlib import Path
from student_tools.native_sft_data import require,encode_sample,FinalOnlyCollator,token_digest
from student_tools.teacher_physics_sft import preflight,adapter_exact,evaluate_arm
from student_tools.focused_task_support import PURPOSE,verify_package,training_order,TraceCollator,score,summarize,merge_references,save,sha

DEFAULT_ADAPTER='/root/epfs/chiller_targeted_task_sft_kit_v1/results/targeted_task_20261119_055737_64864/adapter_targeted_epoch1'

def run(args,root,m,plan,rows,evaluation,judges,records):
    stats=preflight(args,m,initialization='retained_targeted1058_focused_teacher32_fresh_optimizer')
    import torch
    from transformers import AutoTokenizer,AutoModelForCausalLM,Trainer,TrainingArguments,TrainerCallback,set_seed
    from peft import PeftModel,get_peft_model_state_dict
    from torch.utils.data import SequentialSampler
    tok=AutoTokenizer.from_pretrained(str(args.model_dir),local_files_only=True,trust_remote_code=False);tok.padding_side='right'
    encoded={};checks=[];prompts={}
    for r in rows:
        f,c=encode_sample(tok,r);encoded[r['sample_id']]=f;checks.append(c)
    require(checks==[json.loads(l) for l in (root/'checks/native_encoding_reference.jsonl').read_text(encoding='utf8').splitlines()],'Native labels/tokenizer drift')
    for r in evaluation:
        ids=tok.apply_chat_template(r['request']['messages'],tools=None,enable_thinking=False,tokenize=True,add_generation_prompt=True)
        require(r['prompt_reference']=={'prompt_tokens':len(ids),'token_ids_sha256':token_digest(ids)},'Eval prompt drift')
        require(len(ids)+2048<=8192,'No context truncation allowed');prompts[r['case_id']]=ids
    save(args.output/'encoding_check.json',{'checks':checks,'evaluation_prompts':172,'final_answer_only':True,'no_truncation':True,'development_targets_in_gradients':0})
    save(args.output/'actual_eval_requests.json',evaluation)
    set_seed(42)
    base=AutoModelForCausalLM.from_pretrained(str(args.model_dir),torch_dtype=torch.bfloat16,attn_implementation='sdpa',
        device_map={'':0},local_files_only=True,trust_remote_code=False,use_safetensors=True)
    model=PeftModel.from_pretrained(base,str(args.adapter_dir),is_trainable=True,local_files_only=True,autocast_adapter_dtype=True)
    require(set(model.peft_config)=={'default'},'One training adapter only')
    initial=adapter_exact(model,args.adapter_dir,args.output,'initial_retained_targeted1058')
    trainable={n:p for n,p in model.named_parameters() if p.requires_grad}
    require(len(trainable)==504 and all('lora_' in n and p.dtype==torch.float32 for n,p in trainable.items()),'LoRA trainability/precision drift')
    require(all(p.dtype==torch.bfloat16 for n,p in model.named_parameters() if n not in trainable),'Base precision drift')
    frozen={n:p.detach().reshape(-1)[:64].cpu().clone() for n,p in model.named_parameters() if not p.requires_grad}
    save(args.output/'model_setup.json',{'initial_adapter_sha256':m['adapter_files_sha256']['adapter_model.safetensors'],
        'trainable_tensors':504,'trainable_parameters':sum(p.numel() for p in trainable.values()),'adapter_dtype':'float32',
        'base_dtype':'bfloat16','historical_adapters_stacked':False,'new_optimizer':True,'candidate':args.candidate})
    controls=plan['control_case_ids'];control_rows=[r for r in evaluation if r['case_id'] in controls]
    evaluate_arm(model,tok,prompts,control_rows,judges,records,args.output,'retained_control',write_summary=False,score_fn=score)
    refs=[json.loads(l) for l in (root/'checks/retained_dev_references140.jsonl').read_text(encoding='utf8').splitlines()]
    control_refs=[json.loads(l) for l in (root/'checks/startup_controls.jsonl').read_text(encoding='utf8').splitlines()]
    merge_references(records,evaluation,judges,refs,control_refs)
    fresh_before=[r for r in evaluation if r['evaluation_group']=='focused_train32']
    require(len(fresh_before)==32,'New TRAIN baseline denominator drift')
    evaluate_arm(model,tok,prompts,fresh_before,judges,records,args.output,'retained_reference',write_summary=False,score_fn=score)
    require(len(records)==172 and len({r['case_id'] for r in records})==172,'Missing/duplicate before answers')
    save(args.output/'before_accounting.json',{'fresh_controls':4,'controls_exact':True,'fresh_initial_TRAIN_answers':32,'reused_DEV_answers':140,'comparison_records':172,
        'fresh_controls_checkpoint':'retained_targeted1058','comparison_checkpoint':'same_retained_targeted104_plus_selection36_and_fresh_train32','controls_not_comparison_answers':True,'reference_reuse_not_new_inference':True,'old_errors_preserved':True})
    save(args.output/'before_comparison_records.json',records)
    adapter_exact(model,args.adapter_dir,args.output,'after_controls')
    order=training_order(rows);collator=FinalOnlyCollator(tok.pad_token_id);trace=TraceCollator(collator,order,1,args.output/'training_sample_trace.jsonl')
    features=[encoded[max(encoded,key=lambda k:len(encoded[k]['input_ids']))],encoded[min(encoded,key=lambda k:len(encoded[k]['input_ids']))]]
    batch=collator(features)
    for i,f in enumerate(features):
        n=len(f['labels']);require(batch['labels'][i,:n].tolist()==f['labels'] and (batch['labels'][i,n:]==-100).all().item(),'Padding supervised')
    del batch
    saved=[]
    def checkpoint(label,step):
        directory=args.output/('adapter_focused_'+label);model.save_pretrained(str(directory),safe_serialization=True)
        stored=adapter_exact(model,directory,args.output,label+'_serialized')
        changed=sum(not torch.equal(stored[k],initial[k]) for k in stored);require(changed>0,'No parameter update')
        save(args.output/(label+'_adapter_manifest.json'),{'step':step,'adapter_dir':str(directory),'changed_tensors':changed,
            'fp32_serialization_exact':True,'files':{p.name:{'sha256':sha(p),'bytes':p.stat().st_size} for p in directory.iterdir() if p.is_file()}})
        saved.append(step)
    class Audit(TrainerCallback):
        gradients=0
        def on_pre_optimizer_step(self,args_,state,control,model=None,**kwargs):
            gg=[p.grad for p in trainable.values() if p.grad is not None]
            require(len(gg)==504 and all(torch.isfinite(g).all().item() for g in gg),'Missing/nonfinite gradient')
            require(all(p.grad is None for n,p in model.named_parameters() if n not in trainable),'Frozen base received gradient')
            norm=float(torch.stack([torch.linalg.vector_norm(g.detach().float()) for g in gg]).norm().item())
            require(math.isfinite(norm) and norm>0,'Zero/nonfinite gradient norm');self.gradients+=1
            with (args.output/'gradient_checks.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps({'step':state.global_step+1,'tensors':len(gg),'norm_after_clipping':norm})+'\n')
        def on_log(self,args_,state,control,logs=None,**kwargs):
            if logs:
                require(all(math.isfinite(float(logs[k])) for k in ('loss','grad_norm','train_loss') if k in logs),'Nonfinite loss/log')
                with (args.output/'trainer_logs.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(logs,allow_nan=False)+'\n')
        def on_step_end(self,args_,state,control,**kwargs):
            print('FOCUSED_TASK_'+args.candidate.upper()+'_STEP '+str(state.global_step)+'/1186',flush=True)
    class OrderedTrainer(Trainer):
        def _get_train_sampler(self,*a,**k):return SequentialSampler(self.train_dataset)
    model.config.use_cache=False;callback=Audit();lr=plan['learning_rates'][args.candidate]
    training=TrainingArguments(output_dir=str(args.output/'trainer'),max_steps=1186,num_train_epochs=1,
        per_device_train_batch_size=1,gradient_accumulation_steps=1,learning_rate=lr,lr_scheduler_type='constant',
        warmup_steps=0,weight_decay=0.,max_grad_norm=1.,bf16=True,fp16=False,tf32=False,
        gradient_checkpointing=True,gradient_checkpointing_kwargs={'use_reentrant':False},optim='adamw_torch',
        logging_strategy='steps',logging_steps=1,logging_nan_inf_filter=False,save_strategy='no',eval_strategy='no',
        report_to=[],disable_tqdm=True,seed=42,data_seed=42,dataloader_num_workers=0,dataloader_pin_memory=False,
        remove_unused_columns=False,label_names=['labels'],save_safetensors=True)
    trainer=OrderedTrainer(model=model,args=training,train_dataset=[{'sample_id':sid,**encoded[sid]} for sid in order],data_collator=trace,callbacks=[callback])
    save(args.output/'training_started.json',{'purpose':PURPOSE,'training_run':True,'candidate':args.candidate,'learning_rate':lr,
        'max_steps':1186,'unique_training_rows':815,'weighted_visits':1186,'weighted_data_passes':1,'selected_ids':order,'new_optimizer':True,'seed':42,'final_holdout_included':False,'teacher_calls':0})
    torch.cuda.reset_peak_memory_stats();start=time.perf_counter();trained=trainer.train();torch.cuda.synchronize()
    require(trainer.state.global_step==callback.gradients==1186 and trace.seen==order and saved==[],'Unexpected updates/visits/checkpoints')
    checkpoint('epoch1',1186);require(saved==[1186],'Incomplete checkpoints')
    evaluate_arm(model,tok,prompts,evaluation,judges,records,args.output,'focused_after',write_summary=False,score_fn=score)
    final=args.output/'adapter_focused_epoch1';adapter_exact(model,final,args.output,'after_generation')
    for n,p in model.named_parameters():
        if n in frozen:require(torch.equal(p.detach().reshape(-1)[:64].cpu(),frozen[n]),'Frozen base sample changed')
    for name,stat in stats.items():
        p=Path(name);require((p.stat().st_size,p.stat().st_mtime_ns)==stat,'Preserved weight metadata changed')
    require(all(sha(args.adapter_dir/n)==h for n,h in m['adapter_files_sha256'].items()),'Initial adapter file changed')
    from student_tools.adapter_precision import add_fp32_adapter_then_load,compare_adapter_tensors
    from safetensors.torch import load_file
    from torch.nn.attention import sdpa_kernel,SDPBackend
    model.eval();model.requires_grad_(False);model.gradient_checkpointing_disable();model.config.use_cache=True
    probe=torch.tensor([prompts[evaluation[0]['case_id']]],dtype=torch.long,device='cuda:0')
    def logits():
        with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16),sdpa_kernel(backends=[SDPBackend.MATH]):
            return model(input_ids=probe,attention_mask=torch.ones_like(probe),use_cache=False).logits[0,-1].detach().cpu()
    before=logits();add_fp32_adapter_then_load(model,final,'reload_focused',emit=lambda stage,report:save(args.output/('reload_'+stage+'.json'),report))
    precision=compare_adapter_tensors(get_peft_model_state_dict(model,adapter_name='reload_focused'),load_file(str(final/'adapter_model.safetensors'),device='cpu'))
    require(precision['exact_fp32'] and precision['equal_tensors']==504,'FP32 reload differs')
    model.set_adapter('reload_focused');model.eval();model.requires_grad_(False);require(torch.equal(before,logits()),'Reload changed next-token logits')
    save(args.output/'reload_check.json',{'tensors':precision,'next_token_logits_exact':True,'adapters_combined':False})
    summary=summarize(records,evaluation);require(summary['complete'],'Incomplete development answers')
    summary.update(candidate=args.candidate,learning_rate=lr,training_run=True,optimizer_steps=1186,finite_gradient_checks=callback.gradients,
        train_visit_order_verified=True,base_sample_probes_unchanged=True,starting_adapter_rehashed=True,reload_check_passed=True,
        base_full_rehash_after_training=False,original_weight_metadata_unchanged=True,completed_weighted_data_passes=1,
        fresh_generations=208,reused_answers=140,unique_training_rows=815,weighted_training_visits=1186,startup_control_generations=4,fresh_initial_TRAIN_answers=32,fresh_after_answers=172,comparison_fresh_generations=204,training_and_eval_seconds=time.perf_counter()-start,
        peak_allocated_GiB=torch.cuda.max_memory_allocated()/2**30,peak_reserved_GiB=torch.cuda.max_memory_reserved()/2**30,trainer_metrics=trained.metrics)
    save(args.output/'focused_summary.json',summary);print(json.dumps({'complete':True,'candidate':args.candidate,'updates':1186,'fresh_answers':208,'reused_answers':140,'deployment_approved':False}),flush=True)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bundle',type=Path,default=Path('bundle_manifest.json'))
    p.add_argument('--model-dir',type=Path,default=Path('/root/epfs/chiller_student_baseline_kit_v1/models/Qwen3-8B'));p.add_argument('--adapter-dir',type=Path,default=Path(DEFAULT_ADAPTER))
    p.add_argument('--candidate',choices=('focused',),default='focused');p.add_argument('--output',type=Path,required=True)
    mode=p.add_mutually_exclusive_group(required=True);mode.add_argument('--run',action='store_true');mode.add_argument('--validate-package-only',action='store_true')
    args=p.parse_args()
    for n in ('output','model_dir','adapter_dir'):setattr(args,n,getattr(args,n).expanduser().resolve())
    require(not args.output.exists() and not any(args.output.is_relative_to(d) for d in (args.model_dir,args.adapter_dir)),'Use new output outside preserved weights')
    root,m,plan,rows,evaluation,judges=verify_package(args.bundle);args.output.mkdir(parents=True)
    save(args.output/'run_manifest.json',{'purpose':PURPOSE,'bundle_sha256':sha(args.bundle),'candidate':args.candidate,
        'learning_rate':plan['learning_rates'][args.candidate],'training_requested':args.run,'planned_steps':1186,'unique_training_rows':815,'weighted_visits':1186,'planned_fresh_answers':208,
        'planned_reused_answers':140,'model_dir':str(args.model_dir),'adapter_dir':str(args.adapter_dir),'final_holdout_included':False})
    if args.validate_package_only:
        save(args.output/'package_check.json',{'passed':True,'train_rows':815,'weighted_visits':1186,'task08_rows':512,'old_replay_rows':111,'old_compound_rows':48,'old_selection_rows':16,'old_teacher_rows':64,'previous_teacher_rows':32,'new_focused_teacher_rows':32,'eval_cases':172,'GPU_loaded':False,'training_run':False})
        print('Package passed:815 unique TRAIN rows,1186 fixed visits,32 new TRAIN probes and140 unchanged development cases;0 model/teacher/training calls.');return
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';records=[]
    import fcntl
    lock=(root/'results'/'.focused_task_run.lock');lock.parent.mkdir(exist_ok=True)
    lock_handle=lock.open('a')
    try:fcntl.flock(lock_handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        save(args.output/'busy.json',{'error':'Another process holds this package lock; no new GPU job started','automatic_retry':False})
        raise ValueError('This package already has a running job; do not relaunch.')
    try:run(args,root,m,plan,rows,evaluation,judges,records)
    except Exception as exc:
        save(args.output/'focused_error.json',{'error_type':type(exc).__name__,'error':str(exc),'traceback':traceback.format_exc(),
            'training_started':(args.output/'training_started.json').exists(),'answers_saved':len(records),'automatic_retry':False})
        save(args.output/'incomplete_focused_summary.json',summarize([r for r in records if r.get('arm') in ('retained_reference','focused_after')],evaluation));raise
    finally:lock_handle.close()

if __name__=='__main__':main()
