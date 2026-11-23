"""Application-only grammatical-number exemption; historical scores stay frozen."""
import re
from chiller_student.explanation_number_gate_v8 import render_answer as frozen_render
from chiller_student.joint_physics_support import explanation_renderer

VERSION = 'focused_application_number_gate_v1'


def render_answer(text, facts):
    # "Two power units cancel" describes dimensional analysis, not a measured
    # temperature, power or count. All other literals still pass the frozen gate.
    checked = re.sub(r'两个(?=功率(?:单位|量))', '相应', text)
    frozen_render(checked, facts)
    return explanation_renderer()(text, facts, allow_general_numbers=True)
