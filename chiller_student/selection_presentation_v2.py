"""Code-owned report limits; preserves raw model choices and historical scores.

V1 remains frozen for all previous experiments. This presentation revision is
not a new model, a selection repair, or evidence of improved model accuracy.
"""
from copy import deepcopy
from chiller_student.selection_presentation import present_selection

DIAGNOSTIC_LIMIT = ('作故障判断还需核对传感器测量不确定度、允许误差、测量边界和匹配工况基准。'
                    '缺少这些诊断证据不等于缺少性能计算输入；仅凭本次能量残差不能确诊故障或判断严重程度。')
CONDENSER_FLOW_LIMIT = ('冷冻侧流量不能直接替代冷却侧流量；需要补充或核对冷却侧的有效流量测量。')


def present_selection_v2(context, candidate):
    prior = present_selection(context, candidate)
    result = deepcopy(prior)
    additions = []
    for section in result['sections']:
        if section['topic'] == 'energy_balance':
            section['markdown'] += '\n\n' + DIAGNOSTIC_LIMIT
            additions.append({'policy_id':'diagnostic_evidence_limits_v1','topic':'energy_balance',
                              'owner':'deterministic_code','text':DIAGNOSTIC_LIMIT})
        if section['topic'] == 'missing_inputs':
            missing = {f for m in context['metrics'].values() if m['value'] is None
                       for f in m['unmapped_fields'] + m['missing_internal_fields']}
            if 'cond_flow_kg_s' in missing:
                section['markdown'] += '\n\n' + CONDENSER_FLOW_LIMIT
                additions.append({'policy_id':'condenser_flow_non_substitution_v1','topic':'missing_inputs',
                                  'owner':'deterministic_code','text':CONDENSER_FLOW_LIMIT})
    answer = '\n\n'.join('### '+s['title']+'\n\n'+s['markdown'] for s in result['sections'])
    if result['followup_checks']:
        from chiller_student.structured_physics import _escaped
        answer += '\n\n### 建议核查\n\n' + '\n'.join('- '+_escaped(c['text']) for c in result['followup_checks'])
    result['answer_markdown'] = answer + '\n'
    result.update(presentation_version='physics_selection_presentation_v2',
                  code_added_boundaries=additions, model_selection_repaired=False,
                  original_model_selection=deepcopy(candidate), production_integrated=False,
                  limits=('Presentation-only code revision. Diagnostic limits are appended only when energy_balance '
                          'was selected. Missing topics/check IDs remain missing; no semantic completeness guarantee. '
                          'No change to weights, requests, original scores, numeric values or formulas.'))
    return result
