"""One preselected focused1186 source-file holdout;no training or retries."""
import copy,json,os,zipfile
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

from student_tools.native_sft_data import require,token_digest
from student_tools.paired_support import sha,save
from student_tools.joint_physics_support import canonical_hash
from student_tools.planned_task_contract_v2 import from_task_request,validate_request
from student_tools.targeted_task_support import score as original_score

PURPOSE='focused1186_preselected_source_file_holdout128_20261122_v1'
ADAPTER_SHA='136eeeb15c1751b8a32628fc525ba680e783e3bf1cbbc546e54a64ab00eca8ab'
FOCUSED_RETURN_SHA='70bc90246d36377ff63dc1b791b2fc21676d8ca2ef9531afe4cb76d3e5f6158a'
TEST_KEY='focused136eee_task08_final128_v3'

def verify_package(path):
 path=Path(path).resolve();root=path.parent;m=json.loads(path.read_text(encoding='utf8'))
 require(m['purpose']==PURPOSE and m['environment_spec_hash']=='5befcb78','Purpose/environment drift')
 require(m['adapter_files_sha256']['adapter_model.safetensors']==ADAPTER_SHA and m['training_run'] is False and not m['automatic_deployment'],'Candidate/scope changed')
 require(len(m['files'])==len({f['path'] for f in m['files']}),'Duplicate manifest path')
 for f in m['files']:
  raw=root/f['path'];p=raw.resolve()
  require(p.is_relative_to(root) and not raw.is_symlink() and p.stat().st_size==f['bytes'] and sha(p)==f['sha256'],'Package changed:'+f['path'])
 read=lambda n:[json.loads(s) for s in (root/n).read_text(encoding='utf8').splitlines() if s.strip()]
 reg=json.loads((root/'pre_registration.json').read_text(encoding='utf8'))
 require(reg['version']==PURPOSE and reg['selected_adapter_sha256']==ADAPTER_SHA and reg['one_candidate_only'],'Preselection changed')
 require(reg['generation']=={'runtime_profile':'strict_math','attention':'sdpa_math','enable_thinking':False,'do_sample':False,'max_new_tokens':2048,'num_beams':1,'repetition_penalty':1.0,'seed':42,'quality_passes_per_case':1,'automatic_retries':0},'Generation settings changed')
 require(reg['model_selection_frozen_before_parsing_final_jobs_and_judges'] and reg['no_training_or_optimizer'],'Selection/gradient policy changed')
 for name,h in reg['request_transformation_code_sha256'].items():require(sha(root/'student_tools'/name)==h,'Frozen input compiler changed')
 sealed=json.loads((root/'checks/sealed_final/sealed_manifest.json').read_text(encoding='utf8'))
 require(sha(root/'checks/sealed_final/sealed_manifest.json')==reg['source_holdout_manifest_sha256'],'Original seal changed')
 for f in sealed['files']:require(sha(root/'checks/sealed_final'/f['path'])==f['sha256'],'Sealed data changed')
 jobs=read('checks/sealed_final/jobs.jsonl');original_judges=read('checks/sealed_final/judge_only.jsonl')
 sources=read('checks/sealed_final/source_artifacts.jsonl');parents=read('checks/sealed_final/source_rows.jsonl')
 rows=read('data/model_inputs128.jsonl');judges=read('checks/judge_only128.jsonl')
 require(len(jobs)==len(rows)==len(judges)==len(sources)==128 and len(parents)==8,'Held-out denominator changed')
 require(len({r['case_id'] for r in rows})==128 and Counter(r['question_kind'] for r in rows)==Counter({k:8 for k in json.loads((root/'test_plan.json').read_text(encoding='utf8'))['question_kinds']}),'Task distribution changed')
 oldj={r['case_id']:r for r in original_judges};by_source={r['case_id']:r for r in sources};parent_ids={r['parent_source_record_id'] for r in parents}
 source_train=read('checks/training815_provenance.jsonl')
 train_parents={v for r in source_train for v in r.get('parent_source_record_ids',[r['parent_source_record_id']])}
 require(not parent_ids&train_parents,'Final parent is in training')
 request_hashes={r['request_sha256'] for r in source_train}
 contexts={}
 for source,row,judge in zip(jobs,rows,judges):
  cid=source['case_id'];s=by_source[cid]
  require(source['assigned_split']=='final_locked' and row['case_id']==cid+'__focused_holdout' and row['original_case_id']==cid,'Case identity drift')
  require(source['request_sha256']==canonical_hash(source['request']) and row['request']==from_task_request(source['request']),'Original frozen request transformation changed')
  require(row['request_sha256']==canonical_hash(row['request']) and row['request_sha256'] not in request_hashes,'Question in training/wrong hash')
  require(row['family']=='explanation' and row['evaluation_group']=='heldout128' and row['parent_source_record_id']==source['parent_source_record_id'],'Row metadata drift')
  payload=validate_request(row['request']);e=payload['tool_evidence']
  require([x['role'] for x in row['request']['messages']]==['system','user'] and row['request']['tools'] is None,'Target/history leaked')
  expected={**copy.deepcopy(oldj[cid]),'case_id':row['case_id'],'original_case_id':cid,'facts':copy.deepcopy(e['facts']),
   'original_required_fact_ids_unchanged':True,'reviewer_only':True,'not_model_input':True}
  require(judge==expected and not judge['training_approved'],'Judge/source changed')
  artifact=s['artifact']
  for f in e['facts']:
   value=artifact
   for k in f['pointer'].lstrip('/').split('/'):value=value[int(k)] if isinstance(value,list) else value[k]
   require(f['run_id']==artifact['result']['run_id'] and f['dataset_id'] in (None,artifact['result']['dataset_id']) and value==f['value'],'Cross-run or changed fact')
  contexts[row['case_id']]=judge
 controls=read('checks/startup_controls4.jsonl')
 require(len(controls)==4 and not {r['case_id'] for r in controls}&set(contexts),'Control identities changed')
 require(sha(root/'checks/source_focused_review.zip')==FOCUSED_RETURN_SHA,'Historical focused return changed')
 with zipfile.ZipFile(root/'checks/source_focused_review.zip') as z:
  prefix='focused_task_20261120_011938_24235/'
  original_eval=json.loads(z.read(prefix+'actual_eval_requests.json'))
  refs={r['case_id']:r for r in [json.loads(s) for s in z.read(prefix+'focused_after_records.jsonl').decode('utf8').splitlines()]}
  adapter=json.loads(z.read(prefix+'epoch1_adapter_manifest.json'))
  require({n:f['sha256'] for n,f in adapter['files'].items()}==m['adapter_files_sha256'],'Actual adapter identity drift')
 for row in controls:
  require(row==next(r for r in original_eval if r['case_id']==row['case_id']) and row['case_id'] in refs,'Not an exact historical control')
  require(token_digest(refs[row['case_id']]['completion']['completion_token_ids'])==refs[row['case_id']]['completion']['completion_token_ids_sha256'],'Control tokens changed')
 plan=json.loads((root/'test_plan.json').read_text(encoding='utf8'))
 require(plan['purpose']==PURPOSE and plan['one_time_registry_key']==TEST_KEY and plan['fresh_generations']==132 and plan['final_answers']==128 and plan['controls']==4,'Test budget changed')
 require(not plan['training_run'] and plan['automatic_retries']==0 and not plan['automatic_release'],'No training/retry/release')
 policy=json.loads((root/'checks/original_acceptance_policy.json').read_text(encoding='utf8'))
 require(sha(root/'checks/original_acceptance_policy.json')==reg['acceptance_policy_sha256'],'Original acceptance policy changed')
 kind_to_group={kind:g['group'] for g in policy['groups'] for kind in g['question_kinds']}
 require(plan['major_group_policy']==policy['groups'] and all(r['major_group']==kind_to_group[r['question_kind']] for r in rows),'Major group allocation changed')
 audit=json.loads((root/'checks/prepared_data_audit.json').read_text(encoding='utf8'))
 require(audit['passed'] and audit['physics_scalar_and_current_backend_replays']==128 and audit['numeric_duplicate_checks_passed'],'Physics/isolation not verified')
 return root,m,reg,plan,rows,controls,contexts,refs

