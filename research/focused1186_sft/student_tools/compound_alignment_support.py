"""Training-only compound references; fixed high623 development comparison."""
import copy,json,random
from pathlib import Path
from collections import Counter
from types import SimpleNamespace
from student_tools.native_sft_data import require,token_digest
from student_tools.paired_support import sha,save
from student_tools.joint_physics_support import canonical_hash,TraceCollator,selection_value
from student_tools.task08_sft_support import score as old_score,INITIAL_SHA
from student_tools.task_explanation import validate_request,from_v1
from student_tools.explanation_protocol import validate_explanation
from student_tools.explanation_number_gate_v5 import render_answer
from student_tools.explanation_consistency_v3 import check_consistency

PURPOSE='compound_alignment687_weighted850_sft_v1'
REFERENCE_SHA='246e62d2f3303a3767aa68cf8ba4ac3d070e04f61da25eee64e7daff1a47c1f9'
ARMS=('high623_reference','compound_after')
MIX={'task08':512,'explanation_replay':60,'selection_replay':51,'compound09':48,'selection09':16}
WEIGHTS={'task08':1,'explanation_replay':1,'selection_replay':2,'compound09':3,'selection09':2}

def training_order(rows):
    order=[r['sample_id'] for r in sorted(rows,key=lambda r:r['sample_id']) for _ in range(WEIGHTS[r['training_bucket']])]
    random.Random(42).shuffle(order);return order

def score(completion,row,judge):
    # One unchanged finite diagnostic on BOTH canonical-language comparison arms.
    # Original legacy-v2 scores remain in historical provenance, never rewritten.
    return old_score(completion,{**row,'evaluation_group':'task08_dev64'} if row['family']=='explanation' else row,judge)

