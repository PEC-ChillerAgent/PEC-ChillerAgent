"""Offline-only finite guard correction; not semantic verification or release.

Keep v1/v2 immutable. Recheck each fault predicate locally, rather than exempting
an entire sentence containing a negation. Detect a shared residual denominator.
"""
import re

from chiller_student.explanation_protocol import strict_json
from chiller_student.typed_physics_claims_v2 import check_claims as prior_check

VERSION = 'typed_physics_claims_v3_local_negation_and_shared_denominator_offline_r2'
FAULT = re.compile(r'(?:已|已经)(?:确认|确诊).{0,10}故障')
NEGATED = re.compile(r'不表示|不意味着|不代表|不是|并非|不等于|没有|尚未|未曾|未能|不能|不应|不可|是否|错误写法|假设|如果')
RESIDUAL_DENOMINATOR = re.compile(r'(?:残差|能量平衡偏差|(?<![A-Za-z0-9_])R(?![A-Za-z0-9_]))[^。；;\n，,]{0,16}分母', re.I)


def check_claims(raw, request):
    previous = prior_check(raw, request)
    text = strict_json(raw)['answer']
    issues = [i for i in previous['issues'] if i != 'UNSUPPORTED_FAULT_DIAGNOSIS']
    if 'POWER_INDICATOR_IS_NOT_A_RATIO' in issues:
        # The subject in "COP以输入功率为分母" is COP. It does not claim
        # that the measured power indicator itself needs a denominator.
        bad_power_subject = False
        for clause in re.split('[。；;\n，,]', text):
            pattern = r'(?:功率指标|输入功率)(?:本身)?(?:的|需要|是|为).{0,6}分母'
            for match in re.finditer(pattern, clause):
                prefix = clause[:match.start()]
                cop_subject = re.search(r'COP(?:须|需|应|需要|必须)?以(?:有效正|有效|正)?$', prefix, re.I)
                if not cop_subject:
                    bad_power_subject = True
        if not bad_power_subject:
            issues.remove('POWER_INDICATOR_IS_NOT_A_RATIO')
    for clause in re.split(r'[。；;\n，,]|但是|但|然而', text):
        for match in FAULT.finditer(clause):
            if not NEGATED.search(clause[:match.start()]):
                issues.append('UNSUPPORTED_FAULT_DIAGNOSIS')
        for match in RESIDUAL_DENOMINATOR.finditer(clause):
            prefix = clause[:match.start()]
            if NEGATED.search(prefix) or re.search(r'没有|无分|不含|不需要|不以|不因', match.group()):
                continue
            # A trailing explicit denial also negates the proposition itself.
            if re.match(r'\s*(?:的说法)?(?:不成立|是错误|并不存在)', clause[match.end():]):
                continue
            issues.append('RESIDUAL_IS_NOT_A_RATIO')
    e = strict_json(request['messages'][1]['content'])['tool_evidence']
    state = e.get('input_conditions', {}).get('fields', {}).get('P_W', {}).get('state')
    if state is not None and state != 'unavailable':
        for clause in re.split('[。；;\n，,]', text):
            for match in re.finditer(r'(?:缺少|缺失|缺测)\s*P_W(?![A-Za-z0-9_])', clause):
                # "COP不可计算，因为缺少P_W" negates computability, not the
                # following missing-power assertion. Do not exempt that cause.
                prefix = clause[:match.start()]
                negated_missing = re.search(r'不是|并非|没有|不能(?:说|认为|声称|认定)|不应(?:说|认为|声称)|假设|如果|若|是否', prefix)
                if not negated_missing:
                    issues.append('OBSERVED_POWER_NOT_MISSING_CANONICAL_FIELD')
    issues = list(dict.fromkeys(issues))
    return {**previous, 'check_version': VERSION, 'issues': issues,
            'passed_known_checks': not issues, 'previous_v2_issues': previous['issues'],
            'model_text_repaired': False, 'exhaustive_semantic_verification': False,
            'task_completeness': 'pending_editorial_review', 'domain_accuracy': None}
