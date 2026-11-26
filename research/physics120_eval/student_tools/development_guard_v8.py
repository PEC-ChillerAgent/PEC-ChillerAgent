"""Offline guard experiment with independent diagnostics and no model calls."""
import re
from types import SimpleNamespace

from student_tools.explanation_protocol import strict_json, validate_explanation
from student_tools.explanation_number_gate_v8 import render_answer, VERSION as NUMBER_VERSION
from student_tools.typed_physics_claims_v3 import check_claims, VERSION as CLAIM_VERSION
from student_tools.explanation_quality import check_repetition

VERSION = 'offline_development_guard_v8'


def score(completion, request, required_fact_ids):
    facts = strict_json(request['messages'][1]['content'])['tool_evidence']['facts']
    result = {'version': VERSION, 'number_gate_version': NUMBER_VERSION,
              'claim_gate_version': CLAIM_VERSION, 'protocol_passed': False,
              'required_fact_coverage_passed': False, 'finite_claim_passed': False,
              'repetition_passed': False, 'finish_reason_stop': completion['finish_reason'] == 'stop',
              'diagnostic_passed': False, 'issues': {}, 'model_text_repaired': False,
              'actual_task_success': None, 'domain_accuracy': None, 'offline_only': True}
    try:
        parsed = strict_json(completion['content'])
        if not isinstance(parsed, dict) or set(parsed) != {'answer'} or not isinstance(parsed['answer'], str):
            raise ValueError('Only string answer field allowed')
    except (ValueError, KeyError, TypeError) as error:
        result['issues']['envelope'] = str(error)
        return result
    # Coverage is independent of number/claim gates, not silently set to false
    # merely because another check rejected a mathematical zero or other prose.
    cited = set(re.findall(r'\{\{fact:(F\d+)\}\}', parsed['answer']))
    result['required_fact_coverage_passed'] = set(required_fact_ids) <= cited
    result['missing_required_fact_ids'] = sorted(set(required_fact_ids) - cited)
    try:
        validate_explanation(completion['content'], [SimpleNamespace(**f) for f in facts], renderer=render_answer)
        result['protocol_passed'] = True
    except (ValueError, KeyError, TypeError) as error:
        result['issues']['protocol'] = str(error)
    try:
        checked = check_claims(completion['content'], request)
        result['finite_claim_passed'] = checked['passed_known_checks']
        result['issues']['finite_claims'] = checked['issues']
    except (ValueError, KeyError, TypeError) as error:
        result['issues']['finite_claims'] = [str(error)]
    result['repetition_passed'] = check_repetition(parsed['answer'])['passed_repetition_check']
    result['diagnostic_passed'] = all(result[k] for k in (
        'protocol_passed', 'required_fact_coverage_passed', 'finite_claim_passed',
        'repetition_passed', 'finish_reason_stop'))
    return result
