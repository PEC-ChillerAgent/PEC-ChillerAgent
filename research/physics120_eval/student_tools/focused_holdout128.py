"""Frozen focused1186 inference-only132 generations;one held-out quality pass."""
import argparse,json,math,os,time,traceback
from datetime import datetime,timezone
from pathlib import Path
from student_tools.native_sft_data import require,token_digest
from student_tools.teacher_physics_sft import preflight,adapter_exact,evaluate_arm
from student_tools.focused_holdout_support import (PURPOSE,ADAPTER_SHA,TEST_KEY,verify_package,generation_only_score,
 automated_scores,summarize,claim_once,save,sha)

DEFAULT_ADAPTER='/root/epfs/chiller_focused_task_sft_kit_v1/results/focused_task_20261120_011938_24235/adapter_focused_epoch1'

def run(args,root,m,reg,plan,rows,controls,judges,refs,records):
 stats=preflight(args,m,initialization='frozen_focused1186_inference_only_holdout128')
 import torch
 from transformers import AutoTokenizer,AutoModelForCausalLM,set_seed
 from peft import PeftModel
 tok=AutoTokenizer.from_pretrained(str(args.model_dir),local_files_only=True,trust_remote_code=False)
 prompts={}
 for row in controls+rows:
  ids=tok.apply_chat_template(row['request']['messages'],tools=None,enable_thinking=False,tokenize=True,add_generation_prompt=True)
  require(row['prompt_reference']=={'prompt_tokens':len(ids),'token_ids_sha256':token_digest(ids)} and len(ids)+2048<=8192,'Native prompt/context drift')
  require(row['case_id'] not in prompts,'Duplicate prompt ID');prompts[row['case_id']]=ids
 save(args.output/'native_prompt_check.json',{'passed':True,'prompts':132,'no_input_truncation':True,'reference_answers_in_model_input':False})
 save(args.output/'actual_eval_requests.json',rows);save(args.output/'actual_control_requests.json',controls)
 set_seed(42)
 base=AutoModelForCausalLM.from_pretrained(str(args.model_dir),torch_dtype=torch.bfloat16,attn_implementation='sdpa',device_map={'':0},local_files_only=True,trust_remote_code=False,use_safetensors=True)
 model=PeftModel.from_pretrained(base,str(args.adapter_dir),is_trainable=False,local_files_only=True,autocast_adapter_dtype=True)
 model.eval();model.requires_grad_(False);model.config.use_cache=True
 require(set(model.peft_config)=={'default'} and all(not p.requires_grad and p.grad is None for p in model.parameters()),'Parameters must all be frozen')
 tensors={n:p for n,p in model.named_parameters() if 'lora_' in n}
 require(len(tensors)==504 and all(p.dtype==torch.float32 for p in tensors.values()),'FP32 adapter precision changed')
 frozen={n:p.detach().reshape(-1)[:64].cpu().clone() for n,p in model.named_parameters() if 'lora_' not in n}
 adapter_exact(model,args.adapter_dir,args.output,'initial_focused1186')
 save(args.output/'model_setup.json',{'selected_adapter_sha256':ADAPTER_SHA,'adapter_FP32_tensors':504,
  'base_dtype':'bfloat16','adapter_dtype':'float32','all_parameters_frozen':True,'optimizer_created':False,'training_run':False,'adapters_stacked':False})
 startup=[];dummy={r['case_id']:None for r in controls+rows}
 evaluate_arm(model,tok,prompts,controls,dummy,startup,args.output,'startup_control',write_summary=False,score_fn=generation_only_score)
 require(len(startup)==4,'Missing startup controls')
 for r in startup:require(r['completion']['completion_token_ids']==refs[r['case_id']]['completion']['completion_token_ids'],'Focused startup control differs;do not open final inference')
 adapter_exact(model,args.adapter_dir,args.output,'after_controls')
 save(args.output/'startup_control_check.json',{'exact_controls':4,'known_errors_preserved':True,'final_inference_started_only_after_controls':True})
 marker=claim_once(args.registry_dir,{'run_output':str(args.output),'bundle_sha256':sha(args.bundle),
  'pre_registration_sha256':sha(root/'pre_registration.json'),'final_manifest_sha256':reg['source_holdout_manifest_sha256']})
 save(args.output/'one_time_registry.json',{'marker':str(marker),'marker_sha256':sha(marker),'created_before_final_attempts':True})
 save(args.output/'evaluation_started.json',{'selected_adapter_sha256':ADAPTER_SHA,'final_cases':128,'training_run':False,
  'automatic_retries':0,'judging_deferred_until_all_raw_answers_saved':True,'registry_key':TEST_KEY})
 attempts=args.output/'final_attempts.jsonl'
 require(not attempts.exists(),'Preserve attempt trace')
 def marked_rows():
  with attempts.open('x',encoding='utf8') as f:
   for position,row in enumerate(rows,1):
    f.write(json.dumps({'attempt':position,'case_id':row['case_id'],'request_sha256':row['request_sha256'],
     'started_at_UTC':datetime.now(timezone.utc).isoformat(),'retry':0})+'\n');f.flush()
    yield row
 torch.cuda.reset_peak_memory_stats();start=time.perf_counter()
 # No judge object or answer reference is passed to generation. The constant
 # placeholder score lets the shared evaluator save immutable raw records first.
 evaluate_arm(model,tok,prompts,marked_rows(),dummy,records,args.output,'holdout_raw',write_summary=False,score_fn=generation_only_score)
 torch.cuda.synchronize();seconds=time.perf_counter()-start
 require(len(records)==128 and [r['case_id'] for r in records]==[r['case_id'] for r in rows],'Incomplete held-out generation')
 adapter_exact(model,args.adapter_dir,args.output,'after_final')
 require(all(not p.requires_grad and p.grad is None for p in model.parameters()),'Inference enabled gradient state')
 for n,p in model.named_parameters():
  if n in frozen:require(torch.equal(p.detach().reshape(-1)[:64].cpu(),frozen[n]),'Base parameter sample changed')
 verified=json.loads((args.output/'weights_verified.json').read_text(encoding='utf8'))['file_sha256']
 require(all(sha(Path(name))==digest for name,digest in verified.items()),'Original base/tokenizer/adapter file changed')
 save(args.output/'ending_identity_check.json',{'all_input_model_files_rehashed':True,'all_adapter_tensors_exact':True,
  'base_parameter_samples_unchanged':True,'all_parameters_frozen':True,'no_optimizer_or_weight_update':True})
 scored=automated_scores(rows,records,judges)
 with (args.output/'automated_scores128.jsonl').open('x',encoding='utf8') as f:
  for row in scored:f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
 summary=summarize(rows,records,scored)
 times=sorted(r['generation_seconds'] for r in records)
 summary.update(fresh_generations=132,startup_controls=4,final_generations=128,one_time_marker=str(marker),
  final_generation_seconds=seconds,median_generation_seconds=(times[63]+times[64])/2,
  p95_generation_seconds_nearest_rank=times[math.ceil(.95*128)-1],
  peak_allocated_GiB=torch.cuda.max_memory_allocated()/2**30,peak_reserved_GiB=torch.cuda.max_memory_reserved()/2**30,
  startup_controls_exact=True,all_model_files_rehashed_after=True,judges_consumed_after_generation=True)
 save(args.output/'holdout_summary.json',summary)
 receipt=marker.with_name(TEST_KEY+'.completed.json')
 with receipt.open('x',encoding='utf8') as f:json.dump({'run_output':str(args.output),'answers':128,'completed_at_UTC':datetime.now(timezone.utc).isoformat(),
  'summary_sha256':sha(args.output/'holdout_summary.json'),'content_accuracy':None,'review_required':True},f,indent=2)
 print(json.dumps({'complete':True,'final_answers':128,'controls':4,'training_run':False,'content_accuracy':None,'editorial_review':'pending'}),flush=True)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bundle',type=Path,default=Path('bundle_manifest.json'))
 p.add_argument('--model-dir',type=Path,default=Path('/root/epfs/chiller_student_baseline_kit_v1/models/Qwen3-8B'))
 p.add_argument('--adapter-dir',type=Path,default=Path(DEFAULT_ADAPTER));p.add_argument('--registry-dir',type=Path,default=Path('/root/epfs/chiller_student_evaluation_registry'))
 p.add_argument('--output',type=Path,required=True)
 mode=p.add_mutually_exclusive_group(required=True);mode.add_argument('--run',action='store_true');mode.add_argument('--validate-package-only',action='store_true')
 args=p.parse_args()
 for n in ('bundle','output','model_dir','adapter_dir','registry_dir'):setattr(args,n,getattr(args,n).expanduser().resolve())
 require(not args.output.exists() and not any(args.output.is_relative_to(d) for d in (args.model_dir,args.adapter_dir)),'Use a new output outside weights')
 require(not any(args.registry_dir.is_relative_to(d) for d in (args.model_dir,args.adapter_dir)),'Registry must be outside original model directories')
 root,m,reg,plan,rows,controls,judges,refs=verify_package(args.bundle);args.output.mkdir(parents=True)
 save(args.output/'run_manifest.json',{'purpose':PURPOSE,'bundle_sha256':sha(args.bundle),'selected_adapter_sha256':ADAPTER_SHA,
  'test_registry_key':TEST_KEY,'test_manifest_sha256':reg['source_holdout_manifest_sha256'],
  'evaluation_requested':args.run,'training_run':False,'expected_cases':128,'planned_generations':132,
  'model_dir':str(args.model_dir),'adapter_dir':str(args.adapter_dir),'registry_dir':str(args.registry_dir),
  'teacher_calls':0,'automatic_deployment':False})
 if args.validate_package_only:
  save(args.output/'package_check.json',{'passed':True,'heldout_cases':128,'startup_controls':4,'preselected_model':'focused1186',
   'original_source_seal_verified':True,'training_parent_overlap':0,'model_loaded':False,'training_run':False,'teacher_calls':0,'registry_created':False})
  print('Package passed:128 held-out cases plus4 exact controls;0 model/GPU/training/API calls and no final-attempt marker created.');return
 os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
 import fcntl
 (root/'results').mkdir(exist_ok=True);handle=(root/'results/.focused_holdout128.lock').open('a');records=[]
 try:
  fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
  save(args.output/'process.json',{'PID':os.getpid(),'exclusive_package_lock':True})
  run(args,root,m,reg,plan,rows,controls,judges,refs,records)
 except Exception as exc:
  save(args.output/'evaluation_error.json',{'error_type':type(exc).__name__,'error':str(exc),'traceback':traceback.format_exc(),
   'final_inference_started':(args.output/'evaluation_started.json').exists(),'final_answers_saved':len(records),
   'automatic_retry':False,'training_run':False,'do_not_delete_registry_or_rerun_final':True});raise
 finally:handle.close()

if __name__=='__main__':main()
