"""Narrow static zero definitions; never accept handwritten run measurements."""
import re
from student_tools.explanation_number_gate_v6 import proven_spans as old_spans
from student_tools.explanation_number_gate_v5 import render_answer as v5
from student_tools.joint_physics_support import explanation_renderer

VERSION='number_gate_v7_static_residual_zero_definition'
def proven_spans(text,facts):
    spans=list(old_spans(text,facts))
    for pattern in (
        r'P为(?P<zero>零)仍(?:然)?(?:能|可)(?:以)?参与残差计算',
        r'(?:不把|不能把)P为(?P<zero>零)(?:说成|当成)没有测量',
    ):
        for m in re.finditer(pattern,text):
            prefix=re.split('[。；;\n，,]',text[:m.start()])[-1]
            current=bool(re.search(r'本次|当前|这次',prefix)) and not bool(re.search(r'如果|假设|若|当',prefix))
            if current:continue
            spans.append((m.start('zero'),m.end('zero'),'code_defined_observed_zero_and_residual'))
    return sorted(set(spans))

def render_answer(text,facts):
    masked=text
    for start,end,_ in reversed(proven_spans(text,facts)):masked=masked[:start]+'已核对常量'+masked[end:]
    v5(masked,facts)
    return explanation_renderer()(text,facts,allow_general_numbers=True)
