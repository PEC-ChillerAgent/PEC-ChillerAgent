"""Offline-only, versioned static-number correction; never repair model prose.

Actual measurement/count literals still require fact placeholders. This module
does not change any existing application import or historical score.
"""
import re

from chiller_student.explanation_number_gate_v7 import render_answer as prior_render
from chiller_student.joint_physics_support import explanation_renderer

VERSION = 'number_gate_v8_static_dimension_and_residual_sign_offline'


def static_spans(text, facts):
    spans = []
    for pattern in (
        r'一(?=个无量纲(?:量|比值))',
        r'以无量纲的[“\"](?P<constant>1)[”\"]表示',
        # Negative instructions do not assert a current measurement of zero.
        r'(?:不能|不可|不应|不得|不要)(?:直接)?按(?P<constant>零|0)(?:处理|填充|补齐)',
        r'(?:不能|不可|不应)(?:直接)?(?:补|填)(?P<constant>零|0)(?![\d.])',
        r'(?:不能|不可|不应)(?:把|将)(?:缺值|缺测|缺失值|不可用结果)(?:直接)?(?:当成|当作|视为|补成|补为)(?P<constant>零|0)(?![\d.])',
    ):
        for match in re.finditer(pattern, text):
            start, end = match.span('constant') if 'constant' in match.re.groupindex else match.span()
            spans.append((start, end, 'nonmeasurement_constant_or_negative_instruction'))
    cited = set(re.findall(r'\{\{fact:(F\d+)\}\}', text))
    residuals = [f for f in facts if f.fact_id in cited and
                 f.pointer == '/result/metrics/energy_balance_error_kW/value']
    # Includes R=Qc-Qe-P>0 and a stand-alone R>0. Only mathematical definitions
    # or a correctly signed, already cited current residual are allowed.
    pattern = r'(?<![A-Za-z0-9_])R\s*(?:=\s*Qc\s*[-−]\s*Qe\s*[-−]\s*P\s*)?(?P<relation>[>＞<＜])\s*(?P<zero>0)(?![\d.])'
    for match in re.finditer(pattern, text, re.I):
        prefix = re.split('[。；;\n，,]', text[:match.start()])[-1]
        suffix = text[match.end():]
        current = bool(re.search(r'本次|当前|这次', prefix))
        hypothetical = bool(re.search(r'如果|假设|若|当', prefix))
        definition = bool(re.match(r'\s*(?:时|表示|意味着|说明)', suffix)) and not current
        correct = len(residuals) == 1 and (
            residuals[0].value > 0 if match['relation'] in ('>', '＞') else residuals[0].value < 0)
        if hypothetical or definition or correct:
            spans.append((*match.span('zero'), 'defined_or_cited_residual_sign'))
    return sorted(set(spans))


def render_answer(text, facts):
    masked = text
    for start, end, _ in reversed(static_spans(text, facts)):
        masked = masked[:start] + '已核对静态表达' + masked[end:]
    prior_render(masked, facts)
    # This second call preserves the exact original text and fact-linked output.
    return explanation_renderer()(text, facts, allow_general_numbers=True)
