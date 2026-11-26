"""High-precision repetition guard; not a factual/completeness certificate."""
import re
from collections import Counter

VERSION='physics_explanation_repetition_guard_v1'
def check_repetition(answer):
    if not isinstance(answer,str):raise ValueError('Answer must be text')
    paragraphs=[re.sub(r'\s+','',p) for p in re.split(r'\n\s*\n',answer) if p.strip()]
    sentences=[re.sub(r'\s+','',s) for s in re.split(r'[。！？!?\n]',answer) if s.strip()]
    issues=[]
    for paragraph,count in Counter(paragraphs).items():
        if len(paragraph)>=80 and count>=2:
            issues.append({'kind':'repeated_long_paragraph','characters':len(paragraph),'occurrences':count,'excerpt':paragraph[:100]})
    for sentence,count in Counter(sentences).items():
        if len(sentence)>=12 and count>=4:
            issues.append({'kind':'repeated_sentence_loop','characters':len(sentence),'occurrences':count,'excerpt':sentence[:100]})
    return {'version':VERSION,'passed_repetition_check':not issues,'issues':issues,
        'automatic_semantic_pass':False,'model_text_repaired':False,'domain_accuracy':None}
