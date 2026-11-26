"""Fixed32 TRAIN coverage repair, one complete978 single-pass continuation."""
import copy,json,random
from pathlib import Path
from collections import Counter
from types import SimpleNamespace
from student_tools.native_sft_data import require,token_digest
from student_tools.joint_physics_support import canonical_hash,TraceCollator,selection_value
from student_tools.paired_support import sha,save
from student_tools.task08_sft_support import score as selection_score
from student_tools.planned_alignment_support import score as frozen_score
from student_tools.planned_task_contract_v2 import validate_request
from student_tools.development_guard_v8 import score as diagnostic
from student_tools.explanation_protocol import validate_explanation
from student_tools.explanation_number_gate_v8 import render_answer
from student_tools.typed_physics_claims_v3 import check_claims

PURPOSE='targeted_complete_answer32_single_pass_continuation_v1'
INITIAL_SHA='11a99658110bd32d57c6f464abe597f7bd764440800ad0d384bbf01a2e86bba1'
SOURCE_RETURN_SHA='1818bbacdb5b76289941032c303276560e6fdb5b7f00fa8edf669481b8b8b7ca'
MIX={'task08':512,'explanation_replay':60,'selection_replay':51,'compound09':48,'selection09':16,'complete_teacher':64,'targeted_teacher':32}
WEIGHTS={'task08':1,'explanation_replay':1,'selection_replay':2,'compound09':2,'selection09':2,'complete_teacher':1,'targeted_teacher':6}
ARMS=('retained_reference','targeted_after')

def training_order(rows):
 order=[r['sample_id'] for r in sorted(rows,key=lambda r:r['sample_id']) for _ in range(WEIGHTS[r['training_bucket']])]
 random.Random(42).shuffle(order);return order

def score(completion,row,judge):
 if row['family']=='selection':return selection_score(completion,row,judge)
 old=frozen_score(completion,row,judge);latest=diagnostic(completion,row['request'],judge['required_fact_ids'])
 return {**old,'original_frozen_v7_score':copy.deepcopy(old),'offline_v8':latest,
  'protocol_passed':latest['protocol_passed'],'required_fact_coverage_passed':latest['required_fact_coverage_passed'],
  'safe_protocol_passed':latest['diagnostic_passed'],'actual_task_success':None,'domain_accuracy':None,'finite_checks_are_not_accuracy':True}

