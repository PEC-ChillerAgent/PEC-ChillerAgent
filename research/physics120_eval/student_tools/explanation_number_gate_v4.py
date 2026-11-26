"""Versioned non-quantity vocabulary fix; original v2/v3 remain immutable."""
import re
from student_tools.explanation_number_gate_v3 import render_answer as render_v3
from student_tools.joint_physics_support import explanation_renderer

VERSION='explanation_number_gate_v4_nonquantity_vocabulary_units_r2'
# Exact lexical/unit tokens, not a blanket exemption for Chinese numerals.
# In "72 m3/h" only the unit token is exempt:72 remains a rejected quantity.
_WORDS=re.compile(r'两者|二者|三者|归一化|一定|两回事|两套(?:独立的)?测量|这[两二三四五]项|五项指标|(?<![A-Za-z0-9_])m(?:3|\^3)/h(?![A-Za-z0-9_])|(?<![A-Za-z0-9_])(?:evap|cond)_flow_m3_h(?![A-Za-z0-9_])')

def nonquantity_spans(text):
    return [{'start':m.start(),'end':m.end(),'text':m.group(),'model_text_changed':False} for m in _WORDS.finditer(text)]

def render_answer(text,facts):
    # Only the validation VIEW is masked. All real quantities, references,
    # zero claims and attribution still undergo the existing v3 checks.
    masked=_WORDS.sub('相关概念',text)
    render_v3(masked,facts)
    return explanation_renderer()(text,facts,allow_general_numbers=True)
