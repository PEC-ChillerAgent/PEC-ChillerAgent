"""Frozen inputs and independent protocol/coverage reporting for base inference."""
import json
from pathlib import Path
import re
import statistics
from types import SimpleNamespace

from student_tools.explanation_protocol import VERSION, SYSTEM, strict_json, validate_explanation
from student_tools.native_sft_data import require, token_digest
from student_tools.paired_support import sha, save, decode_completion

PURPOSE = 'physics_evidence_explanation_base12_v1'
TOKEN_LIMIT = 2048


def canonical_hash(value):
    import hashlib
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def verify_bundle(path):
    path = Path(path).resolve()
    root = path.parent
    manifest = strict_json(path.read_bytes())
    require(manifest['purpose'] == PURPOSE and manifest['contract_version'] == VERSION, 'Wrong package')
    require(manifest['enable_thinking'] is False and manifest['effective_template_tools'] is None, 'Template changed')
    require(len(manifest['files']) == len({x['path'] for x in manifest['files']}), 'Duplicate package files')
    for entry in manifest['files']:
        file = (root / entry['path']).resolve()
        require(file.is_relative_to(root) and sha(file) == entry['sha256'], 'Package changed: ' + entry['path'])
    rows = [strict_json(line) for line in (root / 'data/model_inputs.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    judges = [strict_json(line) for line in (root / 'data/judge_only.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    require(len(rows) == len(judges) == 12, 'Expected twelve cases')
    ids = [r['case_id'] for r in rows]
    lookup = {j['case_id']: j for j in judges}
    require(len(set(ids)) == len(lookup) == 12 and set(ids) == set(lookup), 'Case IDs differ')
    require(ids == [f'explanation_dev_{i:03d}' for i in range(1, 13)], 'Unexpected case order or identity')
    for row in rows:
        require(set(row) == {'case_id', 'family', 'contract_version', 'messages', 'tools', 'request_sha256'}, 'Targets/metadata in model row')
        require(row['tools'] is None and row['contract_version'] == VERSION, 'Task changed')
        messages = row['messages']
        require(len(messages) == 2 and messages[0] == {'role': 'system', 'content': SYSTEM}
                and messages[1]['role'] == 'user' and set(messages[1]) == {'role', 'content'}, 'Two frozen messages required')
        payload = strict_json(messages[1]['content'])
        require(set(payload) == {'contract_version', 'question', 'tool_evidence', 'response_schema'}, 'Unexpected input fields')
        require(payload['contract_version'] == VERSION and isinstance(payload['question'], str) and payload['question'].strip(), 'Invalid question')
        require(canonical_hash({'messages': messages, 'tools': None}) == row['request_sha256']
                == manifest['request_sha256'][row['case_id']], 'Prompt changed')
        facts = payload['tool_evidence']['facts']
        require(facts == lookup[row['case_id']]['facts'], 'Input fact table differs from judge fact table')
        fact_ids = {f['fact_id'] for f in facts}
        require(len(fact_ids) == len(facts) and set(lookup[row['case_id']]['required_fact_ids']) <= fact_ids, 'Unknown or duplicate facts')
    return root, manifest, rows, lookup


def encode_prompt(tokenizer, row, reference):
    ids = tokenizer.apply_chat_template(row['messages'], tools=None, enable_thinking=False,
                                       tokenize=True, add_generation_prompt=True)
    require(len(ids) == reference['prompt_tokens'] and token_digest(ids) == reference['token_ids_sha256'], 'Native prompt changed')
    require(len(ids) + TOKEN_LIMIT <= 8192, 'Context too long; no truncation')
    return ids


def score_completion(completion, judge, renderer):
    require(completion['completion_token_ids_sha256'] == token_digest(completion['completion_token_ids']), 'Completion changed')
    result = {'protocol_passed': False, 'required_fact_coverage_passed': False,
              'cited_required_fact_count': 0, 'required_fact_count': len(judge['required_fact_ids']),
              'truncated': completion['finish_reason'] == 'length', 'semantic_review': 'pending',
              'domain_accuracy': None, 'source_entailment_verified': False}
    try:
        parsed = strict_json(completion['content'])
        answer = parsed.get('answer') if isinstance(parsed, dict) else None
        cited = set(re.findall(r'\{\{fact:(F\d+)\}\}', answer)) if isinstance(answer, str) else set()
        result['cited_required_fact_count'] = len(cited & set(judge['required_fact_ids']))
        result['required_fact_coverage_passed'] = set(judge['required_fact_ids']) <= cited
        require(completion['finish_reason'] == 'stop', 'Completion did not stop normally')
        report = validate_explanation(completion['content'], [SimpleNamespace(**f) for f in judge['facts']], renderer=renderer)
        result.update(protocol_passed=True, rendered_answer=report['rendered_answer'], cited_fact_ids=report['cited_fact_ids'])
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        result['protocol_error'] = str(exc)
    result['protocol_and_coverage_passed'] = result['protocol_passed'] and result['required_fact_coverage_passed']
    return result


def summarize(records, expected):
    require(len(records) == len({r['case_id'] for r in records}), 'Duplicate results')
    require({r['case_id'] for r in records} <= set(expected), 'Unexpected results')
    n = len(records)
    return {'complete': n == len(expected), 'answers': n, 'expected_answers': len(expected),
            'protocol_passes': sum(r['score']['protocol_passed'] for r in records),
            'required_fact_coverage_passes': sum(r['score']['required_fact_coverage_passed'] for r in records),
            'cases_requiring_numeric_fact_references': sum(r['score']['required_fact_count'] > 0 for r in records),
            'coverage_passes_among_cases_requiring_numeric_facts': sum(r['score']['required_fact_count'] > 0 and r['score']['required_fact_coverage_passed'] for r in records),
            'protocol_and_coverage_passes': sum(r['score']['protocol_and_coverage_passed'] for r in records),
            'truncated_completions': sum(r['score']['truncated'] for r in records),
            'mean_generation_seconds': statistics.mean(r['generation_seconds'] for r in records) if n else None,
            'training_run': False, 'domain_accuracy': None, 'semantic_review': 'pending',
            'independent_test': False, 'source_entailment_verified': False,
            'teacher_calls': 0, 'retries': 0, 'fallback': False,
            'meaning': 'Format/citation coverage only; source overlap with past development. Not factual accuracy.'}