def verify_package(path):
 path=Path(path).resolve();root=path.parent;m=json.loads(path.read_text(encoding='utf8'))
 require(m['purpose']==PURPOSE and m['environment_spec_hash']=='5befcb78' and not m['final_holdout_included'],'Wrong purpose/environment/split')
 require(m['adapter_files_sha256']['adapter_model.safetensors']==INITIAL_SHA,'Wrong complete978 start')
 require(len(m['files'])==len({v['path'] for v in m['files']}),'Duplicate package member')
 for v in m['files']:
  p=(root/v['path']).resolve();require(p.is_relative_to(root) and not p.is_symlink() and sha(p)==v['sha256'],'Changed package file: '+v['path'])
 load=lambda n:[json.loads(l) for l in (root/n).read_text(encoding='utf8').splitlines() if l.strip()]
 plan=json.loads((root/'training_plan.json').read_text(encoding='utf8'))
 require(plan['purpose']==PURPOSE and plan['initialization_adapter_sha256']==INITIAL_SHA and plan['learning_rates']=={'targeted':5e-6},'Training design drift')
 require(plan['optimizer_steps_per_candidate']==1058 and plan['epochs_per_candidate']==1 and plan['batch_size']==plan['gradient_accumulation_steps']==1 and not plan['resume_optimizer'] and plan['intermediate_step'] is None,'Fixed budget drift')
 rows=load('data/train.messages.jsonl');original=load('checks/original_train751.jsonl');sources={r['sample_id']:r for r in original}
 require(len(rows)==len({r['sample_id'] for r in rows})==783 and Counter(r['training_bucket'] for r in rows)==MIX,'Training mix/IDs drift')
 require(Counter(r['family'] for r in rows)=={'explanation':716,'selection':67},'Task mix drift')
 order=training_order(rows);require(order==plan['train_visit_order'] and len(order)==1058 and len(set(order))==783,'Weighted order drift')
 require(rows[:751]==original and sha(root/'checks/original_train751.jsonl')==plan['original751_file_sha256'],'Old751 rows must remain exact')
 approvals={r['sample_id']:r for r in load('checks/row_approvals.jsonl')};teacher={r['case_id']:r for r in load('checks/raw_teacher32.jsonl')}
 inputs={r['case_id']:r for r in load('checks/teacher_inputs32.jsonl')};reviews={r['case_id']:r for r in load('checks/teacher_reviews32.jsonl')};lineage={r['case_id']:r for r in load('checks/teacher_lineage32.jsonl')}
 require(len(approvals)==783 and len(original)==751 and len(teacher)==len(inputs)==len(reviews)==len(lineage)==32,'Source/approval count drift')
 excluded=set(plan['excluded_parent_source_record_ids']);requests=[]
 for r in rows:
  sid=r['sample_id'];a=approvals[sid]
  require(r['assigned_split']=='train' and r['training_approved'] and a['approved_row_sha256']==canonical_hash(r) and not a['expert_certified'],'Unapproved row')
  require(not set(r.get('parent_source_record_ids',[r['parent_source_record_id']]))&excluded,'Held-out parent in TRAIN')
  req={'messages':r['messages'][:-1],'tools':None};require([v['role'] for v in r['messages']]==['system','user','assistant'] and canonical_hash(req)==r['request_sha256'],'Input/role drift')
  if r['training_bucket']=='targeted_teacher':
   cid=r['teacher_case_id'];raw=teacher[cid];review=reviews[cid];src=lineage[cid]
   require(req==inputs[cid]['request'] and src['split']=='train' and src['Python_evidence_unchanged'] and src['parent_source_record_id']==r['parent_source_record_id'],'Teacher source drift')
   require(raw['HTTP_status']==200 and raw['completion']['finish_reason']=='stop' and raw['retry']==0,'Incomplete raw teacher')
   require(review['approved'] and review['editor_reviewed'] and not review['expert_certified'] and review['raw_record_sha256']==canonical_hash(raw),'Unreviewed teacher answer')
   require(r['messages'][-1]['content']==review['approved_target'],'Unapproved target text')
   source=sources[src['source_sample_id']];old=json.loads(source['messages'][1]['content']);new=json.loads(req['messages'][1]['content'])
   for p in (old,new):p.pop('question');p['tool_evidence'].pop('answer_task_plan')
   require(old==new and canonical_hash(source)==src['source_row_sha256'],'New question changed Python evidence')
  else:require(r==sources[sid],'Old751 row changed')
  if r['family']=='explanation':
   e=validate_request(req)['tool_evidence'];validate_explanation(r['messages'][-1]['content'],[SimpleNamespace(**f) for f in e['facts']],renderer=render_answer)
   require(check_claims(r['messages'][-1]['content'],req)['passed_known_checks'],'Known reference contradiction')
  else:selection_value(r['messages'][-1]['content'],req)
  requests.append(r['request_sha256'])
 require(len(set(requests))==783,'Duplicate training input')
 evaluation=load('data/eval_inputs.jsonl');jj=load('checks/judge_only.jsonl');judges={r['case_id']:r for r in jj};refs=load('checks/retained_references.jsonl');controls=load('checks/startup_controls.jsonl')
 require(len(evaluation)==len(jj)==len(judges)==len(refs)==140 and len(controls)==4,'Development/control count drift')
 require(Counter(r['evaluation_group'] for r in evaluation)=={'planned64':64,'planned40':40,'selection36':36},'Full development denominator changed')
 rr={r['case_id']:r for r in refs};by={r['case_id']:r for r in evaluation}
 for r in evaluation:
  require(set(r)=={'case_id','family','evaluation_group','request','request_sha256','prompt_reference'} and canonical_hash(r['request'])==r['request_sha256'] and r['request_sha256'] not in requests,'Development collision/leakage')
  require([v['role'] for v in r['request']['messages']]==['system','user'] and r['request']['tools'] is None,'Answers in inference history')
  ref=rr[r['case_id']];require(ref['checkpoint_sha256']==INITIAL_SHA and ref['source_zip_sha256']==SOURCE_RETURN_SHA and ref['request_sha256']==r['request_sha256'],'Reference identity/input drift')
  require(token_digest(ref['completion']['completion_token_ids'])==ref['completion']['completion_token_ids_sha256'],'Reference token drift')
  require(ref['rescored']==score(ref['completion'],r,judges[r['case_id']]),'Reference score drift')
  if r['family']=='explanation':require(validate_request(r['request'])['tool_evidence']['facts']==judges[r['case_id']]['facts'],'Fact inventory drift')
 require(set(plan['control_case_ids'])=={r['case_id'] for r in controls},'Control ID drift')
 for c in controls:require(c==rr[c['case_id']],'Control reference differs')
 return root,m,plan,rows,evaluation,judges

