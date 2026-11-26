"""One preregistered interface-aligned SFT; no final test or release."""
import copy,json,math
from pathlib import Path
from collections import Counter
from types import SimpleNamespace
from student_tools.compound_alignment_support import training_order,TraceCollator,MIX,WEIGHTS,INITIAL_SHA
from student_tools.planned_probe_support import score as previous_score
from student_tools.task08_sft_support import score as selection_score
from student_tools.planned_alignment_contract import from_task_request,validate_request
from student_tools.native_sft_data import require,token_digest
from student_tools.joint_physics_support import canonical_hash,selection_value
from student_tools.paired_support import save,sha
from student_tools.typed_physics_claims_v2 import check_claims
from student_tools.explanation_number_gate_v7 import render_answer
from student_tools.explanation_protocol import validate_explanation
from student_tools.explanation_quality import check_repetition

PURPOSE='planned_interface_alignment687_weighted850_sft_v1'
REFERENCE_SHA='9d0e74f2c40409ccf75f5c26b2388f242863f49e9626df6314bad2d481c0e798'
ARMS=('fixed850_reference','aligned_after')

def score(completion,row,judge):
    if row['family']=='selection':return selection_score(completion,row,judge)
    result=previous_score(completion,row,judge)
    try:
        typed=check_claims(completion['content'],row['request'])
        validate_explanation(completion['content'],[SimpleNamespace(**f) for f in judge['facts']],renderer=render_answer)
        protocol=completion['finish_reason']=='stop'
        repeat=check_repetition(json.loads(completion['content'])['answer'])['passed_repetition_check']
    except (ValueError,KeyError,TypeError):
        typed={'passed_known_checks':False,'issues':['UNPARSEABLE_ALIGNED_OUTPUT'],'model_text_repaired':False};protocol=False;repeat=False
    result.update(typed_v2_claim_checks=typed,protocol_v7_passed=protocol,
        aligned_safe_protocol_passed=protocol and typed['passed_known_checks'] and repeat,actual_task_success=None)
    return result

def verify_package(path):
    path=Path(path).resolve();root=path.parent;m=json.loads(path.read_text(encoding='utf8'))
    require(m['purpose']==PURPOSE and m['environment_spec_hash']=='5befcb78' and not m['final_holdout_included']
        and m['adapter_files_sha256']['adapter_model.safetensors']==INITIAL_SHA,'Wrong environment/start/scope')
    require(len(m['files'])==len({x['path'] for x in m['files']}),'Duplicate manifest entry')
    for x in m['files']:
        f=(root/x['path']).resolve();require(f.is_relative_to(root) and sha(f)==x['sha256'],'Package drift: '+x['path'])
    load=lambda n:[json.loads(l) for l in (root/n).read_text(encoding='utf8').splitlines() if l.strip()]
    plan=json.loads((root/'training_plan.json').read_text(encoding='utf8'));train=load('data/train.messages.jsonl')
    original=load('checks/original_train687.jsonl');approved=load('checks/alignment_approvals.jsonl');errata=load('checks/count_definition_errata.jsonl')
    old={r['sample_id']:r for r in original};aa={r['sample_id']:r for r in approved};ee={r['sample_id']:r for r in errata}
    require(plan['purpose']==PURPOSE and plan['learning_rates']=={'alignment':1e-5} and plan['optimizer_steps_per_candidate']==850
        and plan['epochs_per_candidate']==1 and plan['batch_size']==plan['gradient_accumulation_steps']==1
        and not plan['resume_optimizer'] and plan['intermediate_step'] is None,'Training design changed')
    require(len(train)==len(old)==len(aa)==len({r['sample_id'] for r in train})==687 and len(errata)==len(ee)==4,'Training count drift')
    require(Counter(r['training_bucket'] for r in train)==MIX and Counter(r['family'] for r in train)=={'explanation':620,'selection':67},'Replay mix drift')
    require(plan['train_visit_order']==training_order(train)==training_order(original) and len(plan['train_visit_order'])==850,'Training order drift')
    excluded=set(plan['excluded_parent_source_record_ids']);hashes=[]
    for r in train:
        sid=r['sample_id'];source=old[sid];require(aa[sid]['approved_row_sha256']==canonical_hash(r) and not aa[sid]['expert_certified'],'Approval drift')
        require(r['training_approved'] and r['assigned_split']=='train' and not set(r.get('parent_source_record_ids',[r['parent_source_record_id']]))&excluded,'Held-out parent in gradients')
        lineage=r['interface_alignment_lineage'];require(lineage['original_row_sha256']==canonical_hash(source)
            and lineage['original_request_sha256']==source['request_sha256'] and lineage['training_only'] and lineage['new_teacher_calls']==0,'Source lineage drift')
        req={'messages':r['messages'][:-1],'tools':None};oldreq={'messages':copy.deepcopy(source['messages'][:-1]),'tools':None}
        require([v['role'] for v in r['messages']]==['system','user','assistant'] and canonical_hash(req)==r['request_sha256'],'Training prompt drift')
        if sid in ee:
            err=ee[sid];p=json.loads(oldreq['messages'][1]['content'])
            require(p['question']==err['old_question'] and err['editor_reviewed'] and not err['expert_certified'] and not err['new_teacher_call'],'Unreviewed erratum')
            p['question']=err['new_question'];oldreq['messages'][1]['content']=json.dumps(p,ensure_ascii=False,allow_nan=False)
            require(r['messages'][-1]['content']==err['new_target'] and source['messages'][-1]['content']==err['old_target'],'Erratum drift')
        else:require(r['messages'][-1]==source['messages'][-1],'Undeclared reference edit')
        if r['family']=='explanation':
            require(req==from_task_request(oldreq),'Handwritten per-sample interface')
            e=validate_request(req)['tool_evidence']
            validate_explanation(r['messages'][-1]['content'],[SimpleNamespace(**f) for f in e['facts']],renderer=render_answer)
            require(check_claims(r['messages'][-1]['content'],req)['passed_known_checks'],'Known reference contradiction')
        else:
            require(req==oldreq,'Selector interface changed');selection_value(r['messages'][-1]['content'],req)
        hashes.append(r['request_sha256'])
    require(len(set(hashes))==687,'Duplicate training prompt')
    evaluation=load('data/eval_inputs.jsonl');jj=load('checks/judge_only.jsonl');judges={r['case_id']:r for r in jj}
    require(len(evaluation)==len(jj)==len(judges)==len({r['case_id'] for r in evaluation})==144,'Inference/judge count drift')
    require(Counter(r['evaluation_group'] for r in evaluation)=={'control4':4,'planned64':64,'planned40':40,'selection36':36},'Development scope drift')
    by={r['case_id']:r for r in evaluation}
    for r in evaluation:
        require(set(r)=={'case_id','family','evaluation_group','request','request_sha256','prompt_reference'} and [v['role'] for v in r['request']['messages']]==['system','user'],'Judge/target in inference')
        require(r['request']['tools'] is None and canonical_hash(r['request'])==r['request_sha256'] and r['request_sha256'] not in hashes,'Inference/train overlap')
        if r['family']=='explanation' and r['evaluation_group']!='control4':
            require(validate_request(r['request'])['tool_evidence']['facts']==judges[r['case_id']]['facts'],'Inference facts drift')
    refs=load('checks/fixed850_references.jsonl');controls=load('checks/c506_controls.jsonl')
    require(len(refs)==len({r['case_id'] for r in refs})==140 and len(controls)==4,'Wrong historical count')
    for ref in refs:
        require(ref['checkpoint_sha256']==REFERENCE_SHA and ref['request_sha256']==by[ref['case_id']]['request_sha256']
            and token_digest(ref['completion']['completion_token_ids'])==ref['completion_token_ids_sha256'],'850 reference drift')
    require(set(plan['control_case_ids'])=={r['case_id'] for r in controls},'Control IDs drift')
    for ref in controls:
        require(ref['checkpoint_sha256']==INITIAL_SHA and ref['request_sha256']==by[ref['case_id']]['request_sha256'],'c506 control drift')
    return root,m,plan,train,evaluation,judges

