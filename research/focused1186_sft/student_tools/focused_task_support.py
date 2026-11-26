"""Reviewed32 focused TRAIN references;one815-row/1186-visit SFT candidate."""
import copy,json,random
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from student_tools.native_sft_data import require,token_digest
from student_tools.joint_physics_support import canonical_hash,TraceCollator,selection_value
from student_tools.targeted_task_support import score,WEIGHTS as OLD_WEIGHTS
from student_tools.paired_support import sha,save
from student_tools.planned_task_contract_v2 import validate_request
from student_tools.explanation_protocol import validate_explanation
from student_tools.explanation_number_gate_v8 import render_answer
from student_tools.typed_physics_claims_v3 import check_claims

PURPOSE='focused_teacher32_single_candidate_SFT815_visits1186_v1'
INITIAL_SHA='79b247f68597d64de0dc667344229ce9462e617ae2b782b389fc3588c614bef3'
SOURCE_RETURN_SHA='b249c73232ab425e22aca3b5f31b240124f8a0c42764be3a3e65d72db514c3cb'
WEIGHTS={**OLD_WEIGHTS,'focused_teacher':4}
MIX={'task08':512,'explanation_replay':60,'selection_replay':51,'compound09':48,'selection09':16,'complete_teacher':64,'targeted_teacher':32,'focused_teacher':32}

def training_order(rows):
 order=[r['sample_id'] for r in sorted(rows,key=lambda r:r['sample_id']) for _ in range(WEIGHTS[r['training_bucket']])]
 random.Random(42).shuffle(order);return order

