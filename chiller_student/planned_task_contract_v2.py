"""Versioned question-only compiler correction; no application activation.

The wire schema/system remain planned_physics_explanation_v1. This code revision
adds an explicitly requested COP-meaning task. Old packages and compilers stay
immutable; package manifests record this algorithm version and source hash.
"""
import copy
import json
import re

from chiller_student.planned_alignment_contract import (
    compile_question as previous_compile, from_task_request as previous_from_task,
    validate_request as previous_validate,
)
from chiller_student.native_sft_data import require

COMPILER_VERSION = 'planned_task_compiler_v2_explicit_COP_meaning'
MEANING = '用单位输入功率对应多少制冷量解释COP；若问无单位原因，说明分子和分母都是功率量，单位相除抵消。'


def compile_question(question):
    plan = previous_compile(question)
    if any(t['task_id'] == 'COP_meaning' for t in plan['tasks']):
        return plan
    for match in re.finditer(r'(?:COP|能效比)[^。；;\n，,]{0,12}(?:表示什么|代表什么|什么意思|是什么含义)', question, re.I):
        prefix = re.split('[。；;\n，,]', question[:match.start()])[-1]
        suffix = question[match.end():]
        if re.search(r'(?:不用|不要|无需|不需要)(?:再)?(?:解释|说明|讨论|展开)\s*$', prefix):
            continue
        if re.match(r'\s*(?:不用|不要|无需)(?:再)?(?:解释|说明|讨论)', suffix):
            continue
        plan['tasks'].append({'task_id': 'COP_meaning', 'instruction': MEANING})
        break
    return plan


def upgrade_request(request):
    payload = previous_validate(request)
    payload['tool_evidence']['answer_task_plan'] = compile_question(payload['question'])
    result = copy.deepcopy(request)
    result['messages'][1]['content'] = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    validate_request(result)
    return result


def from_task_request(request):
    return upgrade_request(previous_from_task(request))


def validate_request(request):
    payload = json.loads(request['messages'][1]['content'])
    require(payload['tool_evidence']['answer_task_plan'] == compile_question(payload['question']), 'v2 task-plan drift')
    old = copy.deepcopy(request)
    pp = json.loads(old['messages'][1]['content'])
    pp['tool_evidence']['answer_task_plan'] = previous_compile(pp['question'])
    old['messages'][1]['content'] = json.dumps(pp, ensure_ascii=False, allow_nan=False)
    previous_validate(old)
    return payload
