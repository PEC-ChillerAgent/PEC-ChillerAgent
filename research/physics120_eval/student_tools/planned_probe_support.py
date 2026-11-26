import copy,json
from types import SimpleNamespace
from pathlib import Path
from collections import Counter
from student_tools.compound_alignment_support import score as old_score
from student_tools.planned_explanation import from_task_request,validate_request
from student_tools.typed_physics_claims import check_claims
from student_tools.native_sft_data import require,token_digest
from student_tools.paired_support import sha,save
from student_tools.joint_physics_support import canonical_hash
from student_tools.explanation_protocol import validate_explanation
from student_tools.explanation_number_gate_v6 import render_answer

PURPOSE='planned_question_and_typed_evidence_fixed850_probe_v1'
CHECKPOINT='9d0e74f2c40409ccf75f5c26b2388f242863f49e9626df6314bad2d481c0e798'

def verify_package(path):
    path=Path(path).resolve();root=path.parent;m=json.loads(path.read_text(encoding='utf8'))
    require(m['purpose']==PURPOSE and m['adapter_files_sha256']['adapter_model.safetensors']==CHECKPOINT
        and m['environment_spec_hash']=='5befcb78' and not m['final_holdout_included'],'Wrong planned probe/start')
    require(len(m['files'])==len({x['path'] for x in m['files']}),'Duplicate source entry')
    for x in m['files']:
        f=(root/x['path']).resolve();require(f.is_relative_to(root) and sha(f)==x['sha256'],'Package changed: '+x['path'])
    load=lambda n:[json.loads(l) for l in (root/n).read_text(encoding='utf8').splitlines() if l.strip()]
    rows=load('data/model_inputs.jsonl');jj=load('checks/judge_only.jsonl');judges={r['case_id']:r for r in jj}
    refs=load('checks/original850_references.jsonl');by={r['case_id']+'__planned':r for r in refs};controls=json.loads((root/'checks/control_answers.json').read_text(encoding='utf8'))
    require(len(rows)==len(jj)==len(judges)==len({r['case_id'] for r in rows})==108 and len(refs)==len(by)==104 and len(controls)==4,'Wrong answer/reference count')
    require(Counter(r['evaluation_group'] for r in rows)=={'control4':4,'planned64':64,'planned40':40},'Group changed')
    for r in rows:
        require(set(r)=={'case_id','family','evaluation_group','request','request_sha256','prompt_reference'},'Judge/answer in generation input')
        require(r['family']=='explanation' and [x['role'] for x in r['request']['messages']]==['system','user'] and r['request']['tools'] is None,'Wrong history/task')
        require(canonical_hash(r['request'])==r['request_sha256'],'Prompt hash drift')
        if r['evaluation_group']=='control4':
            c=controls[r['case_id']];require(c['request_sha256']==r['request_sha256'] and token_digest(c['tokens'])==c['token_ids_sha256'],'850 control changed')
            payload=json.loads(r['request']['messages'][1]['content'])
        else:
            ref=by[r['case_id']];require(r['request']==from_task_request(ref['request']),'Planner bypassed/handwritten per-case input')
            require(ref['checkpoint_sha256']==CHECKPOINT and ref['request_sha256']==canonical_hash(ref['request']),'Historical identity changed')
            require(ref['completion_token_ids_sha256']==token_digest(ref['completion']['completion_token_ids']),'Historical tokens changed')
            payload=validate_request(r['request'])
        require(payload['tool_evidence']['facts']==judges[r['case_id']]['facts'],'Judge facts differ from inference facts')
    return root,m,rows,judges,controls,refs

def score(completion,row,judge):
    result=old_score(completion,{**row,'evaluation_group':'task08_dev64'},judge)
    try:typed=check_claims(completion['content'],row['request'])
    except (ValueError,KeyError,TypeError):typed={'passed_known_checks':False,'issues':['UNPARSEABLE_TYPED_OUTPUT'],'model_text_repaired':False}
    result['typed_claim_checks']=typed
    try:
        validate_explanation(completion['content'],[SimpleNamespace(**f) for f in judge['facts']],renderer=render_answer)
        upgraded=completion['finish_reason']=='stop'
    except (ValueError,TypeError,KeyError):upgraded=False
    from student_tools.explanation_quality import check_repetition
    try:repeat=check_repetition(json.loads(completion['content'])['answer'])['passed_repetition_check']
    except (ValueError,TypeError,KeyError):repeat=False
    result['protocol_v6_passed']=upgraded
    result['safe_protocol_passed']=upgraded and typed['passed_known_checks'] and repeat
    result['actual_task_success']=None
    return result

def summarize(records,rows):
    ids=[r['case_id'] for r in records];expected={r['case_id'] for r in rows}
    require(len(ids)==len(set(ids)) and set(ids)<=expected,'Duplicate/unknown answer')
    groups={}
    for g in ('planned64','planned40'):
        rr=[r for r in records if r['evaluation_group']==g]
        groups[g]={'answers':len(rr),'protocol_passes':sum(r['score']['protocol_passed'] for r in rr),
            'frozen_finite_check_passes':sum(r['score']['finite_checks_passed'] for r in rr),
            'safe_protocol_passes':sum(r['score']['safe_protocol_passed'] for r in rr),
            'would_reject_by_application_checks':sum(not r['score']['safe_protocol_passed'] for r in rr),
            'actual_app_fallbacks':None,'model_only_fully_correct_complete':None,'semantic_review':'pending'}
    return {'complete':set(ids)==expected,'fresh_answers':len(records),'expected_fresh_answers':108,'groups':groups,
        'truncated':sum(r['completion']['finish_reason']=='length' for r in records),'training_run':False,'teacher_calls':0,
        'actual_page_tested':False,'actual_app_fallbacks':None,'domain_accuracy':None,'final_holdout_included':False,
        'deployment_approved':False,'automatic_checkpoint_selection':False,
        'intervention':'Fixed850; original question retained; Python-derived task plan/static source-code rule card/typed index plus saved missing-input count facts. Combined engineering change, not SFT or a one-factor causal test.'}

def make_pairs(records,rows,judges,refs):
    by={r['case_id']:r for r in records};lookup={r['case_id']:r for r in rows};pairs=[]
    for ref in refs:
        cid=ref['case_id']+'__planned';new=by[cid]
        oldrow={**lookup[cid],'request':ref['request']};oldjudge={**judges[cid],'facts':json.loads(ref['request']['messages'][1]['content'])['tool_evidence']['facts']}
        pairs.append({'case_id':ref['case_id'],'old_content':ref['completion']['content'],'new_content':new['completion']['content'],
            'old_original_score':ref['original_score'],'old_same_new_diagnostic':score(ref['completion'],oldrow,oldjudge),'new_score':new['score'],
            'old_response_origin':'audited850_reuse_not_new_inference','old_new_latency_seconds':None,
            'reference_provenance':ref['provenance'],'new_latency_seconds':new['generation_seconds']})
    return pairs
