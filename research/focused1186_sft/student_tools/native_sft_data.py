"""Native Qwen3 final-answer-only preprocessing shared with the planned trainer.

Explanation-only stage uses tools=None to match the frozen vLLM 0.8.5 requests
with tool_choice=none. Existing tool-call/result history is retained verbatim.
"""
import hashlib
import json


def require(condition, message):
    if not condition:
        raise ValueError(message)


def token_digest(ids):
    return hashlib.sha256(json.dumps(ids,separators=(',',':')).encode('utf-8')).hexdigest()


def encode_sample(tokenizer, row, cutoff=8192):
    messages=row['messages']
    require(messages[-1]['role']=='assistant' and not messages[-1].get('tool_calls'),'Final answer must be text')
    answer=messages[-1]['content']
    require(isinstance(answer,str) and answer.strip(),'Empty target')
    require('<think>' not in answer and '</think>' not in answer,'Thinking target not allowed')
    options={'tools':None,'tokenize':True,'enable_thinking':False}
    prompt=tokenizer.apply_chat_template(messages[:-1],add_generation_prompt=True,**options)
    full=tokenizer.apply_chat_template(messages,add_generation_prompt=False,**options)
    require(full[:len(prompt)]==prompt,'Native prompt is not an exact prefix')
    expected=row['baseline_template_reference']
    require(len(prompt)==expected['prompt_tokens'],'Prompt token count differs from verified baseline')
    require(token_digest(prompt)==expected['token_ids_sha256'],'Prompt tokens differ from baseline template probe')
    require(len(full)<=cutoff,'Sequence exceeds cutoff; refuse silent truncation')
    require(len(full)>len(prompt),'Empty supervision')
    labels=[-100]*len(prompt)+full[len(prompt):]
    supervised=tokenizer.decode(full[len(prompt):],skip_special_tokens=False)
    require(supervised==answer+'<|im_end|>\n','Supervision differs from final answer plus stop')
    require(all(v==-100 for v in labels[:len(prompt)]),'Prompt/history supervised')
    data={'input_ids':full,'attention_mask':[1]*len(full),'labels':labels}
    check={'sample_id':row['sample_id'],'family':row['family'],'prompt_tokens':len(prompt),'total_tokens':len(full),
           'supervised_tokens':len(full)-len(prompt),'prompt_token_ids_sha256':token_digest(prompt),
           'full_token_ids_sha256':token_digest(full),'labels_sha256':token_digest(labels),
           'native_prompt_matches_baseline_reference':True,'no_truncation':True,'final_answer_only':True}
    return data,check


class FinalOnlyCollator:
    """Right-pad input and attention; preserve all labels and pad labels with -100."""
    def __init__(self,pad_token_id):
        require(isinstance(pad_token_id,int),'Tokenizer must supply a padding token')
        self.pad_token_id=pad_token_id

    def __call__(self,features):
        import torch
        require(bool(features),'Empty batch')
        max_len=max(len(f['input_ids']) for f in features)
        batch={k:[] for k in ['input_ids','attention_mask','labels']}
        for f in features:
            size=len(f['input_ids'])
            require(size==len(f['attention_mask'])==len(f['labels']),'Feature lengths differ')
            require(any(x!=-100 for x in f['labels']),'No supervised tokens')
            pad=max_len-size
            batch['input_ids'].append(f['input_ids']+[self.pad_token_id]*pad)
            batch['attention_mask'].append(f['attention_mask']+[0]*pad)
            batch['labels'].append(f['labels']+[-100]*pad)
        return {k:torch.tensor(v,dtype=torch.long,device='cpu') for k,v in batch.items()}
