"""Short-token reproducibility diagnostics, not answer-quality evaluation."""
import hashlib
import json
from pathlib import Path

from student_tools.native_sft_data import require,token_digest
from student_tools.paired_support import read,save,sha,decode_completion

def canonical_hash(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

IDS=('batch04_001','batch05_006')
PROFILES=('recorded_sdpa','strict_math')
TOKEN_LIMIT=64


def jobs(rows):
    require([r['case_id'] for r in rows]==list(IDS),'Wrong diagnostic cases')
    return [{'job_id':f'{sid}__{arm}_{rep}','case_id':sid,'arm':arm,'replicate':rep}
            for sid in IDS for arm,rep in [('round2',1),('round2',2),('base',1),('base',2),('round2',3),('round2',4)]]


def verify_bundle(path):
    path=Path(path).resolve();root=path.parent;m=read(path)
    require(m['purpose']=='short_reproducibility_diagnostic_v1','Wrong package')
    require(m['effective_template_tools'] is None and m['enable_thinking'] is False,'Native template changed')
    require(len(m['files'])==len({e['path'] for e in m['files']}),'Duplicate manifest paths')
    for entry in m['files']:
        p=(root/entry['path']).resolve()
        require(p.is_relative_to(root) and sha(p)==entry['sha256'],'Package drift: '+entry['path'])
    rows=[json.loads(s) for s in (root/'data/model_inputs.jsonl').read_text(encoding='utf-8').splitlines()]
    plan=read(root/'experiment_plan.json')
    require(plan['profiles']==list(PROFILES) and plan['jobs_per_profile']==jobs(rows),'Plan drift')
    require(plan['max_new_tokens']==TOKEN_LIMIT,'Short diagnostic budget changed')
    for row in rows:
        require(set(row)=={'case_id','request','prompt_reference'},'Unexpected input fields')
        require(set(row['request'])=={'messages','tools'},'Unexpected request fields')
        require(row['request']['messages'][-1]['role']=='tool','Input must end at tool evidence')
        require(all(m.get('tool_calls') and not m.get('content') for m in row['request']['messages'] if m['role']=='assistant'),'Assistant answer leaked into input')
        require(canonical_hash(row['request'])==m['request_sha256'][row['case_id']],'Prompt changed')
        require(row['prompt_reference']==m['prompt_reference'][row['case_id']],'Prompt reference changed')
    return root,m,rows


def encode_prompt(tokenizer,row):
    ids=tokenizer.apply_chat_template(row['request']['messages'],tools=None,enable_thinking=False,
                                      tokenize=True,add_generation_prompt=True)
    require(len(ids)==row['prompt_reference']['prompt_tokens'] and token_digest(ids)==row['prompt_reference']['token_ids_sha256'],'Prompt fingerprint mismatch')
    require(len(ids)+TOKEN_LIMIT<=8192,'Prompt too long')
    return ids


def tensor_sha(tensor):
    # CPU contiguous raw bytes; bfloat16 is viewed as uint8 before NumPy.
    import torch
    return hashlib.sha256(tensor.detach().contiguous().cpu().reshape(-1).view(torch.uint8).numpy().tobytes()).hexdigest()


def rng_snapshot():
    import random
    import pickle
    import numpy as np
    import torch
    return {'cpu':tensor_sha(torch.get_rng_state()),
            'cuda':tensor_sha(torch.cuda.get_rng_state(0)) if torch.cuda.is_available() else None,
            'python':hashlib.sha256(repr(random.getstate()).encode()).hexdigest(),
            'numpy':hashlib.sha256(pickle.dumps(np.random.get_state(),protocol=4)).hexdigest()}


def module_snapshot(model):
    """A forward-state witness, not a bytewise hash of all base parameters."""
    training=[n for n,mod in model.named_modules() if mod.training]
    require(not training,'A submodule is still in training mode: '+str(training[:5]))
    require(all(not p.requires_grad for p in model.parameters()),'Trainable parameters in probe')
    state=[(n,str(p.dtype),tuple(p.shape),p._version,p.data_ptr()) for n,p in model.named_parameters()]
    dropouts=[{'name':n,'p':float(mod.p),'training':mod.training}
              for n,mod in model.named_modules() if mod.__class__.__name__=='Dropout']
    buffers={n:{'shape':list(b.shape),'dtype':str(b.dtype),'sha256':tensor_sha(b)}
             for n,b in model.named_buffers()}
    return {'training_module_count':len(training),'parameter_version_pointer_sha256':canonical_hash(state),
            'dropouts':dropouts,'buffers':buffers,
            'limits':'Versions and pointers are a mutation diagnostic, not a full bytewise base-weight identity check.'}


class ScoreRecorder:
    """Read-only generation score observer; never changes scores or token choice."""
    def __init__(self,reference,compare_steps=8):
        self.reference=reference;self.compare_steps=compare_steps;self.steps=[]
    def __call__(self,input_ids,scores):
        import torch
        require(scores.ndim==2 and scores.shape[0]==1,'Batch-one scores expected')
        values=scores[0].detach().float().cpu()
        require(torch.isfinite(values).all().item(),'Nonfinite generation scores')
        step=len(self.steps);top=torch.topk(values,min(10,values.numel()))
        prefix=token_digest(input_ids[0].tolist())
        data={'step':step,'scores_sha256':tensor_sha(values),'argmax_token_id':int(values.argmax()),
              'input_prefix_sha256':prefix,
              'top10_ids':top.indices.tolist(),'top10_scores':top.values.tolist(),
              'top1_top2_margin':float(top.values[0]-top.values[1])}
        if step<self.compare_steps:
            if step not in self.reference:self.reference[step]=(prefix,values.clone())
            ref_prefix,ref=self.reference[step]
            same=prefix==ref_prefix
            data.update(same_prefix_as_first=same,
                        equal_to_first_vector=torch.equal(ref,values) if same else None,
                        maximum_absolute_difference_from_first=float((ref-values).abs().max()) if same else None,
                        reference_argmax_token_id=int(ref.argmax()) if same else None)
        self.steps.append(data)
        return scores


def summarize(records):
    expected=jobs([{'case_id':sid} for sid in IDS])
    require(len(records)==len({r['job_id'] for r in records}),'Duplicate trace')
    allowed={r['job_id']:r for r in expected}
    for r in records:require(r['job_id'] in allowed and all(r[k]==v for k,v in allowed[r['job_id']].items()),'Unexpected trace identity')
    groups={}
    for sid in IDS:
        for arm in ('round2','base'):
            rr=[r for r in records if r['case_id']==sid and r['arm']==arm]
            target=4 if arm=='round2' else 2
            groups[sid+'__'+arm]={'count':len(rr),'expected':target,
                'all_short_sequences_identical':len(rr)==target and len({r['completion']['completion_token_ids_sha256'] for r in rr})==1,
                'first_step_score_hashes':[r['score_trace'][0]['scores_sha256'] for r in rr],
                'all_first_step_scores_identical':len(rr)==target and len({r['score_trace'][0]['scores_sha256'] for r in rr})==1,
                'rng_changed_jobs':[r['job_id'] for r in rr if r['rng_before']!=r['rng_after']],
                'parameter_version_pointer_changed_jobs':[r['job_id'] for r in rr if r['state_before']['parameter_version_pointer_sha256']!=r['state_after']['parameter_version_pointer_sha256']],
                'buffer_changed_jobs':[r['job_id'] for r in rr if r['state_before']['buffers']!=r['state_after']['buffers']]}
    return {'complete':len(records)==12,'short_traces':len(records),'groups':groups,
            'training_run':False,'domain_accuracy':None,'answer_quality_tested':False,
            'length_finish_is_planned_probe_budget':True,
            'limitation':'64-token prefixes with read-only score observer; not full answer evaluation; profile changes are bundled controls, not single-factor attribution.'}