def merge_references(records,rows,judges,refs,controls):
 expected={r['case_id']:r for r in controls};require(len(records)==len(expected)==4 and len({r['case_id'] for r in records})==4,'Controls incomplete')
 for r in records:require(r['arm']=='retained_control' and r['completion']['completion_token_ids']==expected[r['case_id']]['completion']['completion_token_ids'],'Complete978 control token mismatch')
 records.clear();by={r['case_id']:r for r in rows}
 for ref in refs:
  row=by[ref['case_id']];records.append({'case_id':ref['case_id'],'arm':'retained_reference','family':row['family'],'evaluation_group':row['evaluation_group'],
   'request_sha256':row['request_sha256'],'completion':copy.deepcopy(ref['completion']),'score':copy.deepcopy(ref['rescored']),'original_score':copy.deepcopy(ref['original_score']),
   'checkpoint_sha256':INITIAL_SHA,'source_zip_sha256':SOURCE_RETURN_SHA,'response_origin':'historical_exact_input_not_new_inference','generation_seconds':None,
   'original_run_generation_seconds':ref['original_generation_seconds'],'teacher_calls':0,'retries':0})

def summarize(records,rows):
 expected={(a,r['case_id']) for a in ARMS for r in rows};got={(r['arm'],r['case_id']) for r in records}
 require(len(got)==len(records) and got<=expected,'Duplicate/unknown comparison output');groups={}
 for g in ('planned64','planned40','selection36'):
  groups[g]={}
  for a in ARMS:
   rr=[r for r in records if r['evaluation_group']==g and r['arm']==a]
   item={'answers':len(rr),'protocol_passes':sum(r['score']['protocol_passed'] for r in rr),'truncated':sum(r['completion']['finish_reason']=='length' for r in rr),
    'model_only_fully_correct_complete':None,'domain_accuracy':None,'actual_page_fallbacks':None}
   if g=='selection36':item['selection_protocol_and_safety_passes']=sum(r['score']['selection_gate_passed'] for r in rr)
   else:item.update(offline_v8_finite_passes=sum(r['score']['offline_v8']['diagnostic_passed'] for r in rr),required_fact_coverage_passes=sum(r['score']['required_fact_coverage_passed'] for r in rr))
   groups[g][a]=item
 return {'complete':got==expected,'answers':len(records),'expected_answers':280,'groups':groups,'final_holdout_cases':0,'independent_test':False,'deployment_approved':False,
  'actual_page_tested':False,'domain_accuracy':None,'semantic_review':'pending_editorial','automatic_checkpoint_selection':False,'finite_checks_are_not_task_accuracy':True,'all_original_development_cases_retained':True}
