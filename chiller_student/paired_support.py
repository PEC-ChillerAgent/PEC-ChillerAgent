"""Inference file hashing and lossless completion decoding."""
import hashlib
import json
from pathlib import Path
from chiller_student.native_sft_data import require,token_digest

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path,obj):
    with Path(path).open('x',encoding='utf-8') as f:json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False)


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
