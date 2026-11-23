"""Versioned missing-claim scope fix; original answers and v1 stay frozen.

An introductory condition such as '缺少TCO时，输入功率可得' does not
assert that the later available power input is missing. Other known checks
are inherited unchanged. This remains a finite guard, not semantic proof.
"""
import re
from chiller_student.explanation_protocol import strict_json
from chiller_student.explanation_consistency import FIELD_PATTERNS,check_consistency as check_v1

VERSION='physics_explanation_consistency_v2_clause_scope'
_SKIP=re.compile(r'不能|不可|不应|若|如果|假设|是否|核查|核对|没有.{0,5}缺')
_MISSING=re.compile(r'缺少|缺失|缺测')
_TEMPORAL=re.compile(r'(?:时|的情况下)\s*[，,]')
_POSITIVE=re.compile(r'(?<!不)(?:可得|可用|已提供|已具备|均已具备|均已提供)')

def _asserted_tail(text):
    """End the missing list at a conditional or a positive availability clause."""
    end=len(text)
    temporal=_TEMPORAL.search(text)
    if temporal:end=min(end,temporal.start())
    for comma in re.finditer(r'[，,]',text):
        # Do not split comma-separated missing-field lists. A following clause
        # must actually state availability, without another missing predicate.
        tail=re.split(r'[，,]',text[comma.end():],maxsplit=1)[0]
        positive=_POSITIVE.search(tail)
        if positive and not _MISSING.search(tail[:positive.end()]):end=min(end,comma.start())
    return text[:end]

def missing_claim_issues(answer,missing):
    issues=[]
    for clause in re.split('[。；;\n]',answer):
        if _SKIP.search(clause):continue
        for marker in _MISSING.finditer(clause):
            asserted=_asserted_tail(clause[marker.end():])
            for field,pattern in FIELD_PATTERNS.items():
                if field not in missing and re.search(pattern,asserted):issues.append('MISSING_FIELD_CONTRADICTION:'+field)
        # A later affirmative predicate still counts after the conditional:
        # '缺TCO时，输入功率也缺失' must not be exempted by the scope fix.
        for field,pattern in FIELD_PATTERNS.items():
            suffix=r'\s*(?:(?:当前|本次|实际|也|仍|均|都|则|确实|为|是)\s*){0,3}(?:缺少|缺失|缺测)'
            if field not in missing and re.search(pattern+suffix,clause):issues.append('MISSING_FIELD_CONTRADICTION:'+field)
    return list(dict.fromkeys(issues))

def check_consistency(raw,request):
    original=check_v1(raw,request)
    answer=strict_json(raw)['answer'];payload=strict_json(request['messages'][1]['content'])
    missing={f for m in payload['tool_evidence']['readable_summary']['metrics'].values() for f in m['currently_missing_fields']}
    retained=[i for i in original['issues'] if not i.startswith('MISSING_FIELD_CONTRADICTION:')]
    issues=list(dict.fromkeys(retained+missing_claim_issues(answer,missing)))
    return {**original,'passed_known_checks':not issues,'issues':issues,'check_version':VERSION,
            'legacy_v1_issues':original['issues'],'model_text_repaired':False}
