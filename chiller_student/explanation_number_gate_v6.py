"""Allow proven mathematical zero/sign statements, not uncited run values.

Historical v5 results remain unchanged. Validation masks only identified spans;
the returned text/segments are the student's exact original text.
"""
import re
from chiller_student.explanation_number_gate_v5 import render_answer as v5
from chiller_student.joint_physics_support import explanation_renderer

VERSION='number_gate_v6_proven_math_zero'
def proven_spans(text,facts):
    cited=set(re.findall(r'\{\{fact:(F\d+)\}\}',text));spans=[]
    p=[f for f in facts if f.fact_id in cited and f.pointer=='/result/metrics/power_kW/value' and f.value==0]
    r=[f for f in facts if f.fact_id in cited and f.pointer=='/result/metrics/energy_balance_error_kW/value']
    if len(p)==1:
        for m in re.finditer(r'(?:P_W|输入功率|功率)(?:为|是|(?:已)?观(?:察|测)到|测得)(?P<zero>零)(?!功率缺测)',text):
            spans.append((m.start('zero'),m.end('zero'),'cited_observed_zero_power'))
    for m in re.finditer(r'COP[^。；;\n，,]{0,15}(?:需要|要求|条件为|前提为)[^。；;\n，,]{0,12}P(?:_W)?\s*[>＞]\s*(?P<zero>0)(?![\d.])',text,re.I):
        spans.append((m.start('zero'),m.end('zero'),'definition_positive_power_threshold'))
    for m in re.finditer(r'(?:残差|能量平衡偏差|能量偏差)(?P<relation>大于|小于)(?P<zero>零)',text):
        prefix=re.split('[。；;\n，,]',text[:m.start()])[-1]
        hypothetical=bool(re.search(r'若|如果|假设|当',prefix))
        correct_current=len(r)==1 and ((m['relation']=='大于' and r[0].value>0) or (m['relation']=='小于' and r[0].value<0))
        if hypothetical or correct_current:spans.append((m.start('zero'),m.end('zero'),'definition_or_cited_residual_sign'))
    return sorted(set(spans))

def render_answer(text,facts):
    masked=text
    for start,end,kind in reversed(proven_spans(text,facts)):masked=masked[:start]+'已核对常量'+masked[end:]
    v5(masked,facts)
    return explanation_renderer()(text,facts,allow_general_numbers=True)
