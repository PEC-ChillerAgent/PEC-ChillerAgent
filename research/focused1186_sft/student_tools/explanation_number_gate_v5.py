"""Optional proven-count/negative-inference handling, with unchanged prose.

No blanket allowance for numbers or 零. Historical v2-v4 gates stay frozen.
Not enabled by the current app or task-contract comparison package.
"""
import re
from student_tools.explanation_number_gate_v4 import render_answer as v4
from student_tools.joint_physics_support import explanation_renderer

VERSION='explanation_number_gate_v5_cited_zero_and_discourse_scope'
WORDS=re.compile(r'混为一谈|两个部分')
ORDINAL=re.compile(r'(?P<prefix>^|[。；;\n：:])\s*\d{1,2}[.、)](?=\s*(?:补录|上传|确认|选择|重新|新计算|历史))',re.M)
LABELS={'输入功率':'power_kW','功率':'power_kW','制冷量':'cooling_capacity_kW','冷量':'cooling_capacity_kW',
 '冷凝热':'condenser_heat_kW','COP':'COP','能量平衡偏差':'energy_balance_error_kW','能量偏差':'energy_balance_error_kW','残差':'energy_balance_error_kW'}
LABEL='(?:'+'|'.join(sorted(map(re.escape,LABELS),key=len,reverse=True))+')'
COUNT=re.compile(r'(?P<metric>'+LABEL+r')\s*(?:(?:当前|本次|仍)?(?:不可得|不可用|无法计算|不能计算)[，,]\s*)?有效点数(?:均)?为\s*(?P<zero>0|零)(?![\d.eE零〇一二两三四五六七八九十百千万亿点])',re.I)
NEGATIVE=re.compile(r'(?:不能|不可|不应)(?:由此|因此|据此)?(?:直接)?(?:推断|认定|说明|表示)?(?:输入功率|功率)(?:为|是|等于)(?P<zero>0|零)(?![\d.eE零〇一二两三四五六七八九十百千万亿点])')


def verified_spans(text,facts):
    cited=set(re.findall(r'\{\{fact:(F\d+)\}\}',text));spans=[]
    for match in COUNT.finditer(text):
        metric=LABELS['COP' if match['metric'].upper()=='COP' else match['metric']]
        counts=[f for f in facts if f.fact_id in cited and f.pointer=='/result/metrics/'+metric+'/valid_count'
                and f.origin=='sample_count' and f.unit=='条' and f.value==0]
        if len(counts)==1 and not any(f.pointer=='/result/metrics/'+metric+'/value' for f in facts):
            spans.append({'start':match.start('zero'),'end':match.end('zero'),'kind':'already_cited_zero_count','fact_id':counts[0].fact_id})
    power=[f for f in facts if f.fact_id in cited and f.pointer=='/result/metrics/power_kW/value' and f.origin=='measured']
    if len(power)==1 and power[0].value>0:
        for match in NEGATIVE.finditer(text):spans.append({'start':match.start('zero'),'end':match.end('zero'),'kind':'cannot_infer_zero_from_missingness_with_known_positive_power','fact_id':power[0].fact_id})
    return sorted(spans,key=lambda s:(s['start'],s['end']))


def render_answer(text,facts):
    spans=verified_spans(text,facts);masked=text
    for s in reversed(spans):masked=masked[:s['start']]+'已引用事实'+masked[s['end']:]
    masked=WORDS.sub('概念区别',masked)
    masked=ORDINAL.sub(lambda m:m['prefix']+'步骤：',masked)
    v4(masked,facts)
    # Validation alone used a masked view. Keep the exact original text and
    # fact-linked segments, without inserting a reference or replacing an answer.
    return explanation_renderer()(text,facts,allow_general_numbers=True)
