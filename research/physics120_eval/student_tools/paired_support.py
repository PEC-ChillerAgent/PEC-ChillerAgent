"""Input isolation, completion preservation and independent format diagnostics."""
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

from student_tools.native_sft_data import require,token_digest


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path,obj):
    with Path(path).open('x',encoding='utf-8') as f:json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False)


def verify_bundle(path):
    path=Path(path).resolve();root=path.parent;m=read(path)
    require(m['purpose']=='paired_base_pilot_generation_48','Wrong package')
    for e in m['files']:
        p=(root/e['path']).resolve()
        require(p.is_relative_to(root),'Package path escapes root')
        require(sha(p)==e['sha256'],'Package changed: '+e['path'])
    rows=[json.loads(s) for s in (root/'data/model_inputs.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
    judges=[json.loads(s) for s in (root/'data/judge_only.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
    require(len(rows)==len(judges)==48,'Expected 48 cases')
    lookup={r['case_id']:r for r in judges}
    ids=[r['case_id'] for r in rows]
    require(len(set(ids))==len(lookup)==48 and set(ids)==set(lookup),'Case IDs differ')
    for r in rows:
        require(set(r)=={'case_id','family','evaluation_group','request','prompt_reference'},'Unexpected model-input fields')
        require(re.fullmatch(r'(?:batch04_\d{3}|knowledge_K\d{3})',r['case_id']),'Invalid case ID')
        require(set(r['request'])=={'messages','tools'},'Targets or judge fields in request')
        messages=r['request']['messages']
        if r['family']=='physics':
            require(messages[-1]['role']=='tool','Physics input must end at tool evidence')
            require(r['evaluation_group']=='physics_train_in_sample','Unexpected physics group')
            for msg in messages:
                if msg['role']=='assistant':require(bool(msg.get('tool_calls')),'Assistant target in input')
        else:
            require(r['family']=='knowledge' and [x['role'] for x in messages]==['system','user'],'Knowledge input must not include target answers')
            require(r['evaluation_group'] in {'knowledge_train_in_sample','knowledge_dev_validation'},'Unexpected knowledge group')
        canonical=json.dumps(r['request'],ensure_ascii=False,separators=(',',':'),sort_keys=True)
        require(hashlib.sha256(canonical.encode()).hexdigest()==m['request_sha256'][r['case_id']],'Frozen baseline input changed')
    require(sum(r['evaluation_group']=='physics_train_in_sample' for r in rows)==24,'Expected 24 physics cases')
    require(sum(r['evaluation_group']=='knowledge_train_in_sample' for r in rows)==20,'Expected 20 seen knowledge cases')
    require({r['case_id'] for r in rows if r['evaluation_group']=='knowledge_dev_validation'}=={f'knowledge_K{i:03d}' for i in range(13,17)},'Wrong developer validation cases')
    return root,m,rows,lookup


def encode_prompt(tokenizer,row):
    # Only request messages reach the tokenizer; no gold answer or rubric.
    ids=tokenizer.apply_chat_template(row['request']['messages'],tools=None,enable_thinking=False,
                                      tokenize=True,add_generation_prompt=True)
    ref=row['prompt_reference']
    require(len(ids)==ref['prompt_tokens'] and token_digest(ids)==ref['token_ids_sha256'],'Prompt differs from verified baseline: '+row['case_id'])
    require(len(ids)+2048<=8192,'Prompt plus output budget exceeds baseline context limit')
    return ids


def decode_completion(tokenizer,ids,eos_ids,max_new_tokens=2048):
    require(len(ids)<=max_new_tokens,'Unexpected output token count')
    eos=set(eos_ids)
    positions=[i for i,t in enumerate(ids) if t in eos]
    require(not positions or positions==[len(ids)-1],'Unexpected tokens after EOS')
    stopped=bool(positions)
    body=ids[:-1] if stopped else ids
    return {'content':tokenizer.decode(body,skip_special_tokens=False),
            'raw_completion_with_special_tokens':tokenizer.decode(ids,skip_special_tokens=False),
            'finish_reason':'stop' if stopped else ('length' if len(ids)==max_new_tokens else 'unknown'),
            'completion_tokens':len(ids),'completion_token_ids':ids,'completion_token_ids_sha256':token_digest(ids)}


def score_completion(row,completion,judge):
    from student_tools.pair_physics_score import score_response as physics_score
    from student_tools.pair_knowledge_score import score_response as knowledge_score
    from student_tools.pair_project_reporting import TOKEN
    text=completion['content']
    message={'role':'assistant','content':text}
    # Preserve the raw completion, but expose tool markup to frozen scorers.
    tool_markup='<tool_call>' in text or '</tool_call>' in text
    if tool_markup:message['tool_calls']=[{'type':'unexpected_tool_markup'}]
    response={'choices':[{'finish_reason':completion['finish_reason'],'message':message}]}
    if row['family']=='knowledge':
        result=knowledge_score(response,judge['judge'])
        return {'frozen_score':result,'automatic_format_passed':result['knowledge_format_passed'],
                'unexpected_tool_markup':tool_markup,'domain_accuracy':None}
    gold=judge['judge']
    legacy=physics_score(response,gold,row['request'])
    # Frozen legacy scorer exits before coverage on format failures. Calculate
    # these diagnostics separately for BOTH arms; do not rewrite old results.
    cited=set(TOKEN.findall(text));facts={f['fact_id']:f for f in gold['facts']}
    missing_values=[metric for metric in gold['required_value_metrics'] if not any(
        fid in cited and f['pointer']==f'/result/metrics/{metric}/value' for fid,f in facts.items())]
    missing_counts=[metric for metric in gold['required_missing_count_metrics'] if not any(
        fid in cited and f['pointer']==f'/result/metrics/{metric}/valid_count' and f['value']==0 for fid,f in facts.items())]
    counts_applicable=bool(gold['required_missing_count_metrics'])
    coverage={'all_required_values_cited':not missing_values,'missing_value_metrics':missing_values,
        'required_value_facts_total':len(gold['required_value_metrics']),
        'required_value_facts_cited':len(gold['required_value_metrics'])-len(missing_values),
        'missing_count_check_applicable':counts_applicable,
        'all_required_missing_counts_cited':not missing_counts if counts_applicable else None,
        'missing_count_metrics':missing_counts,'required_missing_count_facts_total':len(gold['required_missing_count_metrics']),
        'required_missing_count_facts_cited':len(gold['required_missing_count_metrics'])-len(missing_counts),
        'unknown_fact_ids':sorted(cited-set(facts))}
    return {'frozen_score':legacy,'independent_fact_coverage':coverage,
            'automatic_format_passed':legacy['protocol_passed'],'unexpected_tool_markup':tool_markup,
            'protocol_and_coverage_passed':legacy['protocol_passed'] and not missing_values and not missing_counts,
            'domain_accuracy':None}


def summarize_records(records,expected_cases=48):
    require(all(r['arm'] in {'base','sft'} for r in records),'Unknown evaluation arm')
    require(all(r['evaluation_group'] in {'physics_train_in_sample','knowledge_train_in_sample','knowledge_dev_validation'} for r in records),'Unknown evaluation group')
    require(all(math.isfinite(r['generation_seconds']) and r['generation_seconds']>=0 for r in records),'Invalid generation latency')
    identities=[(r['case_id'],r['arm']) for r in records]
    require(len(identities)==len(set(identities)),'Duplicate generation record')
    groups={}
    for group in ['physics_train_in_sample','knowledge_train_in_sample','knowledge_dev_validation']:
        arms={}
        for arm in ['base','sft']:
            rr=[r for r in records if r['evaluation_group']==group and r['arm']==arm]
            latency=sorted(r['generation_seconds'] for r in rr)
            a={'answers':len(rr),'format_passes':sum(r['score']['automatic_format_passed'] for r in rr),
               'truncated':sum(r['completion']['finish_reason']=='length' for r in rr),
               'mean_generation_seconds':statistics.mean(latency) if latency else None,
               'p95_generation_seconds':latency[math.ceil(.95*len(latency))-1] if latency else None,
               'completion_tokens':sum(r['completion']['completion_tokens'] for r in rr)}
            if group=='physics_train_in_sample':
                cc=[r['score']['independent_fact_coverage'] for r in rr]
                a.update(value_fact_coverage_cases=sum(c['all_required_values_cited'] for c in cc),
                    missing_count_applicable_cases=sum(c['missing_count_check_applicable'] for c in cc),
                    missing_count_coverage_cases=sum(c['all_required_missing_counts_cited'] is True for c in cc),
                    protocol_and_coverage_cases=sum(r['score']['protocol_and_coverage_passed'] for r in rr))
            arms[arm]=a
        b=arms['base'];s=arms['sft']
        matched=bool(b['answers']) and {r['case_id'] for r in records if r['evaluation_group']==group and r['arm']=='base'}=={r['case_id'] for r in records if r['evaluation_group']==group and r['arm']=='sft'}
        arms['format_difference']={'same_case_set':matched,'sft_minus_base_cases':s['format_passes']-b['format_passes'] if matched else None,
            'relative_pass_count_change':(s['format_passes']-b['format_passes'])/b['format_passes'] if matched and b['format_passes'] else None,
            'note':'Automatic format only; semantic review pending. Zero baseline has undefined relative change.'}
        groups[group]=arms
    case_ids={r['case_id'] for r in records}
    complete=len(case_ids)==expected_cases and all((sid,arm) in identities for sid in case_ids for arm in ['base','sft'])
    return {'complete':complete,'answers':len(records),'paired_cases':sum(all((sid,arm) in identities for arm in ['base','sft']) for sid in case_ids),
            'groups':groups,'training_run':False,'domain_accuracy':None,'independent_test':False,
            'tool_selection_tested':False,'retrieval_tested':False,'live_physics_execution_tested':False,
            'automatic_retries':0,'fallback':False,'inference_engine':'Transformers 4.51.3 BF16 SDPA batch=1',
            'legacy_vllm_baseline_directly_comparable':False,
            'comparison_scope':'Base vs SFT within this paired run; 44 seen prompts plus 4 previously inspected same-source development validation prompts.',
            'latency_scope':'Serial GPU generation wall time includes prefill; no warm-up, concurrent serving, network or production throughput test.'}
