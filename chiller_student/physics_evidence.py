"""Deterministic, single-row development evidence. No judges or model answers.

Definitions are frozen from workbench._calculate and data.pipeline. This is an
offline experiment module, not a production multi-row analysis implementation.
"""
import copy
import json
import math
from chiller_student.native_sft_data import require

FIELDS = {
    'TEI_K': ('冷冻水进水温度', 'K'), 'TEO_K': ('冷冻水出水温度', 'K'),
    'TCI_K': ('冷却水进水温度', 'K'), 'TCO_K': ('冷却水出水温度', 'K'),
    'evap_flow_kg_s': ('冷冻水质量流量', 'kg/s'),
    'cond_flow_kg_s': ('冷却水质量流量', 'kg/s'),
    'P_W': ('实测输入功率', 'W'), 'TSet_K': ('冷冻水出水设定温度（非实测出水温度）', 'K'),
}
METRICS = {
    'power_kW': ('P_W/1000', 'measured'),
    'cooling_capacity_kW': ('evap_flow_kg_s*cp*(TEI_K-TEO_K)/1000', 'measured_derived'),
    'condenser_heat_kW': ('cond_flow_kg_s*cp*(TCO_K-TCI_K)/1000', 'measured_derived'),
    'COP': ('cooling_capacity_kW/power_kW，要求有效正功率', 'measured_derived'),
    'energy_balance_error_kW': ('condenser_heat_kW-cooling_capacity_kW-power_kW', 'measured_derived'),
}


def build_evidence(inspect, analysis):
    dataset = inspect['dataset']
    require(inspect['status'] == 'success', 'Inspection must have succeeded')
    require(dataset['row_count'] == 1, 'Evidence v1 supports single-row development cases only')
    require(analysis['status'] in {'success', 'partial'} and not analysis['errors'], 'Failed analysis is unsupported')
    schema = dataset['effective_schema']; columns = dataset['columns']; mapping = schema['column_map']
    facts = analysis['facts']
    require(len({f['fact_id'] for f in facts}) == len(facts), 'Duplicate fact ID')
    require(len({f['pointer'] for f in facts}) == len(facts), 'Duplicate fact pointer')
    by_pointer = {f['pointer']: f for f in facts}
    for pointer in ['/result/input_rows', '/result/output_rows']:
        require(by_pointer[pointer]['value'] == 1, 'Only one input and output row supported')
    fields = {}
    for field, (meaning, unit) in FIELDS.items():
        source = mapping.get(field)
        fields[field] = {'meaning': meaning, 'source_column': source if source in columns else None,
                         'mapped_column_present': source in columns if source is not None else False,
                         'internal_unit': unit}
    metrics = {}
    for metric, (formula, origin) in METRICS.items():
        prefix = '/result/metrics/'+metric
        count = by_pointer[prefix+'/valid_count']; value = by_pointer.get(prefix+'/value')
        require(count['origin'] == 'sample_count' and count['unit'] == '条', 'Count/value type confusion')
        require(math.isfinite(count['value']) and count['value'] in (0, 1), 'Invalid single-row valid count')
        require((value is not None) == (count['value'] == 1), 'Value and valid_count disagree')
        if value is not None:
            require(value['origin'] == origin and math.isfinite(value['value']), 'Invalid metric value/origin')
            require(value['unit'] == ('1' if metric == 'COP' else 'kW'), 'Unexpected result unit')
        reasons = [item for item in analysis['missing_inputs'] if item['target'] == metric]
        require(not (value is not None and reasons), 'Single-row value contradicts missing reason')
        missing = sorted({field for item in reasons for field in item['fields']})
        require(all(field in FIELDS for field in missing), 'Unknown missing field')
        metrics[metric] = {'definition': formula, 'origin': origin,
                           'status': '有有效值' if value is not None else '无有效值',
                           'value_fact_id': value['fact_id'] if value else None,
                           'valid_count_fact_id': count['fact_id'],
                           'missing_internal_fields': missing}
    return {
        'schema_version': 'single_row_physics_evidence_v1',
        'scope': '由工具事实与固定代码定义生成；列存在不保证单元格有效；无值不等于测得零值；计数不是指标值。',
        'fields': fields, 'metrics': metrics,
        'source_units': {k: schema[k] for k in ['temperature_unit', 'flow_unit', 'power_unit']},
        'unit_rules': '温度 C 加273.15转K；F先减32乘5/9再加273.15转K。m3/h乘密度除3600转kg/s；US gpm乘0.003785411784乘密度除60转kg/s；kg/s不转换。kW乘1000转W。密度用于体积流量转质量流量，cp用于质量流量乘温差得到热功率，不能用于流量转换。结果热功率为kW，COP无量纲。',
        'balance_rule': '残差为冷凝热减制冷量再减输入功率；负号表示冷凝热小于制冷量与输入功率之和，不表示能量已闭合，不等于效率损失或已确诊故障。',
        'execution': {'physics_executed': True, 'simulation_executed': False,
                      'model_validity_counts_are_validation': False},
    }


def enhance_request(request):
    """Only enrich the existing chiller_analyze tool message; all else unchanged."""
    result = copy.deepcopy(request)
    messages = result['messages']
    calls = {c['id']: c['function'] for m in messages if m['role'] == 'assistant' for c in m['tool_calls']}
    tools = {calls[m['tool_call_id']]['name']: m for m in messages if m['role'] == 'tool'}
    require(set(tools) == {'inspect_dataset', 'chiller_analyze'}, 'Unexpected tool history')
    fn = next(c for c in calls.values() if c['name'] == 'chiller_analyze')
    require(json.loads(fn['arguments']) == {'task': 'physics'}, 'Physics-only probe')
    target = tools['chiller_analyze']
    analysis = json.loads(target['content'])
    require('interpretation_evidence' not in analysis, 'Already enhanced')
    analysis['interpretation_evidence'] = build_evidence(json.loads(tools['inspect_dataset']['content']), analysis)
    target['content'] = json.dumps(analysis, ensure_ascii=False)
    return result
