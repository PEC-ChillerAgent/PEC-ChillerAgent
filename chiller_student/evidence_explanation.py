"""Development contract for student-authored, fact-referenced explanations.

No model/service calls or app routing. Strict formatting is not semantic proof.
The deployed selection service intentionally does not accept this new task.
"""
import json
import math

from energy_agent.agents.reporting import result_facts
from energy_agent.contracts.datasets import DatasetInfo
from energy_agent.contracts.tools import ToolResult
from chiller_student.structured_physics import build_context_from_payloads, canonical_hash, require
from chiller_student.explanation_protocol import VERSION, SYSTEM, validate_explanation


def prepare_explanation(info, artifact, question):
    info = DatasetInfo.model_validate(info).model_dump(mode='json')
    result = ToolResult.model_validate(artifact['result']).model_dump(mode='json')
    require(isinstance(question, str) and 0 < len(question.strip()) <= 12000, 'Nonempty current question required')
    require(result['asset_id'] == info['asset_id'] and result['dataset_id'] == info['dataset_id']
            and result['dataset_version'] == info['version'], 'Cross-dataset physical result')
    request = result['request']
    require(request['asset_id'] == info['asset_id'] and request['dataset_id'] == info['dataset_id']
            and request['task'] == result['task'] == 'physics' and request['simulation'] is None,
            'Physics-only request required')
    require(info['row_count'] == result['input_rows'] == result['output_rows'] == 1, 'Single-row development only')
    require(result['status'] in ('success', 'partial') and not result['errors'], 'Valid physical evidence required')
    output = artifact['model_output']
    require(output['metadata']['operation'] == 'calculate' and len(output['records']) == 1
            and output['metadata']['schema'] == info['effective_schema'], 'Physical artifact/schema mismatch')
    facts = [f for f in result_facts(result, 0) if f.origin != 'model_validity']
    for fact in facts:
        node = artifact
        for key in fact.pointer.lstrip('/').split('/'):
            node = node[int(key)] if isinstance(node, list) else node[key]
        require(type(node) in (int, float) and math.isfinite(node) and node == fact.value, 'Fact pointer mismatch')
    analysis = {key: result[key] for key in ('status', 'run_id', 'missing_inputs', 'warnings', 'errors', 'notes')}
    analysis['facts'] = [f.model_dump(mode='json') for f in facts]
    context = build_context_from_payloads({'status': 'success', 'dataset': info}, analysis)
    metrics = {name: {'value_fact_id': item['value_fact_id'], 'valid_count_fact_id': item['valid_count_fact_id'],
                      'missing_fields': sorted(set(item['missing_internal_fields'] + item['unmapped_fields']))}
               for name, item in context['metrics'].items()}
    # These are code definitions, not model answers, reviewer labels or gold prose.
    definitions = {
        'power_kW': '按有效实测输入功率字段处理。',
        'cooling_capacity_kW': '由冷冻侧质量流量、比热和进水减出水温差计算，属于测量派生。',
        'condenser_heat_kW': '由冷却侧质量流量、比热和出水减进水温差计算，属于测量派生。',
        'COP': '制冷量除以有效正输入功率，无量纲，属于测量派生。',
        'energy_balance_error_kW': '冷凝热减制冷量再减输入功率；为代数残差，不是已确认的故障、损失或故障概率。',
    }
    payload = {'contract_version': VERSION, 'question': question,
               'tool_evidence': {'task': 'physics', 'status': result['status'],
                    'metrics': metrics, 'facts': analysis['facts'], 'definitions': definitions,
                    'field_mapping': info['effective_schema']['column_map'],
                    'source_units': context['evidence']['source_units'],
                    'warnings': result['warnings'], 'missing_inputs': result['missing_inputs'],
                    'simulation_executed': False, 'retrieval_executed': False,
                    'measurement_alignment_verified': False, 'fault_diagnosis_performed': False},
               'response_schema': {'type': 'object', 'additionalProperties': False,
                    'required': ['answer'], 'properties': {'answer': {'type': 'string', 'minLength': 1, 'maxLength': 6000}}}}
    messages = [{'role': 'system', 'content': SYSTEM},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, allow_nan=False)}]
    return {'messages': messages, 'tools': None, 'request_sha256': canonical_hash({'messages': messages, 'tools': None}),
            'evidence_sha256': canonical_hash({'dataset_info': info, 'artifact': artifact}),
            'facts': facts, 'semantic_review': 'pending', 'domain_accuracy': None}
