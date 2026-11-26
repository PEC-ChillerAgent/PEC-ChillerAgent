"""Frozen reviewed task08 data, c506 references, and development-only scoring."""
import json,random,copy
from pathlib import Path
from types import SimpleNamespace
from collections import Counter
from student_tools.native_sft_data import require,token_digest
from student_tools.paired_support import sha,save
from student_tools.joint_physics_support import canonical_hash,TraceCollator,selection_value,score_selection
from student_tools.task_explanation import validate_request
from student_tools.explanation_protocol import validate_explanation
from student_tools.explanation_number_gate_v5 import render_answer
from student_tools.explanation_consistency_v3 import check_consistency
from student_tools.explanation_quality import check_repetition
from student_tools.grounded_physics_support import score_completion,explanation_renderer

PURPOSE='task08_reviewed512_sft_lr_compare_v1'
ARMS=('c506_reference','task08_after')
INITIAL_SHA='c506e4a6ddd7159bcb7fb80567453756d765664937dfe0a1c22109acdfa83a22'

def training_order(rows):
    order=sorted(r['sample_id'] for r in rows);random.Random(42).shuffle(order);return order

def score(completion,row,judge):
    if row['family']=='selection':return score_selection(completion,row,judge)
    if row['evaluation_group']!='task08_dev64':return score_completion(completion,judge,explanation_renderer())
    result={'protocol_passed':False,'required_fact_coverage_passed':False,'protocol_and_coverage_passed':False,
        'finite_checks_passed':False,'domain_accuracy':None,'semantic_review':'pending','model_text_repaired':False}
    try:
        report=validate_explanation(completion['content'],[SimpleNamespace(**f) for f in judge['facts']],renderer=render_answer)
        known=check_consistency(completion['content'],row['request']);repeat=check_repetition(report['model_authored_answer_template'])
        required=set(judge['required_fact_ids']);cited=set(report['cited_fact_ids'])
        result.update(protocol_passed=completion['finish_reason']=='stop',required_fact_coverage_passed=required<=cited,
            cited_fact_ids=report['cited_fact_ids'],missing_required_fact_ids=sorted(required-cited),
            rendered_answer=report['rendered_answer'],known_pattern_checks=known,repetition_check=repeat)
        result['protocol_and_coverage_passed']=result['protocol_passed'] and result['required_fact_coverage_passed']
        result['finite_checks_passed']=result['protocol_and_coverage_passed'] and known['passed_known_checks'] and repeat['passed_repetition_check']
    except (ValueError,KeyError,TypeError,AttributeError) as exc:result['protocol_error']=str(exc)[:240]
    return result

def verify_package(path):
    path=Path(path).resolve();root=path.parent;m=json.loads(path.read_text(encoding='utf8'))
    require(m['purpose']==PURPOSE and m['environment_spec_hash']=='5befcb78' and m['adapter_files_sha256']['adapter_model.safetensors']==INITIAL_SHA,'Wrong package/start')
    require(len(m['files'])==len({e['path'] for e in m['files']}),'Duplicate manifest path')
    for e in m['files']:
        f=(root/e['path']).resolve();require(f.is_relative_to(root) and sha(f)==e['sha256'],'Package drift: '+e['path'])
    load=lambda n:[json.loads(l) for l in (root/n).read_text(encoding='utf8').splitlines() if l.strip()]
    plan=json.loads((root/'training_plan.json').read_text(encoding='utf8'));train=load('data/train.messages.jsonl')
    evaluation=load('data/eval_inputs.jsonl');jj=load('checks/judge_only.jsonl');judges={r['case_id']:r for r in jj}
    require(plan['purpose']==PURPOSE and plan['learning_rates']=={'low':3e-6,'high':1e-5} and plan['epochs_per_candidate']==1
        and plan['optimizer_steps_per_candidate']==623 and plan['intermediate_step']==312
        and plan['batch_size']==plan['gradient_accumulation_steps']==1 and not plan['resume_optimizer'],'Training design drift')
    require(len(train)==len({r['sample_id'] for r in train})==623,'Training count/duplicate ID')
    require(Counter(r['training_bucket'] for r in train)=={'task08':512,'selection_replay':51,'explanation_replay':60},'Training mix drift')
    require(plan['train_visit_order']==training_order(train) and len(set(plan['train_visit_order']))==623,'Visit order/duplicates')
    reviews=load('checks/task08_approved_reviews.jsonl');approved={r['case_id']:r for r in reviews}
    require(len(reviews)==len(approved)==512 and all(r['editor_reviewed'] and r['training_approved'] for r in reviews),'Missing approved references')
    old=load('checks/legacy_replay_reference.jsonl');replay={r['sample_id']:r for r in old}
    require(len(old)==len(replay)==111,'Replay reference changed')
    forbidden=set(plan['excluded_parent_source_record_ids']);hashes=[]
    for r in train:
        require(r['training_approved'] and r['assigned_split']=='train' and [x['role'] for x in r['messages']]==['system','user','assistant'],'Unapproved/invalid train row')
        parents=set(r.get('parent_source_record_ids',[r['parent_source_record_id']]))
        require(not parents&forbidden,'Held parent in gradients')
        req={'messages':r['messages'][:-1],'tools':None};h=canonical_hash(req);hashes.append(h);require(h==r['request_sha256'],'Train prompt changed')
        if r['training_bucket']=='task08':
            validate_request(req);a=approved[r['sample_id'].removeprefix('task08_reviewed_')]
            require(a['target_content']==r['messages'][-1]['content'] and a['raw_teacher_record_sha256']==r['raw_teacher_record_sha256'],'Label lineage drift')
            facts=json.loads(req['messages'][1]['content'])['tool_evidence']['facts']
            validate_explanation(a['target_content'],[SimpleNamespace(**f) for f in facts],renderer=render_answer)
            require(check_consistency(a['target_content'],req)['passed_known_checks'],'Known reference contradiction')
        else:
            require(r==replay[r['sample_id']],'Historical replay changed')
            if r['family']=='selection':selection_value(r['messages'][-1]['content'],req)
            else:
                facts=json.loads(req['messages'][1]['content'])['tool_evidence']['facts']
                validate_explanation(r['messages'][-1]['content'],[SimpleNamespace(**f) for f in facts],renderer=explanation_renderer())
    require(len(set(hashes))==623,'Duplicate training prompt')
    require(len(evaluation)==len(jj)==len(judges)==len({r['case_id'] for r in evaluation})==140,'Expected64 new plus76 old development cases')
    require(sum(r['evaluation_group']=='task08_dev64' for r in evaluation)==64,'Wrong task development set')
    for r in evaluation:
        require(set(r)=={'case_id','family','evaluation_group','request','request_sha256','prompt_reference'},'Target or judge in inference row')
        require([x['role'] for x in r['request']['messages']]==['system','user'] and r['request']['tools'] is None,'Target/history in inference')
        require(canonical_hash(r['request'])==r['request_sha256'] and r['request_sha256'] not in hashes,'Prompt drift/train-eval collision')
        j=judges[r['case_id']]
        if r['evaluation_group']=='task08_dev64':
            validate_request(r['request']);require(j['parent_source_record_id'] in plan['task_development_parent_ids'],'Wrong development parent')
        if r['family']=='explanation':require(json.loads(r['request']['messages'][1]['content'])['tool_evidence']['facts']==j['facts'],'Fact drift')
    refs=load('checks/c506_reference_records.jsonl');byid={r['case_id']:r for r in evaluation}
    require(len(refs)==len({r['case_id'] for r in refs})==140,'Baseline count drift')
    for r in refs:
        require(r['request_sha256']==byid[r['case_id']]['request_sha256'] and r['checkpoint_sha256']==INITIAL_SHA,'Reference checkpoint/request drift')
        require(token_digest(r['completion']['completion_token_ids'])==r['completion_token_ids_sha256'],'Baseline tokens changed')
    require(len(plan['control_case_ids'])==4 and set(plan['control_case_ids'])<=set(byid),'Control drift')
    return root,m,plan,train,evaluation,judges

