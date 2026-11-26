"""Permit a narrow, already-referenced duplicate zero valid-count statement.

Measurement literals remain subject to v2. No model prose is repaired. This
version changes application compatibility, never historical model scores.
"""
import re
from student_tools.explanation_number_gate_v2 import render_answer as render_v2
from student_tools.joint_physics_support import explanation_renderer as legacy_renderer

VERSION='explanation_number_gate_v3_referenced_zero_count'
_LABELS={
    '输入功率':'power_kW','功率':'power_kW','制冷量':'cooling_capacity_kW','冷量':'cooling_capacity_kW',
    '冷凝热':'condenser_heat_kW','COP':'COP','能量平衡偏差':'energy_balance_error_kW','能量偏差':'energy_balance_error_kW',
}
_LABEL='(?:'+'|'.join(sorted(map(re.escape,_LABELS),key=len,reverse=True))+')'
_GROUP=_LABEL+r'(?:\s*(?:和|与|及|、)\s*'+_LABEL+r'){0,4}'
_REDUNDANT=re.compile(
    r'(?:^|[，,。；;\n])\s*(?:(?:因此|所以|当前|目前|本次)\s*)?'
    r'(?P<metrics>'+_GROUP+r')\s*(?:(?:当前|目前|本次|均|都)\s*){0,2}'
    r'(?:不可得|不可用|无法计算|不能计算)[，,]\s*有效点数(?:均)?为\s*'
    r'(?P<number>0|零)(?=(?:\s*条)?(?:[，,。；;\n]|$))',re.I)

def verified_redundant_zero_counts(text,facts):
    """Each named metric needs its own earlier, zero-count F reference."""
    citations={}
    for m in re.finditer(r'\{\{fact:(F\d+)\}\}',text):citations.setdefault(m.group(1),m.start())
    verified=[]
    for match in _REDUNDANT.finditer(text):
        labels=re.findall(_LABEL,match['metrics'],re.I)
        metrics=list(dict.fromkeys(_LABELS['COP' if label.upper()=='COP' else label] for label in labels))
        selected=[]
        for metric in metrics:
            counts=[f for f in facts if f.pointer=='/result/metrics/'+metric+'/valid_count'
                    and f.origin=='sample_count' and f.unit=='条' and type(f.value) in (int,float) and f.value==0
                    and citations.get(f.fact_id,len(text))<match.start('number')]
            values=[f for f in facts if f.pointer=='/result/metrics/'+metric+'/value']
            if len(counts)!=1 or values:break
            selected.append(counts[0])
        else:
            if selected and len({f.run_id for f in selected})==1:
                verified.append({'number_start':match.start('number'),'number_end':match.end('number'),
                    'raw_literal':match['number'],'metrics':metrics,'fact_ids':[f.fact_id for f in selected],
                    'verified_valid_count':0,'model_text_changed':False})
    return verified

def render_answer(text,facts):
    spans=verified_redundant_zero_counts(text,facts)
    if not spans:return render_v2(text,facts)
    masked=text
    for span in reversed(spans):
        masked=masked[:span['number_start']]+'已引用点数'+masked[span['number_end']:]
    # Every other literal, placeholder and attribution still goes through v2.
    render_v2(masked,facts)
    # Preserve original prose and original fact-linked segments, including the
    # duplicate literal whose role/value were independently verified above.
    return legacy_renderer()(text,facts,allow_general_numbers=True)
