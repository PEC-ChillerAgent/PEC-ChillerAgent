"""Frozen teacher-batch06/replay allocation and honest development reporting."""
import json
import random
from pathlib import Path
from types import SimpleNamespace

from student_tools.native_sft_data import require,token_digest
from student_tools.paired_support import sha,save,decode_completion
from student_tools.joint_physics_support import TraceCollator,selection_value,score_selection
from student_tools.explanation_baseline_support import canonical_hash
from student_tools.grounded_physics_support import score_completion,explanation_renderer
from student_tools.explanation_protocol import validate_explanation

PURPOSE='teacher_batch06_physics_sft_v1'
ARMS=['balanced_before','teacher_epoch1','teacher_epoch2']

def training_order(rows,seed=42):
    require(len(rows)==len({r['sample_id'] for r in rows}),'Duplicate unique row')
    visits=[]
    for r in sorted(rows,key=lambda r:r['sample_id']):
        require(r['training_bucket'] in ('selection_replay','explanation_replay','teacher06'),'Unknown training bucket')
        visits.extend([r['sample_id']]*(1 if r['training_bucket']=='explanation_replay' else 2))
    random.Random(seed).shuffle(visits)
    return visits

def verify_package(path):
    path=Path(path).resolve();root=path.parent;m=json.loads(path.read_text(encoding='utf8'))
    require(m['purpose']==PURPOSE and m['environment_spec_hash']=='5befcb78','Wrong package')
    require(len(m['files'])==len({e['path'] for e in m['files']}),'Duplicate package entry')
    for e in m['files']:
        f=(root/e['path']).resolve()
        require(f.is_relative_to(root) and sha(f)==e['sha256'],'Package drift: '+e['path'])
    load=lambda n:[json.loads(l) for l in (root/n).read_text(encoding='utf8').splitlines() if l.strip()]
    plan=json.loads((root/'training_plan.json').read_text(encoding='utf8'))
    train,evaluation,jj=load('data/train.messages.jsonl'),load('data/eval_inputs.jsonl'),load('data/judge_only.jsonl')
    judges={r['case_id']:r for r in jj}
    require(plan['purpose']==PURPOSE and plan['initialization']=='verified_balanced_epoch1_adapter'
            and plan['epochs']==2 and plan['learning_rate']==5e-6 and not plan['resume_optimizer'],'Training design changed')
    require(len(train)==len({r['sample_id'] for r in train})==151 and len(evaluation)==len(judges)==len(jj)==76,'Unexpected rows')
    require(plan['train_rows']==151 and plan['optimizer_steps']==484 and len(training_order(train))==242
            and plan['train_visit_order']==training_order(train)*2 and plan['planned_answers']==228,'Unexpected steps/answers')
    buckets={b:[r for r in train if r['training_bucket']==b] for b in ('selection_replay','explanation_replay','teacher06')}
    require({k:len(v) for k,v in buckets.items()}=={'selection_replay':51,'explanation_replay':60,'teacher06':40},'Training mix changed')
    require({p for r in train for p in r.get('parent_source_record_ids',[r['parent_source_record_id']])}.isdisjoint(plan['excluded_parent_source_record_ids']),'Development parent in gradients')
    teacher=load('checks/teacher_targets_reviewed.jsonl')
    require(len(teacher)==48 and sum(r['training_approved'] for r in teacher)==40,'Teacher decisions changed')
    approved={r['sample_id']:r for r in teacher if r['training_approved']}
    for r in buckets['teacher06']:
        a=approved[r['sample_id']]
        require(r['messages']==a['messages'] and r['parent_source_record_id']==a['parent_source_record_id'],'Teacher target lineage changed')
    hashes=[]
    for r in train:
        require(r['training_approved'] and r['assigned_split']=='train','Unapproved gradient row')
        require([v['role'] for v in r['messages']]==['system','user','assistant'],'Wrong training roles')
        request={'messages':r['messages'][:-1],'tools':None};h=canonical_hash(request);hashes.append(h)
        require(h==r['request_sha256'],'Training prompt drift')
        if r['family']=='selection':selection_value(r['messages'][-1]['content'],request)
        else:
            require(r['family']=='explanation','Unknown task')
            facts=json.loads(request['messages'][1]['content'])['tool_evidence']['facts']
            validate_explanation(r['messages'][-1]['content'],[SimpleNamespace(**f) for f in facts],renderer=explanation_renderer())
    require(len(hashes)==len(set(hashes)),'Duplicate training input')
    require(len({r['case_id'] for r in evaluation})==76,'Duplicate eval input')
    for r in evaluation:
        require(set(r)=={'case_id','family','evaluation_group','request','request_sha256','prompt_reference'},'Judge/target field in model input')
        require(set(r['request'])=={'messages','tools'} and r['request']['tools'] is None
                and [x['role'] for x in r['request']['messages']]==['system','user'],'Wrong eval history')
        require(canonical_hash(r['request'])==r['request_sha256'] and r['request_sha256'] not in hashes,'Eval prompt drift/leakage')
        if r['family']=='explanation':require(json.loads(r['request']['messages'][1]['content'])['tool_evidence']['facts']==judges[r['case_id']]['facts'],'Eval fact drift')
    require(set(plan['new_train_source_sha256']).isdisjoint(plan['legacy_file_disjoint_dev_source_sha256']),'Legacy file split changed')
    return root,m,plan,train,evaluation,judges

def summarize(records,rows):
    expected={(a,r['case_id']) for a in ARMS for r in rows};got={(r['arm'],r['case_id']) for r in records}
    require(len(got)==len(records) and got<=expected,'Duplicate/unexpected output')
    groups={}
    for group in sorted({r['evaluation_group'] for r in rows}):
        groups[group]={}
        for arm in ARMS:
            rr=[r for r in records if r['arm']==arm and r['evaluation_group']==group]
            item={'answers':len(rr),'protocol_passes':sum(r['score']['protocol_passed'] for r in rr),
                  'truncated':sum(r['completion']['finish_reason']=='length' for r in rr)}
            if group.startswith('selection'):item['selection_gate_passes']=sum(r['score']['selection_gate_passed'] for r in rr)
            else:item.update(protocol_and_coverage_passes=sum(r['score']['protocol_and_coverage_passed'] for r in rr),
                 required_fact_coverage_passes=sum(r['score']['required_fact_coverage_passed'] for r in rr),
                 legacy_protocol_and_coverage_passes=sum(r['score']['legacy_protocol_and_coverage_passed'] for r in rr))
            groups[group][arm]=item
    return {'complete':got==expected,'answers':len(records),'expected_answers':len(expected),'groups':groups,
            'training_run':any(r['arm']!='balanced_before' for r in records),'domain_accuracy':None,
            'semantic_review':'pending','independent_test':False,'deployment_approved':False,'teacher_calls':0,'retries':0,
            'scope':'68 previously inspected development questions plus8 newly held-parent questions. New8 share source files and RP1043 family with training; not independent business testing.',
            'numeric_gate_version':'explanation_number_gate_v2'}
