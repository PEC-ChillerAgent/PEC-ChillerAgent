"""Offline single-row contract prototype. No model calls or production routing.

The model selects topics/check IDs. Numerical facts and definitions are rendered
from validated tools. Free prose is retained for review, never certified by the
JSON validator. This is not a replacement for semantic evaluation.
"""
import copy
import hashlib
import html
import json
import math
import re

from chiller_student.physics_evidence import FIELDS, METRICS, build_evidence

VERSION = 'physics_selection_v0'
TOPICS = ('metrics', 'energy_balance', 'missing_inputs', 'units', 'measurement_origin', 'simulation_status', 'data_update_workflow')
NAMES = dict(zip(METRICS, ('输入功率', '制冷量', '冷凝热', 'COP', '能量平衡偏差')))
DEPENDENCIES = {
    'power_kW': ('P_W',),
    'cooling_capacity_kW': ('evap_flow_kg_s', 'TEI_K', 'TEO_K'),
    'condenser_heat_kW': ('cond_flow_kg_s', 'TCI_K', 'TCO_K'),
    'COP': ('evap_flow_kg_s', 'TEI_K', 'TEO_K', 'P_W'),
    'energy_balance_error_kW': ('evap_flow_kg_s', 'TEI_K', 'TEO_K', 'cond_flow_kg_s', 'TCI_K', 'TCO_K', 'P_W'),
}
BASE_CHECKS = {
    'verify_source_mapping': '核对源列、单位配置和自动映射；工具给出了配置，不等于已人工确认。',
    'verify_measurement_alignment': '核对测量时刻、测点位置与统计边界是否一致。',
    'assess_uncertainty_and_reference': '结合传感器不确定度和匹配工况基准判断偏差，不能直接由残差确诊故障。',
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def tool_payloads(request):
    """Use the original physics tool history, never teacher/judge content."""
    functions = {}
    for msg in request['messages']:
        for call in msg.get('tool_calls', []):
            require(call['id'] not in functions, 'Duplicate tool call ID')
            functions[call['id']] = call['function']
    payloads = {}
    for msg in request['messages']:
        if msg['role'] != 'tool':
            continue
        fn = functions[msg['tool_call_id']]
        name = fn['name']
        require(name not in payloads, 'Duplicate tool response')
        if name == 'chiller_analyze':
            require(json.loads(fn['arguments']) == {'task': 'physics'}, 'Physics-only prototype')
        payloads[name] = json.loads(msg['content'])
    require(set(payloads) == {'inspect_dataset', 'chiller_analyze'}, 'Both physics tools required')
    return payloads['inspect_dataset'], payloads['chiller_analyze']


def build_context(request):
    inspect, analysis = tool_payloads(request)
    return build_context_from_payloads(inspect, analysis)


def build_context_from_payloads(inspect, analysis):
    """Share evidence checks without inventing a model/tool conversation."""
    evidence = build_evidence(inspect, analysis)
    schema = inspect['dataset']['effective_schema']
    require(type(inspect['dataset']['row_count']) is int, 'Invalid row count type')
    require(schema['temperature_unit'] in ('C', 'F', 'K'), 'Unsupported temperature unit')
    require(schema['flow_unit'] in ('kg/s', 'm3/h', 'us_gpm'), 'Unsupported flow unit')
    require(schema['power_unit'] in ('W', 'kW'), 'Unsupported power unit')
    for name in ('water_specific_heat_J_kgK', 'water_density_kg_m3'):
        value = schema[name]
        require(type(value) in (float, int) and math.isfinite(value) and value > 0, 'Invalid fluid property')
    facts = {f['fact_id']: copy.deepcopy(f) for f in analysis['facts']}
    for fid, fact in facts.items():
        require(re.fullmatch(r'F\d+', fid) is not None, 'Invalid fact ID')
        require(fact['run_id'] == analysis['run_id'], 'Cross-run fact')
        require(type(fact['value']) in (float, int) and math.isfinite(fact['value']), 'Invalid numeric fact')
        if fact['pointer'] in ('/result/input_rows', '/result/output_rows'):
            require(fact['origin'] == 'sample_count' and fact['unit'] == '条', 'Invalid row-count fact')
    metrics = copy.deepcopy(evidence['metrics'])
    for metric, item in metrics.items():
        absent = [field for field in DEPENDENCIES[metric]
                  if not evidence['fields'][field]['mapped_column_present']]
        require(not (item['value_fact_id'] and absent), 'Available metric has absent dependencies')
        item['unmapped_fields'] = absent
        item['value'] = facts[item['value_fact_id']]['value'] if item['value_fact_id'] else None
        item['valid_count'] = int(facts[item['valid_count_fact_id']]['value'])
        item['unit'] = '1' if metric == 'COP' else 'kW'
    power = metrics['power_kW']['value']
    cooling = metrics['cooling_capacity_kW']['value']
    condensing = metrics['condenser_heat_kW']['value']
    cop = metrics['COP']['value']
    balance = metrics['energy_balance_error_kW']['value']
    # A single-row aggregate must obey these identities. Multi-row averages
    # cannot use the same checks and are explicitly rejected by build_evidence.
    if cop is not None:
        require(power is not None and power > 0 and cooling is not None, 'COP lacks valid operands')
        require(math.isclose(cop, cooling / power, rel_tol=1e-8, abs_tol=1e-8), 'Inconsistent COP')
    if balance is not None:
        require(all(v is not None for v in (power, cooling, condensing)), 'Residual lacks operands')
        require(math.isclose(balance, condensing - cooling - power, rel_tol=1e-8, abs_tol=1e-8), 'Inconsistent residual')
    checks = dict(BASE_CHECKS)
    unavailable_fields = {field for item in metrics.values() if item['value'] is None
                          for field in item['unmapped_fields'] + item['missing_internal_fields']}
    for field in sorted(unavailable_fields):
        suffix = '缺列、空值、无效值与非正功率应分别核对。' if field == 'P_W' else '缺列、空值和无效值应分别核对，不能直接认定传感器损坏。'
        checks['verify_input:' + field] = f'核查并按需补充{FIELDS[field][0]}的有效测量；' + suffix
    if metrics['COP']['value'] is None and power is not None and power <= 0:
        checks['verify_positive_power'] = '实测功率存在，但 COP 计算需要有效正功率；核对运行状态和测量，不把零值当缺测。'
    if unavailable_fields:
        checks['reanalyze_new_dataset'] = '补充或修改测量后重新上传，选择新数据集并新建对话，再按新数据执行物理分析；当前会话绑定不能原地修改。'
    return {'context_version': 'single_row_contract_context_v0',
            'source_sha256': canonical_hash({'inspect': inspect, 'analysis': analysis}),
            'run_id': analysis['run_id'], 'dataset_id': inspect['dataset']['dataset_id'],
            'analysis_status': analysis['status'], 'warnings': copy.deepcopy(analysis['warnings']),
            'facts': facts, 'evidence': evidence, 'metrics': metrics, 'allowed_checks': checks,
            'scope': 'single_row_seen_development; upstream tools trusted, no raw-sensor recalculation'}


def candidate_schema(context):
    def array(values, minimum=0):
        return {'type': 'array', 'items': {'type': 'string', 'enum': list(values)},
                'uniqueItems': True, 'minItems': minimum, 'maxItems': len(values)}
    return {'type': 'object', 'additionalProperties': False,
            'required': ['schema_version', 'answer_topics', 'focus_metrics', 'followup_check_ids', 'explanation_draft'],
            'properties': {'schema_version': {'const': VERSION},
                           'answer_topics': array(TOPICS, 1),
                           'focus_metrics': array(METRICS, 1),
                           'followup_check_ids': array(context['allowed_checks']),
                           'explanation_draft': {'type': 'string', 'maxLength': 1500}}}


def parse_candidate(raw, context):
    """Strict parse, no extraction from fences, repairs, or silent field removal."""
    require(isinstance(raw, str) and len(raw) <= 12000, 'Invalid response length')
    def unique_object(pairs):
        obj = {}
        for key, value in pairs:
            require(key not in obj, 'Duplicate JSON key')
            obj[key] = value
        return obj
    def reject_constant(value):
        raise ValueError('Nonfinite JSON constant: ' + value)
    obj = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    required = set(candidate_schema(context)['required'])
    require(isinstance(obj, dict) and set(obj) == required, 'Unexpected/missing fields')
    require(obj['schema_version'] == VERSION, 'Wrong contract version')
    for name, allowed, minimum in [('answer_topics', TOPICS, 1), ('focus_metrics', METRICS, 1),
                                    ('followup_check_ids', context['allowed_checks'], 0)]:
        seq = obj[name]
        require(isinstance(seq, list) and minimum <= len(seq) <= len(allowed), 'Invalid selection length')
        require(all(isinstance(v, str) and v in allowed for v in seq), 'Unknown/inapplicable selection')
        require(len(seq) == len(set(seq)), 'Duplicate selection')
    require(isinstance(obj['explanation_draft'], str) and len(obj['explanation_draft']) <= 1500, 'Invalid draft')
    return obj


def _escaped(value):
    return html.escape(str(value)).replace('|', '&#124;').replace('\n', ' ').replace('\r', ' ').replace('`', '&#96;')


def render_trusted_block(context, candidate):
    """Render validated selections plus tool facts; never insert free prose."""
    candidate = parse_candidate(json.dumps(candidate, ensure_ascii=False, allow_nan=False), context)
    lines = ['以下为程序依据本次工具结果生成的事实区。', '',
             '指标结果为有效输出点均值；当前原型只接受单条输入。', '',
             '|指标|结果|有效点数|归属|', '|---|---|---|---|']
    refs = []
    for metric, item in context['metrics'].items():
        cid = item['valid_count_fact_id']; refs.append(cid)
        if item['value_fact_id']:
            fid = item['value_fact_id']; refs.append(fid)
            unit = '无量纲' if item['unit'] == '1' else item['unit']
            value = f"{item['value']:.6g} {unit} [{fid}]"
        else:
            value = '无法获得有效值（不是测得零值）'
        origin = '实测输入' if metric == 'power_kW' else '测量派生'
        lines.append(f"|{NAMES[metric]}|{value}|{item['valid_count']} 条 [{cid}]|{origin}|")
    lines += ['', '能量平衡偏差 = 冷凝热 − 制冷量 − 输入功率，单位 kW。']
    balance = context['metrics']['energy_balance_error_kW']['value']
    if balance is None:
        lines.append('本次残差不可得，不能判断其正负或能量是否闭合。')
    elif balance < 0:
        lines.append('本次负号表示冷凝热小于制冷量与输入功率之和；不表示能量已经闭合。')
    elif balance > 0:
        lines.append('本次正号表示冷凝热大于制冷量与输入功率之和。')
    else:
        lines.append('本次记录的代数残差为零；仍须核对测量边界与不确定度。')
    lines.append('残差不能直接解释为效率损失、故障类型或故障概率。')
    evidence = context['evidence']
    for metric, item in context['metrics'].items():
        if item['value'] is not None:
            continue
        fields = sorted(set(item['unmapped_fields'] + item['missing_internal_fields']))
        desc = '、'.join(FIELDS[f][0] + '（' + f + '）' for f in fields)
        lines.append(f"{NAMES[metric]}：" + (f'应核查 {desc} 的映射和有效测量。' if desc else '工具未给出足够的不可得原因，需核对源记录；不能自行判定传感器损坏。'))
    lines += ['冷冻水出水设定值不能替代出水实测温度；冷却侧流量不能替代冷冻侧流量。',
              '本次执行物理计算，未执行动态仿真；默认模型计数不证明模型适用性。']
    if 'units' in candidate['answer_topics']:
        lines += ['', '|内部字段含义|实际映射的源列|源单位配置|内部字段|内部单位|', '|---|---|---|---|---|']
        for field, meta in evidence['fields'].items():
            key = 'power_unit' if field == 'P_W' else ('flow_unit' if 'flow' in field else 'temperature_unit')
            source = meta['source_column'] if meta['source_column'] is not None else '未映射到现有列'
            lines.append('|'+ '|'.join(_escaped(v) for v in (meta['meaning'], source, evidence['source_units'][key], field, meta['internal_unit'])) + '|')
        lines += ['', evidence['unit_rules']]
    if 'data_update_workflow' in candidate['answer_topics']:
        lines.append('补充或修改测量后重新上传，选择新数据集并新建对话，再执行物理分析；不能声称当前结果已包含后来补充的测量。')
    if context['analysis_status'] == 'partial':
        lines.append('工具状态为 partial；警告和缺测须分别核对，不能直接等同所有指标都缺测。')
    if context['warnings']:
        lines.append('工具警告代码：' + '、'.join(_escaped(w['code']) for w in context['warnings']) + '。')
    lines += ['', '所选解释重点：' + '、'.join(NAMES[m] for m in candidate['focus_metrics']) + '。']
    if candidate['followup_check_ids']:
        lines += ['', '建议核查：']
        lines += ['- ' + context['allowed_checks'][cid] for cid in candidate['followup_check_ids']]
    return {'trusted_markdown': '\n'.join(lines) + '\n', 'rendered_fact_ids': refs,
            'context_sha256': context['source_sha256'], 'candidate_schema_valid': True,
            'question_relevance_review': 'pending', 'domain_accuracy': None,
            'explanation_review': {'status': 'pending', 'text': candidate['explanation_draft'],
                                   'included_in_trusted_block': False}}