def verify_package(path):
 path=Path(path).resolve();root=path.parent;m=json.loads(path.read_text(encoding='utf8'))
 require(m['purpose']==PURPOSE and m['environment_spec_hash']=='5befcb78' and not m['final_holdout_included'] and not m['automatic_deployment'],'Purpose/environment drift')
 require(m['adapter_files_sha256']['adapter_model.safetensors']==INITIAL_SHA,'Wrong initial79b247 candidate;never DPO1849')
 require(len(m['files'])==len({f['path'] for f in m['files']}),'Duplicate manifest files')
 for f in m['files']:
  p=(root/f['path']).resolve();require(p.is_relative_to(root) and not p.is_symlink() and sha(p)==f['sha256'],'Changed package file:'+f['path'])
 load=lambda n:[json.loads(s) for s in (root/n).read_text(encoding='utf8').splitlines() if s.strip()]
 plan=json.loads((root/'training_plan.json').read_text(encoding='utf8'))
 require(plan['purpose']==PURPOSE and plan['initialization_adapter_sha256']==INITIAL_SHA and plan['optimizer_steps']==1186 and plan['learning_rates']=={'focused':5e-6},'Frozen pilot design drift')
 require(plan['weights']==WEIGHTS and not plan['resume_optimizer'] and plan['intermediate_checkpoint_search'] is False,'Update design drift')
 rows=load('data/train.messages.jsonl');original=load('checks/original_train783.jsonl')
 require(len(rows)==815 and len({r['sample_id'] for r in rows})==815 and rows[:783]==original and sha(root/'checks/original_train783.jsonl')==plan['original783_file_sha256'],'Original783/new815 drift')
 require(Counter(r['training_bucket'] for r in rows)==MIX and Counter(r['family'] for r in rows)=={'explanation':748,'selection':67},'Task mix drift')
 require(training_order(rows)==plan['train_visit_order'] and len(plan['train_visit_order'])==1186,'Weighted order drift')
 inputs={r['case_id']:r for r in load('checks/teacher_inputs32.jsonl')};reviews={r['case_id']:r for r in load('checks/teacher_reviews32.jsonl')}
 raw={r['case_id']:r for r in load('checks/raw_teacher32.jsonl')};lineage={r['case_id']:r for r in load('checks/teacher_lineage32.jsonl')}
 require(len(inputs)==len(reviews)==len(raw)==len(lineage)==32,'Teacher source denominator drift')
 auth=json.loads((root/'checks/teacher_authorization.json').read_text(encoding='utf8'));tm=json.loads((root/'checks/teacher_input_manifest.json').read_text(encoding='utf8'))
 require(auth['user_reply']=='授权这批32条教师采集' and auth['data_manifest_sha256']==sha(root/'checks/teacher_input_manifest.json'),'Teacher batch not explicitly authorized')
 require(tm['teacher_inputs_sha256']==sha(root/'checks/teacher_inputs32.jsonl') and tm['lineage_sha256']==sha(root/'checks/teacher_lineage32.jsonl'),'Teacher registered input drift')
 source={r['sample_id']:r for r in original};excluded=set(plan['excluded_parent_source_record_ids']);requests=[]
 approvals={r['sample_id']:r for r in load('checks/row_approvals815.jsonl')};require(len(approvals)==815,'Approval count drift')
 for r in rows:
  require(r['assigned_split']=='train' and r['training_approved'] and not set(r.get('parent_source_record_ids',[r['parent_source_record_id']]))&excluded,'Unapproved/heldout TRAIN row')
  a=approvals[r['sample_id']];require(a['approved_row_sha256']==canonical_hash(r) and a['editor_reviewed'] and not a['expert_certified'] and a['split']=='train','Approval identity drift')
  req={'messages':r['messages'][:-1],'tools':None};require([v['role'] for v in r['messages']]==['system','user','assistant'] and canonical_hash(req)==r['request_sha256'],'Input roles/identity drift')
  if r['training_bucket']=='focused_teacher':
   cid=r['teacher_case_id'];rev=reviews[cid];rr=raw[cid];link=lineage[cid]
   require(req==inputs[cid]['request'] and rev['approved'] and rev['training_approved'] and rev['editor_reviewed'] and not rev['expert_certified'],'Unapproved focused reference')
   require(rev['raw_record_sha256']==canonical_hash(rr) and rr['HTTP_status']==200 and rr['retry']==0 and rr['completion']['finish_reason']=='stop','Incomplete/changed teacher response')
   require(r['messages'][-1]['content']==rev['approved_target'] and rev['target_basis']=='teacher_assisted_editor_rewritten_and_partly_templated_not_raw_teacher_verbatim','Focused target changed')
   src=source[link['source_sample_id']];require(canonical_hash(src)==link['source_row_sha256'] and src['parent_source_record_id']==r['parent_source_record_id'],'Source parent/row drift')
   a=json.loads(src['messages'][1]['content']);b=json.loads(req['messages'][1]['content'])
   for p in (a,b):p.pop('question');p['tool_evidence'].pop('answer_task_plan')
   require(a==b and link['Python_evidence_unchanged'] and link['split']=='train','New question changed physics evidence')
  else:require(r==source[r['sample_id']],'Old TRAIN row changed')
  if r['family']=='explanation':
   e=validate_request(req)['tool_evidence'];validate_explanation(r['messages'][-1]['content'],[SimpleNamespace(**f) for f in e['facts']],renderer=render_answer)
   require(check_claims(r['messages'][-1]['content'],req)['passed_known_checks'],'Known target contradiction')
  else:selection_value(r['messages'][-1]['content'],req)
  requests.append(r['request_sha256'])
 require(len(set(requests))==815,'Duplicate training request')
 evaluation=load('data/eval_inputs.jsonl');judges={r['case_id']:r for r in load('checks/judge_only.jsonl')}
 refs=load('checks/retained_dev_references140.jsonl');controls=load('checks/startup_controls.jsonl');by={r['case_id']:r for r in evaluation}
 require(len(evaluation)==len(by)==len(judges)==172 and len(refs)==140 and len(controls)==4,'Eval/reference denominator drift')
 require(Counter(r['evaluation_group'] for r in evaluation)=={'focused_train32':32,'planned64':64,'planned40':40,'selection36':36},'Group drift')
 require(evaluation[32:]==load('checks/original_DEV140_inputs.jsonl'),'Original DEV inputs changed')
 require([judges[r['case_id']] for r in evaluation[32:]]==load('checks/original_DEV140_judges.jsonl'),'Original DEV judges changed')
 newby={r['sample_id']:r for r in rows[783:]}
 for row in evaluation:
  require(set(row)=={'case_id','family','evaluation_group','request','request_sha256','prompt_reference'} and canonical_hash(row['request'])==row['request_sha256'],'Inference request drift')
  require([v['role'] for v in row['request']['messages']]==['system','user'] and row['request']['tools'] is None,'Target in generation history')
  if row['evaluation_group']=='focused_train32':
   target=newby[row['case_id']];require(row['request']=={'messages':target['messages'][:-1],'tools':None},'TRAIN-fit request not exact')
   require(judges[row['case_id']]['rubric_origin']=='approved_TRAIN_target_citations_not_independent_test','TRAIN-fit score not declared label-derived')
  else:require(row['request_sha256'] not in requests,'DEV input in TRAIN')
  if row['family']=='explanation':require(validate_request(row['request'])['tool_evidence']['facts']==judges[row['case_id']]['facts'],'Fact inventory drift')
 refby={r['case_id']:r for r in refs};require(len(refby)==140,'Duplicate reference')
 for ref in refs:
  row=by[ref['case_id']];require(row['evaluation_group']!='focused_train32' and ref['checkpoint_sha256']==INITIAL_SHA and ref['source_zip_sha256']==SOURCE_RETURN_SHA and ref['request_sha256']==row['request_sha256'],'Wrong historical reference')
  require(token_digest(ref['completion']['completion_token_ids'])==ref['completion']['completion_token_ids_sha256'] and ref['score']==score(ref['completion'],row,judges[row['case_id']]),'Old response/score drift')
 require(set(plan['control_case_ids'])=={r['case_id'] for r in controls},'Control ID drift')
 for c in controls:require(c==refby[c['case_id']],'Control not exact historical response')
 return root,m,plan,rows,evaluation,judges

