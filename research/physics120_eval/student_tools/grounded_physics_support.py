"""Frozen balanced corrective SFT allocation and legacy-visible evaluation."""
import json
import random
from pathlib import Path

from student_tools.native_sft_data import require,token_digest
from student_tools.paired_support import sha,save,decode_completion
from student_tools.joint_physics_support import TraceCollator,selection_value,score_selection
from student_tools.explanation_baseline_support import canonical_hash,score_completion as frozen_score
from student_tools.explanation_protocol import validate_explanation
from student_tools.explanation_number_gate_v2 import render_answer as explanation_renderer_impl,VERSION as GATE_VERSION
from student_tools.joint_physics_support import explanation_renderer as legacy_renderer

PURPOSE='grounded_corrective_physics_sft_v1'


def training_order(rows,seed=42):
    require(len(rows)==len({r['sample_id'] for r in rows}),'Duplicate unique row')
    visits=[r['sample_id'] for r in sorted(rows,key=lambda r:r['sample_id']) for _ in range(4 if r['family']=='selection' else 1)]
    random.Random(seed).shuffle(visits)
    return visits


def explanation_renderer():return explanation_renderer_impl


def score_completion(completion,judge,renderer):
    value=frozen_score(completion,judge,renderer)
    legacy=frozen_score(completion,judge,legacy_renderer())
    value.update(numeric_gate_version=GATE_VERSION,legacy_protocol_passed=legacy['protocol_passed'],
                 legacy_protocol_and_coverage_passed=legacy['protocol_and_coverage_passed'],legacy_protocol_error=legacy.get('protocol_error'))
    return value


def verify_package(path):
    from types import SimpleNamespace
    path=Path(path).resolve();root=path.parent;m=json.loads(path.read_text(encoding='utf-8'))
    require(m['purpose']==PURPOSE and m['environment_spec_hash']=='5befcb78','Wrong package')
    require(len(m['files'])==len({e['path'] for e in m['files']}),'Duplicate package path')
    for e in m['files']:
        file=(root/e['path']).resolve();require(file.is_relative_to(root) and sha(file)==e['sha256'],'Package drift: '+e['path'])
    load=lambda n:[json.loads(l) for l in (root/n).read_text(encoding='utf-8').splitlines() if l.strip()]
    train,evaluation,jj=load('data/train.messages.jsonl'),load('data/eval_inputs.jsonl'),load('data/judge_only.jsonl')
    plan=json.loads((root/'training_plan.json').read_text(encoding='utf-8'));judges={r['case_id']:r for r in jj}
    require(plan['purpose']==PURPOSE and plan['epochs']==2 and plan['learning_rate']==5e-6
            and plan['initialization']=='verified_balanced_epoch1_adapter' and not plan['resume_optimizer'],'Plan changed')
    require(len(train)==plan['train_rows'] and plan['optimizer_steps']==2*len(training_order(train))
            and plan['sampling_visits_per_epoch']==len(training_order(train)),'Wrong training/visit count')
    require(len(train)==len({r['sample_id'] for r in train}) and len(evaluation)==len({r['case_id'] for r in evaluation})==len(judges)==plan['evaluation_cases'],'Repeated IDs/count drift')
    require(not set(plan['excluded_parent_source_record_ids'])&{p for r in train for p in r.get('parent_source_record_ids',[r['parent_source_record_id']])},'Held parent entered gradients')
    require(not set(plan['new_train_source_sha256'])&set(plan['fresh_dev_source_sha256']),'New source file crosses split')
    hashes=[]
    for r in train:
        require(r['training_approved'] and r['assigned_split']=='train','Unapproved gradient row')
        require([v['role'] for v in r['messages']]==['system','user','assistant'],'Unexpected training history')
        request={'messages':r['messages'][:-1],'tools':None};h=canonical_hash(request);hashes.append(h)
        require(h==r['request_sha256'],'Training prompt changed')
        if r['family']=='selection':selection_value(r['messages'][-1]['content'],request)
        else:
            require(r['family']=='explanation','Unknown task')
            facts=json.loads(request['messages'][1]['content'])['tool_evidence']['facts']
            validate_explanation(r['messages'][-1]['content'],[SimpleNamespace(**f) for f in facts],renderer=explanation_renderer())
    require(len(hashes)==len(set(hashes)),'Duplicate gradient prompt')
    for r in evaluation:
        require(set(r)=={'case_id','family','evaluation_group','request','request_sha256','prompt_reference'},'Unexpected eval fields')
        require([x['role'] for x in r['request']['messages']]==['system','user'] and r['request']['tools'] is None,'Eval label in model input')
        require(canonical_hash(r['request'])==r['request_sha256'] and r['request_sha256'] not in hashes,'Eval input drift/leakage')
        if r['family']=='explanation':require(json.loads(r['request']['messages'][1]['content'])['tool_evidence']['facts']==judges[r['case_id']]['facts'],'Eval facts changed')
    require(plan['train_visit_order']==training_order(train)*2 and plan['planned_answers']==len(evaluation)*3,'Visit/eval plan changed')
    return root,m,plan,train,evaluation,judges


def summarize(records,rows):
    arms=['balanced_before','grounded_epoch1','grounded_epoch2'];expected={(a,r['case_id']) for a in arms for r in rows}
    got={(r['arm'],r['case_id']) for r in records};require(len(got)==len(records) and got<=expected,'Output IDs differ')
    groups={}
    for group in sorted({r['evaluation_group'] for r in rows}):
        groups[group]={}
        for arm in arms:
            rr=[r for r in records if r['evaluation_group']==group and r['arm']==arm]
            item={'answers':len(rr),'protocol_passes':sum(r['score']['protocol_passed'] for r in rr),'truncated':sum(r['completion']['finish_reason']=='length' for r in rr)}
            if group.startswith('selection'):item['selection_gate_passes']=sum(r['score']['selection_gate_passed'] for r in rr)
            else:item.update(protocol_and_coverage_passes=sum(r['score']['protocol_and_coverage_passed'] for r in rr),
                             legacy_protocol_passes=sum(r['score']['legacy_protocol_passed'] for r in rr),
                             legacy_protocol_and_coverage_passes=sum(r['score']['legacy_protocol_and_coverage_passed'] for r in rr),
                             numeric_required_cases=sum(r['score']['required_fact_count']>0 for r in rr),
                             numeric_required_coverage_passes=sum(r['score']['required_fact_count']>0 and r['score']['required_fact_coverage_passed'] for r in rr))
            groups[group][arm]=item
    return {'complete':got==expected,'answers':len(records),'expected_answers':len(expected),'groups':groups,
            'training_run':any(r['arm']!='balanced_before' for r in records),'independent_test':False,'domain_accuracy':None,
            'semantic_review':'pending','deployment_approved':False,'teacher_calls':0,'retries':0,
            'numeric_gate_version':GATE_VERSION,'scope':'Old seen dev plus new source-file-disjoint development records; same RP1043 family, not independent business testing. Legacy scores preserved separately.'}
