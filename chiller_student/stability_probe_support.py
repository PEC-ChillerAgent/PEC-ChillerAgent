"""Read-only inference state and greedy score witnesses."""
import hashlib
import json
from chiller_student.native_sft_data import require,token_digest

def canonical_hash(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


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