def merge_references(records,rows,judges,refs,controls):
    fresh={r['case_id']:r for r in records};expected={r['case_id']:r for r in refs}
    require(set(fresh)==set(controls),'Expected four fresh controls before reference reuse')
    for cid,r in fresh.items():
        require(r['completion']['completion_token_ids']==expected[cid]['completion']['completion_token_ids'] and r['request_sha256']==expected[cid]['request_sha256'],'c506 control drift: '+cid)
        r['arm']='c506_reference'
    for row in rows:
        if row['case_id'] in fresh:continue
        ref=expected[row['case_id']]
        records.append({'case_id':row['case_id'],'family':row['family'],'evaluation_group':row['evaluation_group'],
            'request_sha256':row['request_sha256'],'arm':'c506_reference','completion':copy.deepcopy(ref['completion']),
            'score':score(ref['completion'],row,judges[row['case_id']]),'response_origin':'audited_reference_reuse',
            'reference_provenance':ref['provenance'],'original_score':ref['original_score'],'generation_seconds':None,'teacher_calls':0,'retries':0})

def summarize(records,rows):
    expected={(a,r['case_id']) for a in ARMS for r in rows};got={(r['arm'],r['case_id']) for r in records}
    require(len(got)==len(records) and got<=expected,'Duplicate/unknown comparison answer')
    groups={}
    for group in sorted({r['evaluation_group'] for r in rows}):
        groups[group]={}
        for arm in ARMS:
            rr=[r for r in records if r['arm']==arm and r['evaluation_group']==group]
            item={'answers':len(rr),'protocol_passes':sum(r['score']['protocol_passed'] for r in rr),
                'truncated':sum(r['completion']['finish_reason']=='length' for r in rr),'domain_accuracy':None}
            if any(r['family']=='selection' for r in rr):item['selection_gate_passes']=sum(r['score'].get('selection_gate_passed',False) for r in rr)
            else:
                item['protocol_and_coverage_passes']=sum(r['score'].get('protocol_and_coverage_passed',False) for r in rr)
                if group=='task08_dev64':item['finite_checks_passes']=sum(r['score'].get('finite_checks_passed',False) for r in rr)
            groups[group][arm]=item
    return {'complete':got==expected,'answers':len(records),'expected_answers':280,'groups':groups,
        'domain_accuracy':None,'factual_and_task_completeness_review':'pending','teacher_calls':0,'final_holdout_cases':0,
        'independent_test':False,'deployment_approved':False,'automatic_checkpoint_selection':False,
        'reference_reuse_not_new_generation':True,'task_checks':'v5_number/v3_known_claims; finite diagnostics, not semantic certification',
        'legacy_checks':'unchanged historical v2 numeric protocol; task gate changes separately reported'}
