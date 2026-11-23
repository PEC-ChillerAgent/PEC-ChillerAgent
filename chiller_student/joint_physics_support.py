"""Shared request identity and application workflow; no training jobs."""
import copy
import json
import hashlib
from chiller_student.explanation_protocol import strict_json
from chiller_student.native_sft_data import require

WORKFLOW = {
    'version': 'chiller_project_workflow_v1',
    'facts': [
        '当前数据集和已保存的运行结果不会随补录自动修改。',
        '补录后上传或录入新数据，确认列映射和单位，选择新数据并新建对话，重新执行计算。',
        '新计算产生新的运行记录；历史报告保留原记录，不能当成已自动更新。',
    ],
}

def canonical_hash(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

def explanation_renderer():
    from energy_agent.agents.reporting import render_answer
    return render_answer

def with_workflow(request):
    """Supply application behavior as context, never as a hidden gold answer."""
    request = copy.deepcopy(request)
    payload = strict_json(request['messages'][1]['content'])
    require('tool_evidence' in payload and 'project_workflow' not in payload['tool_evidence'], 'Wrong explanation request')
    payload['tool_evidence']['project_workflow'] = copy.deepcopy(WORKFLOW)
    request['messages'][1]['content'] = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    return request
