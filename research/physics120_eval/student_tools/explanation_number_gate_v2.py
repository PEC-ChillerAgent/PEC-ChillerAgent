"""Keep measured numbers gated; allow narrow discourse/ordinal constructions.

The original answer is preserved. First validate a non-quantity-masked view with
the frozen numerical gate, then run the original attribution checks on original
text. This is an explicitly versioned code change, never a model improvement.
"""
import re

from student_tools.joint_physics_support import explanation_renderer as legacy_renderer

VERSION = 'explanation_number_gate_v2'
DISCOURSE = re.compile(r'另[一]组(?:参数|测点|字段)|这[两二三]个(?:指标|结果)|这[两二三]项(?:指标|结果)|这一(?:关键|必要)?输入(?:参数|字段)?')
ORDINAL = re.compile(r'(?m)^(\s*)\d{1,2}[.、)]\s+(?=[\u4e00-\u9fff*])')
MISSING_NEGATION = re.compile(r'(?:不能|不可|不应|不得|不要)(?:直接)?按零(?:处理|填充|补齐)')


def render_answer(text, facts):
    renderer = legacy_renderer()
    masked = ORDINAL.sub(r'\1', DISCOURSE.sub('相关', text))
    cited = set(re.findall(r'\{\{fact:(F\d+)\}\}', text))
    missing = any(f.fact_id in cited and f.origin == 'sample_count' and f.value == 0
                  and f.pointer.startswith('/result/metrics/') and f.pointer.endswith('/valid_count') for f in facts)
    if missing: masked = MISSING_NEGATION.sub('不能擅自补值', masked)
    renderer(masked, facts)
    # The first pass already rejected all unreferenced measurement numbers and
    # unknown placeholders. The second preserves original text/segments and all
    # fact-attribution and zero-claim checks; it does not repair model prose.
    return renderer(text, facts, allow_general_numbers=True)