def verify_package(path):
    path=Path(path).resolve();root=path.parent;m=json.loads(path.read_text(encoding='utf8'))
    require(m['purpose']==PURPOSE and m['environment_spec_hash']=='5befcb78'
        and m['adapter_files_sha256']['adapter_model.safetensors']==INITIAL_SHA,'Wrong package/start/environment')
    require(len(m['files'])==len({e['path'] for e in m['files']}),'Duplicate manifest path')
    for e in m['files']:
        f=(root/e['path']).resolve();require(f.is_relative_to(root) and sha(f)==e['sha256'],'Package drift: '+e['path'])
    load=lambda n:[json.loads(l) for l in (root/n).read_text(encoding='utf8').splitlines() if l.strip()]
    plan=json.loads((root/'training_plan.json').read_text(encoding='utf8'));train=load('data/train.messages.jsonl')
    evaluation=load('data/eval_inputs.jsonl');jj=load('checks/judge_only.jsonl');judges={r['case_id']:r for r in jj}
    require(plan['purpose']==PURPOSE and plan['learning_rates']=={'alignment':1e-5}
        and plan['optimizer_steps_per_candidate']==850 and plan['intermediate_step']==425
        and plan['epochs_per_candidate']==1 and plan['batch_size']==plan['gradient_accumulation_steps']==1
        and not plan['resume_optimizer'],'Training design drift')
    require(len(train)==len({r['sample_id'] for r in train})==687 and Counter(r['training_bucket'] for r in train)==MIX,'Training mix/IDs drift')
    order=training_order(train);require(plan['train_visit_order']==order and len(order)==850 and len(set(order))==687,'Weighted visit drift')
    reviewed=load('checks/approved64_item_reviews.jsonl');review={r['sample_id']:r for r in reviewed}
    require(len(reviewed)==len(review)==64 and all(r['approved'] and not r['expert_certified'] for r in reviewed),'New references unapproved')
    historical=load('checks/previous623_reference.jsonl');old={r['sample_id']:r for r in historical}
    require(len(historical)==len(old)==623,'Historical training reference drift')
    refs512=load('checks/task08_approved_reviews.jsonl');approved={r['case_id']:r for r in refs512}
    require(len(refs512)==len(approved)==512 and all(r['editor_reviewed'] and r['training_approved'] for r in refs512),'Task08 labels unapproved')
    excluded=set(plan['excluded_parent_source_record_ids']);hashes=[]
    parent_sources=json.loads((root/'checks/task08_train_parent_sources.json').read_text(encoding='utf8'))
    compound_parents=set();source_files=set()
    for r in train:
        require(r['training_approved'] and r['assigned_split']=='train' and [x['role'] for x in r['messages']]==['system','user','assistant'],'Unapproved or invalid train row')
        require(not set(r.get('parent_source_record_ids',[r['parent_source_record_id']]))&excluded,'Held parent in gradients')
        req={'messages':r['messages'][:-1],'tools':None};h=canonical_hash(req);hashes.append(h)
        require(h==r['request_sha256'],'Training request changed')
        if r['training_bucket'] in ('compound09','selection09'):
            raw={k:v for k,v in r.items() if k!='baseline_template_reference'}
            require(canonical_hash(raw)==review[r['sample_id']]['approved_row_sha256'],'New row differs from editorial approval')
            if r['training_bucket']=='compound09':
                parent=r['parent_source_record_id'];require(parent in parent_sources and parent_sources[parent]==r['source_group_id'],'New compound source is not training-only')
                source=next((x for x in train if x['sample_id']=='task08_reviewed_'+r['source_task08_case_id']),None)
                require(source is not None and source['parent_source_record_id']==parent
                    and source['request_sha256']==r['source_request_sha256'],'Compound source lineage changed')
                require(json.loads(source['messages'][1]['content'])['tool_evidence']==json.loads(req['messages'][1]['content'])['tool_evidence'],'Compound Python facts/states changed')
                compound_parents.add(parent);source_files.add(parent_sources[parent])
            else:
                src=old[r['source_replay_sample_id']];p=json.loads(req['messages'][1]['content']);q=json.loads(src['messages'][1]['content'])
                require({k:v for k,v in p.items() if k!='question'}=={k:v for k,v in q.items() if k!='question'},'Selection augmentation changed input evidence')
        else:
            src=old[r['sample_id']];require(r['messages'][-1]==src['messages'][-1],'Historical final target changed')
            expected=from_v1({'messages':src['messages'][:-1],'tools':None}) if r['training_bucket']=='explanation_replay' else {'messages':src['messages'][:-1],'tools':None}
            require(req==expected,'Undeclared historical prompt change')
            if r['training_bucket']=='task08':
                a=approved[r['sample_id'].removeprefix('task08_reviewed_')]
                require(a['target_content']==r['messages'][-1]['content'] and a['raw_teacher_record_sha256']==r['raw_teacher_record_sha256'],'Task08 target lineage changed')
        if r['family']=='selection':selection_value(r['messages'][-1]['content'],req)
        else:
            e=validate_request(req)['tool_evidence']
            validate_explanation(r['messages'][-1]['content'],[SimpleNamespace(**f) for f in e['facts']],renderer=render_answer)
            require(check_consistency(r['messages'][-1]['content'],req)['passed_known_checks'],'Known reference contradiction')
    require(len(compound_parents)==8 and len(source_files)==4 and len(set(hashes))==687,'Source count or duplicate prompt')
    require(len(evaluation)==len(jj)==len(judges)==len({r['case_id'] for r in evaluation})==140,'Wrong development count')
    require(Counter(r['evaluation_group'] for r in evaluation)=={'task08_dev64':64,'canonical40':40,'selection36':36},'Development group drift')
    for r in evaluation:
        require(set(r)=={'case_id','family','evaluation_group','request','request_sha256','prompt_reference'},'Judge/target in inference input')
        require([x['role'] for x in r['request']['messages']]==['system','user'] and r['request']['tools'] is None,'History/target in inference')
        require(canonical_hash(r['request'])==r['request_sha256'] and r['request_sha256'] not in hashes,'Evaluation prompt drift/train collision')
        j=judges[r['case_id']]
        if r['family']=='explanation':
            e=validate_request(r['request'])['tool_evidence'];require(e['facts']==j['facts'],'Evaluation facts changed')
        if r['evaluation_group']=='task08_dev64':require(j['parent_source_record_id'] in plan['task_development_parent_ids'],'Wrong development parent')
    refs=load('checks/high_reference_records.jsonl');byid={r['case_id']:r for r in evaluation}
    require(len(refs)==len({r['case_id'] for r in refs})==140,'Wrong historical comparison count')
    for r in refs:
        require(r['request_sha256']==byid[r['case_id']]['request_sha256'] and r['checkpoint_sha256']==REFERENCE_SHA,'Wrong high623 reference')
        require(token_digest(r['completion']['completion_token_ids'])==r['completion_token_ids_sha256'],'High623 tokens changed')
    controls=load('checks/c506_control_records.jsonl');control={r['case_id']:r for r in controls}
    require(len(controls)==len(control)==len(plan['control_case_ids'])==4 and set(control)==set(plan['control_case_ids']),'Startup control drift')
    for cid,r in control.items():
        require(r['request_sha256']==byid[cid]['request_sha256'] and r['checkpoint_sha256']==INITIAL_SHA,'c506 controls confused with high623')
        require(token_digest(r['completion']['completion_token_ids'])==r['completion_token_ids_sha256'],'Control tokens changed')
    return root,m,plan,train,evaluation,judges