def merge_references(records,rows,judges,refs,controls):
 expected={r['case_id']:r for r in controls}
 require(len(records)==len({r['case_id'] for r in records})==4 and {r['case_id'] for r in records}==set(expected),'Controls incomplete/duplicate')
 for r in records:require(r['arm']=='retained_control' and r['completion']['completion_token_ids']==expected[r['case_id']]['completion']['completion_token_ids'],'Targeted1058 control token mismatch')
 records.clear();by={r['case_id']:r for r in rows}
 for ref in refs:
  row=by[ref['case_id']];records.append({'case_id':ref['case_id'],'arm':'retained_reference','family':row['family'],'evaluation_group':row['evaluation_group'],
   'request_sha256':row['request_sha256'],'completion':copy.deepcopy(ref['completion']),'score':copy.deepcopy(ref['score']),
   'checkpoint_sha256':INITIAL_SHA,'source_zip_sha256':SOURCE_RETURN_SHA,'response_origin':'historical_exact_input_not_new_inference',
   'generation_seconds':None,'original_run_generation_seconds':ref['original_generation_seconds'],'teacher_calls':0,'retries':0})

def summarize(records,rows):
 by={r['case_id']:r for r in rows};require(len(by)==len(rows)==172,'Fixed comparison denominator drift')
 expected={(a,r['case_id']) for a in ('retained_reference','focused_after') for r in rows};got={(r['arm'],r['case_id']) for r in records}
 require(len(got)==len(records) and got<=expected,'Duplicate/unknown comparison output')
 require(all(r['evaluation_group']==by[r['case_id']]['evaluation_group'] and r['family']==by[r['case_id']]['family'] for r in records),'Comparison group drift')
 groups={}
 for g in ('focused_train32','planned64','planned40','selection36'):
  groups[g]={}
  for arm in ('retained_reference','focused_after'):
   rr=[r for r in records if r['arm']==arm and r['evaluation_group']==g]
   v={'answers':len(rr),'truncated':sum(r['completion']['finish_reason']=='length' for r in rr),'actual_task_success':None,'domain_accuracy':None}
   if g=='selection36':v['selection_gate_passes']=sum(r['score']['selection_gate_passed'] for r in rr)
   else:v.update(original_v7_passes=sum(r['score']['original_frozen_v7_score']['aligned_safe_protocol_passed'] for r in rr),offline_v8_finite_passes=sum(r['score']['offline_v8']['diagnostic_passed'] for r in rr),required_fact_coverage_passes=sum(r['score']['required_fact_coverage_passed'] for r in rr))
   groups[g][arm]=v
 return {'complete':got==expected,'comparison_records':len(records),'expected_records':344,'groups':groups,'domain_accuracy':None,
  'actual_task_success':None,'independent_test':False,'final_holdout_included':False,'actual_page_tested':False,'actual_page_fallbacks':None,
  'fallback_counted_as_student_success':False,'semantic_review':'pending_editorial','deployment_approved':False,'automatic_checkpoint_selection':False}