def generation_only_score(completion,row,unused):
 return {'protocol_passed':None,'scoring_deferred_until_all_answers_saved':True,'domain_accuracy':None,'teacher_calls':0}

def automated_scores(rows,records,judges):
 by={r['case_id']:r for r in rows}
 require(len(records)==len({r['case_id'] for r in records}) and all(r['case_id'] in by for r in records),'Duplicate/unexpected final record')
 results=[]
 for r in records:
  row=by[r['case_id']]
  require(r['request_sha256']==row['request_sha256'],'Wrong request in answer')
  # This call occurs only after inference has finished and raw answers are saved.
  s=original_score(r['completion'],row,judges[r['case_id']])
  results.append({'case_id':r['case_id'],'question_kind':row['question_kind'],'major_group':row['major_group'],'parent_source_record_id':row['parent_source_record_id'],
   'score':s,'finish_reason':r['completion']['finish_reason'],'semantic_review':'pending','content_complete':None,
   'model_text_repaired':False,'automatic_factual_accuracy_claim':False})
 return results

def summarize(rows,records,scores):
 require(len(rows)==len({r['case_id'] for r in rows})==128,'All128 expected cases must stay in denominator')
 expected={r['case_id'] for r in rows};got={r['case_id'] for r in records}
 require(len(records)==len(got) and got<=expected,'Duplicate/unexpected records')
 require({r['case_id'] for r in scores}==got,'Scored record mismatch')
 by={r['case_id']:r for r in records};groups={}
 for kind in sorted({r['question_kind'] for r in rows}):
  ids={r['case_id'] for r in rows if r['question_kind']==kind};ss=[r for r in scores if r['case_id'] in ids]
  groups[kind]={'expected':len(ids),'answers':len(ss),
   'original_v7_passes':sum(r['score']['original_frozen_v7_score']['aligned_safe_protocol_passed'] for r in ss),
   'required_citation_coverage_passes':sum(r['score']['required_fact_coverage_passed'] for r in ss),
   'original_v7_and_coverage_passes':sum(r['score']['original_frozen_v7_score']['aligned_safe_protocol_passed'] and r['score']['required_fact_coverage_passed'] for r in ss),
   'truncated':sum(by[r['case_id']]['completion']['finish_reason']=='length' for r in ss),
   'content_correct_and_complete':None}
 major_groups={}
 for group in sorted({r['major_group'] for r in rows}):
  ids={r['case_id'] for r in rows if r['major_group']==group};ss=[r for r in scores if r['case_id'] in ids]
  major_groups[group]={'expected':len(ids),'answers':len(ss),
   'original_v7_and_coverage_passes':sum(r['score']['original_frozen_v7_score']['aligned_safe_protocol_passed'] and r['score']['required_fact_coverage_passed'] for r in ss),
   'content_correct_and_complete':None}
 return {'purpose':PURPOSE,'complete':got==expected,'expected_cases':128,'answers':len(records),'question_kind_groups':groups,'major_groups':major_groups,
  'truncated_completions':sum(r['completion']['finish_reason']=='length' for r in records),
  'content_accuracy':None,'model_only_complete_task_rate':None,'domain_accuracy':None,'editorial_review_required':True,
  'finite_checks_are_factual_accuracy':False,'fallback_counted_as_student_success':False,
  'training_run':False,'teacher_calls':0,'automatic_retries':0,'page_tested':False,'HTTP_tested':False,
  'live_physics_execution_in_GPU_job':False,'local_preparation_physics_replays':128,
  'independent_equipment_test':False,'source_file_held_out':True,'source_files':2,'parent_groups':8,
  'source_wording_templates_shared_with_training':True,'deployment_approved':False}

def claim_once(registry_dir,metadata):
 registry_dir=Path(registry_dir).resolve();registry_dir.mkdir(parents=True,exist_ok=True)
 path=registry_dir/(TEST_KEY+'.once.json')
 payload={'test_key':TEST_KEY,'selected_adapter_sha256':ADAPTER_SHA,'created_at_UTC':datetime.now(timezone.utc).isoformat(),
  'PID':os.getpid(),'one_quality_pass_per_case':True,**metadata}
 try:
  with path.open('x',encoding='utf8') as f:json.dump(payload,f,ensure_ascii=False,indent=2)
 except FileExistsError:
  raise ValueError('This selected model/holdout was already started. Preserve registry and return the existing result;do not rerun final cases.') from None
 return path