def merge_references(records,rows,judges,refs,controls):
    fresh={r['case_id']:r for r in records};checks={r['case_id']:r for r in controls}
    require(len(fresh)==len(records)==4 and set(fresh)==set(checks),'Expected four fresh c506 controls')
    for cid,r in fresh.items():
        require(r['arm']=='c506_reference' and r['completion']['completion_token_ids']==checks[cid]['completion']['completion_token_ids']
            and r['request_sha256']==checks[cid]['request_sha256'],'c506 startup control drift: '+cid)
    # Fresh controls have their own disk record. They are NOT high623 baselines.
    records.clear();expected={r['case_id']:r for r in refs}
    for row in rows:
        ref=expected[row['case_id']]
        records.append({'case_id':row['case_id'],'family':row['family'],'evaluation_group':row['evaluation_group'],
            'request_sha256':row['request_sha256'],'arm':'high623_reference','completion':copy.deepcopy(ref['completion']),
            'score':score(ref['completion'],row,judges[row['case_id']]),'response_origin':'audited_high623_reference_not_new_inference',
            'reference_provenance':ref['provenance'],'original_score':ref['original_score'],'generation_seconds':None,'teacher_calls':0,'retries':0})

def summarize(records,rows):
    expected={(a,r['case_id']) for a in ARMS for r in rows};got={(r['arm'],r['case_id']) for r in records}
    # A failure during startup may leave c506 controls in memory, never miscount them.
    controls=[r for r in records if r['arm']=='c506_reference']
    rr=[r for r in records if r['arm'] in ARMS];got={(r['arm'],r['case_id']) for r in rr}
    require(len(got)==len(rr) and got<=expected and len(controls)<=4,'Duplicate/unknown comparison answer')
    require(len(controls)+len(rr)==len(records),'Unknown arm')
    groups={}
    for group in sorted({r['evaluation_group'] for r in rows}):
        groups[group]={}
        for arm in ARMS:
            items=[r for r in rr if r['arm']==arm and r['evaluation_group']==group]
            d={'answers':len(items),'protocol_passes':sum(r['score']['protocol_passed'] for r in items),
                'truncated':sum(r['completion']['finish_reason']=='length' for r in items),'domain_accuracy':None}
            key='selection_gate_passes' if group=='selection36' else 'finite_checks_passes'
            d[key]=sum(r['score'].get('selection_gate_passed' if group=='selection36' else 'finite_checks_passed',False) for r in items)
            groups[group][arm]=d
    return {'complete':got==expected,'answers':len(rr),'expected_answers':280,'groups':groups,
        'startup_controls_pending_reference_merge':len(controls),'domain_accuracy':None,'factual_and_task_completeness_review':'pending',
        'teacher_calls':0,'final_holdout_cases':0,'independent_test':False,'deployment_approved':False,'automatic_checkpoint_selection':False,
        'reference_reuse_not_new_generation':True,'checks':'same v5/v3 frozen reference lists for both language arms; selector unchanged',
        'comparison':'prior high623 vs new weighted850 c506-start; combined data/canonicalization/replay/update-budget experiment, not one-factor causality'}