def merge_references(records,rows,judges,refs,controls):
    actual={r['case_id']:r for r in records};expected={r['case_id']:r for r in controls}
    require(len(records)==len(actual)==len(expected)==4 and set(actual)==set(expected),'Startup controls incomplete')
    for cid,r in actual.items():require(r['arm']=='c506_reference' and r['completion']['completion_token_ids']==expected[cid]['completion']['completion_token_ids'],'c506 startup tokens changed')
    records.clear();by={r['case_id']:r for r in rows}
    for ref in refs:
        row=by[ref['case_id']]
        records.append({'case_id':ref['case_id'],'family':row['family'],'evaluation_group':row['evaluation_group'],
            'request_sha256':row['request_sha256'],'arm':'fixed850_reference','completion':copy.deepcopy(ref['completion']),
            'score':score(ref['completion'],row,judges[row['case_id']]),'original_score':ref['original_score'],
            'response_origin':'historical_fixed850_not_new_inference','reference_provenance':ref['provenance'],
            'generation_seconds':None,'teacher_calls':0,'retries':0})

def summarize(records,rows):
    rows=[r for r in rows if r['evaluation_group']!='control4'];expected={(a,r['case_id']) for a in ARMS for r in rows}
    controls=[r for r in records if r['arm']=='c506_reference'];rr=[r for r in records if r['arm'] in ARMS]
    got={(r['arm'],r['case_id']) for r in rr};require(len(got)==len(rr) and got<=expected and len(rr)+len(controls)==len(records),'Unexpected/duplicate results')
    groups={}
    for group in ('planned64','planned40','selection36'):
        groups[group]={}
        for arm in ARMS:
            items=[r for r in rr if r['arm']==arm and r['evaluation_group']==group];selection=group=='selection36'
            groups[group][arm]={'answers':len(items),'protocol_passes':sum(r['score']['protocol_passed'] for r in items),
                'unchanged_original_diagnostic_passes':sum(r['score'].get('selection_gate_passed' if selection else 'finite_checks_passed',False) for r in items),
                'aligned_finite_check_passes':sum(r['score'].get('selection_gate_passed' if selection else 'aligned_safe_protocol_passed',False) for r in items),
                'model_only_fully_correct_complete':None,'actual_page_fallbacks':None,'domain_accuracy':None}
    return {'complete':got==expected,'answers':len(rr),'expected_answers':280,'groups':groups,
        'startup_controls_pending_merge':len(controls),'teacher_calls':0,'final_holdout_cases':0,
        'independent_test':False,'deployment_approved':False,'automatic_checkpoint_selection':False,
        'factual_and_task_completeness_review':'pending_manual_review','actual_page_tested':False,
        'actual_app_fallbacks':None,'domain_accuracy':None,'reference_reuse_not_new_generation':True,
        'comparison':'Same144-prompt inventory includes4 c506 controls and140 development inputs. Reuse140 fixed850 answers; score both arms with separately versioned diagnostics. No semantic or release pass inferred from finite gates.'}
