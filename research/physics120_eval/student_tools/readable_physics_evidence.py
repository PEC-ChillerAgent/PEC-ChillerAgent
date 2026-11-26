"""Question-independent presentation of already validated Python evidence.

No inferred fault, model answer or evaluator label is added. The original fact
table is retained byte-for-byte as data; derived signs are checked algebraically.
This helper follows evidence_explanation.prepare_explanation, not arbitrary input.
"""
import copy
import json
import math
import re

from student_tools.explanation_protocol import SYSTEM, strict_json
from student_tools.native_sft_data import require

VERSION = 'physics_readable_evidence_v1'
SYSTEM_READABLE = SYSTEM + '''
输出中的工况值和有效点数都要用事实占位符；不要手写其数值或虚构新的事实编号。说明某指标当前可用时引用它的数值事实；说明不可用时引用它的有效点数事实。事实占位符已经包含单位，不再重复添加。
定义和执行状态依据工具说明，不用样本行数证明是否执行了仿真。缺测与有效测量分开表述；无需手写数量来表达拒绝擅自补值。
对涉及多个指标或多个子问的问题，分别说明结论，避免含糊地合并肯定或否定。未核验的动作不能写成已经完成。'''
NAMES = {'power_kW': '输入功率', 'cooling_capacity_kW': '制冷量', 'condenser_heat_kW': '冷凝热',
         'COP': 'COP', 'energy_balance_error_kW': '能量平衡偏差'}
DEPENDENCIES = {
    'power_kW': ['P_W'],
    'cooling_capacity_kW': ['evap_flow_kg_s', 'TEI_K', 'TEO_K'],
    'condenser_heat_kW': ['cond_flow_kg_s', 'TCI_K', 'TCO_K'],
    'COP': ['evap_flow_kg_s', 'TEI_K', 'TEO_K', 'P_W'],
    'energy_balance_error_kW': ['evap_flow_kg_s', 'TEI_K', 'TEO_K', 'cond_flow_kg_s', 'TCI_K', 'TCO_K', 'P_W'],
}


def readable_request(request):
    require(set(request) == {'messages', 'tools'} and request['tools'] is None, 'Two-message physics request required')
    require(len(request['messages']) == 2 and request['messages'][0] == {'role': 'system', 'content': SYSTEM}
            and request['messages'][1]['role'] == 'user', 'Unexpected source contract')
    output = copy.deepcopy(request)
    payload = strict_json(output['messages'][1]['content'])
    evidence = payload['tool_evidence']
    require(evidence['task'] == 'physics' and 'readable_summary' not in evidence, 'Physics evidence must be original')
    facts = {f['fact_id']: f for f in evidence['facts']}
    require(len(facts) == len(evidence['facts']) and all(re.fullmatch(r'F\d+', k) for k in facts), 'Invalid/duplicate fact IDs')
    require(set(evidence['metrics']) == set(NAMES), 'Expected five physical metrics')
    readings = {}
    for name, metric in evidence['metrics'].items():
        count = facts[metric['valid_count_fact_id']]
        require(count['origin'] == 'sample_count' and count['pointer'] == '/result/metrics/' + name + '/valid_count'
                and count['value'] in (0, 1), 'Single-row count reference mismatch')
        fid = metric['value_fact_id']
        fact = facts[fid] if fid is not None else None
        require(bool(fact) == (count['value'] > 0), 'Availability/count mismatch')
        if fact:
            require(fact['pointer'] == '/result/metrics/' + name + '/value' and fact['run_id'] == count['run_id'], 'Value reference mismatch')
            require(type(fact['value']) in (float, int) and math.isfinite(fact['value']), 'Nonfinite result')
            require(fact['origin'] == ('measured' if name == 'power_kW' else 'measured_derived'), 'Origin mismatch')
        missing = metric['missing_fields']
        require(isinstance(missing, list) and all(k in DEPENDENCIES[name] for k in missing), 'Unexpected missing input')
        readings[name] = {'display_name': NAMES[name], 'available': fact is not None,
                          'value_fact_token': '{{fact:' + fid + '}}' if fact else None,
                          'valid_count_fact_token': '{{fact:' + count['fact_id'] + '}}',
                          'source_kind': 'measurement_input' if name == 'power_kW' else 'calculated_from_measurements',
                          'required_input_fields': DEPENDENCIES[name], 'currently_missing_fields': missing}
    relation = {'definition': '冷凝热减制冷量再减输入功率', 'sign': 'unavailable', 'relation': None,
                'meaning': '本次没有有效残差，不能据此认定能量已经闭合',
                'fault_diagnosis': '该残差不是已确认的故障、损失或故障概率'}
    residual_id = evidence['metrics']['energy_balance_error_kW']['value_fact_id']
    if residual_id is not None:
        def number(name): return facts[evidence['metrics'][name]['value_fact_id']]['value']
        qc, qe, power = (number(k) for k in ('condenser_heat_kW', 'cooling_capacity_kW', 'power_kW'))
        residual = facts[residual_id]['value']
        require(math.isclose(residual, qc - qe - power, abs_tol=1e-8, rel_tol=1e-9), 'Residual disagrees with Python values')
        relation.update(value_fact_token='{{fact:' + residual_id + '}}')
        if residual < 0:
            relation.update(sign='negative', relation='Qc < Qe + P', meaning='冷凝热小于制冷量与输入功率之和')
        elif residual > 0:
            relation.update(sign='positive', relation='Qc > Qe + P', meaning='冷凝热大于制冷量与输入功率之和')
        else:
            relation.update(sign='zero', relation='Qc = Qe + P', meaning='本次计算的冷凝热等于制冷量与输入功率之和；不自动证明测量准确或模型适用')
    flags = {k: evidence[k] for k in ('simulation_executed', 'retrieval_executed', 'measurement_alignment_verified', 'fault_diagnosis_performed')}
    require(all(type(v) is bool for v in flags.values()), 'Execution flags must be booleans')
    evidence['readable_summary'] = {'version': VERSION, 'owner': 'deterministic_python_not_model_or_judge',
        'metrics': readings, 'energy_balance': relation,
        'execution': {'physics_formula_calculation': 'executed',
                      'dynamic_simulation': 'executed' if flags['simulation_executed'] else 'not_executed',
                      'knowledge_retrieval': 'executed' if flags['retrieval_executed'] else 'not_executed',
                      'measurement_alignment': 'verified' if flags['measurement_alignment_verified'] else 'not_verified',
                      'fault_diagnosis': 'performed' if flags['fault_diagnosis_performed'] else 'not_performed',
                      'model_suitability': 'not_proven_by_this_physics_calculation',
                      'control_compliance': 'not_proven_by_this_physics_calculation'},
        'citation_rule': 'Only original F fact IDs are citable. Definitions and execution descriptions have no new fact IDs.'}
    require(evidence['facts'] == json.loads(request['messages'][1]['content'])['tool_evidence']['facts'], 'Fact table modified')
    output['messages'][0]['content'] = SYSTEM_READABLE
    output['messages'][1]['content'] = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    return output
