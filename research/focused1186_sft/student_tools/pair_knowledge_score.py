"""Fixed-document development baseline. No teacher, training, retries or fallback.

Citation presence is scored independently of completion format. Neither is a
semantic accuracy score. Only local HTTP endpoints are accepted.
"""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

CITATION = re.compile(r'\[([A-Za-z][A-Za-z0-9_-]*)\]')


def load_rows(path):
    return [json.loads(s) for s in Path(path).read_text(encoding='utf-8-sig').splitlines() if s.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def endpoint_url(value):
    p = urllib.parse.urlsplit(value)
    require(p.scheme == 'http' and p.hostname in {'127.0.0.1', 'localhost', '::1'}
            and not (p.username or p.password or p.query or p.fragment)
            and p.path.rstrip('/') == '/v1', 'Use a local http loopback /v1 endpoint; no URL credentials')
    return value.rstrip('/')


def request_json(url, api_key, body=None):
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = 'Bearer ' + api_key
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8'), headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=180) as r:
        return json.load(r)


def build_request(row, model, max_tokens):
    # Allowlist: source metadata, judge rubric and targets never enter the body.
    return {'model': model, 'messages': row['request']['messages'], 'tools': row['request']['tools'],
            'tool_choice': 'none', 'stream': False, 'max_tokens': max_tokens,
            'temperature': 0, 'top_p': 1, 'seed': 42,
            'chat_template_kwargs': {'enable_thinking': False}}


def validate_files(inputs, judges):
    rows, gold = load_rows(inputs), load_rows(judges)
    ids = [r['sample_id'] for r in rows]
    require(ids and len(set(ids)) == len(ids), 'Empty/duplicate input IDs')
    require(all(re.fullmatch(r'knowledge_K\d{3}', s) for s in ids), 'Invalid sample ID')
    require(len(gold) == len(rows) and {g['sample_id'] for g in gold} == set(ids), 'Judge/input IDs mismatch')
    lookup = {g['sample_id']: g for g in gold}
    for row in rows:
        req = row['request']
        require(set(req) == {'messages', 'tools'}, 'Unexpected request fields')
        messages = req['messages']
        require([m['role'] for m in messages] == ['system', 'user'], 'No assistant targets/tool results allowed in document input')
        require(all(set(m) == {'role', 'content'} and isinstance(m['content'], str) and m['content'].strip() for m in messages), 'Unexpected/empty message')
        require(isinstance(req['tools'], list), 'Tool definition context missing')
        binding = json.loads(messages[0]['content'].rsplit('\n', 1)[-1])
        require(binding.get('dataset_id') is None and binding.get('asset_id') is None and not binding.get('facts')
                and not binding.get('simulation_configured') and binding.get('simulation') is None, 'Knowledge task must not bind device data')
        expected = lookup[row['sample_id']]['required_evidence_ids']
        require(expected and len(set(expected)) == len(expected), 'Empty/duplicate evidence IDs')
        require(all(re.fullmatch(r'[A-Z][A-Z0-9_]*', x) and '['+x+']' in messages[1]['content'] for x in expected), 'Required evidence not in input')
    return rows, lookup


def score_response(response, judge):
    """Structural diagnostics only; evidence ID presence is NOT entailment."""
    errors, text, message, finish = [], '', {}, None
    try:
        choices = response['choices']
        require(isinstance(choices, list) and len(choices) == 1, 'Expected one completion')
        choice = choices[0]
        finish = choice.get('finish_reason')
        message = choice['message']
        require(isinstance(message, dict), 'Invalid message')
        content = message.get('content')
        if isinstance(content, str):
            text = content
        else:
            errors.append('Non-text answer')
        if message.get('role') != 'assistant': errors.append('Unexpected response role')
        if finish != 'stop': errors.append('Incomplete/non-stop completion')
        if not text.strip(): errors.append('Empty answer')
        if message.get('tool_calls'): errors.append('Unexpected tool calls')
        if message.get('reasoning_content') or '<think>' in text or '</think>' in text:
            errors.append('Thinking content in non-thinking task')
        if '{{fact:' in text: errors.append('Device fact placeholder in unbound document task')
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        errors.append(str(exc))
    # Always evaluate citations, including when finish_reason is length or other
    # structural checks failed. Do not repeat the old physics scorer's early exit.
    cited = set(CITATION.findall(text))
    required = set(judge['required_evidence_ids'])
    missing, unknown = sorted(required - cited), sorted(cited - required)
    return {'response_format_passed': not errors, 'format_errors': errors,
            'finish_reason': finish, 'has_unexpected_tool_calls': bool(message.get('tool_calls')) if isinstance(message, dict) else False,
            'required_evidence_count': len(required), 'required_evidence_cited': len(cited & required),
            'cited_evidence_ids': sorted(cited), 'missing_evidence_ids': missing, 'unknown_bracket_ids': unknown,
            'all_required_evidence_ids_cited': not missing,
            'citation_check_passed': not missing and not unknown,
            'knowledge_format_passed': not errors and not missing and not unknown,
            'domain_accuracy': None, 'semantic_review': 'pending; reference presence does not prove support for a claim'}


def verify_bundle(path):
    manifest = json.loads(Path(path).read_text(encoding='utf-8'))
    root = Path(path).resolve().parent
    for entry in manifest['files']:
        target = (root / entry['path']).resolve()
        require(target.is_relative_to(root), 'Bundle path escapes root')
        require(sha(target) == entry['sha256'], 'Frozen package hash mismatch: ' + entry['path'])
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--inputs', type=Path, default=Path('data/model_inputs.jsonl'))
    ap.add_argument('--judges', type=Path, default=Path('data/judge_only.jsonl'))
    ap.add_argument('--bundle', type=Path, default=Path('bundle_manifest.json'))
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--checkpoint', required=True, help='Declared path/revision, not automatic weight verification')
    ap.add_argument('--model', default='chiller-student-base')
    ap.add_argument('--base-url', default='http://127.0.0.1:8000/v1')
    ap.add_argument('--max-tokens', type=int, default=2048)
    ap.add_argument('--limit', type=int)
    ap.add_argument('--stage', choices=['baseline', 'post_sft'], default='baseline')
    ap.add_argument('--run', action='store_true', help='Omit to validate only, no HTTP')
    args = ap.parse_args()
    url = endpoint_url(args.base_url)
    bundle = verify_bundle(args.bundle)
    require(sha(args.inputs) == bundle['inputs_sha256'] and sha(args.judges) == bundle['judges_sha256'], 'Inputs/judges differ from frozen package')
    rows, judges = validate_files(args.inputs, args.judges)
    require(0 < args.max_tokens <= 2048 and (args.limit is None or args.limit > 0), 'Invalid token limit or case limit')
    if args.limit: rows = rows[:args.limit]
    require(not args.output.exists(), 'Use a NEW output directory; retain old attempts')
    args.output.mkdir(parents=True)
    manifest = {'stage': args.stage, 'test_scope': 'provided_document_qa_development_not_heldout',
                'execution_requested': args.run, 'started_utc': datetime.now(timezone.utc).isoformat(),
                'model_alias': args.model, 'checkpoint_declared': args.checkpoint, 'checkpoint_weights_auto_verified': False,
                'python': platform.python_version(), 'platform': platform.platform(), 'endpoint': url,
                'inputs_sha256': sha(args.inputs), 'judges_sha256': sha(args.judges), 'bundle_sha256': sha(args.bundle),
                'runner_sha256': sha(__file__), 'case_count': len(rows), 'max_output_tokens': args.max_tokens,
                'temperature': 0, 'top_p': 1, 'seed': 42, 'thinking': False,
                'automatic_retries': 0, 'fallback': False, 'concurrency': 1,
                'tool_choice': 'none', 'contains_target_answers': False}
    save(args.output / 'run_manifest.json', manifest)
    if not args.run:
        save(args.output / 'dry_run.json', {'passed': True, 'requests_prepared': len(rows), 'model_calls': 0})
        print(f'Dry-run passed: {len(rows)} knowledge inputs; no model called.')
        return
    api_key = os.environ.get('STUDENT_API_KEY', '')
    try:
        models = request_json(url + '/models', api_key)
        save(args.output / 'server_models.json', models)
        matches = [m for m in models.get('data', []) if m['id'] == args.model]
        require(len(matches) == 1, 'Requested model alias not listed uniquely')
        context = matches[0].get('max_model_len')
        if context is not None:
            require(context >= bundle['max_native_prompt_tokens'] + args.max_tokens, 'Model context too short; do not truncate frozen inputs')
    except Exception as exc:
        save(args.output / 'startup_error.json', {'error': str(exc), 'model_calls': 0})
        raise
    results = []
    for row in rows:
        sid = row['sample_id']; body = build_request(row, args.model, args.max_tokens)
        record = {'sample_id': sid, 'request': body, 'http_success': False}
        start = time.perf_counter()
        try:
            response = request_json(url + '/chat/completions', api_key, body)
            record.update(http_success=True, response=response, score=score_response(response, judges[sid]))
        except urllib.error.HTTPError as exc:
            record.update(error_type='http', http_status=exc.code, error_body=exc.read().decode('utf-8', errors='replace'))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            record.update(error_type=type(exc).__name__, error=str(exc))
        record['latency_seconds'] = time.perf_counter() - start
        save(args.output / (sid + '.json'), record)
        results.append(record)
        print(f"{sid}: HTTP={record['http_success']}, knowledge_format={record.get('score', {}).get('knowledge_format_passed', False)}", flush=True)
    ok = [r for r in results if r['http_success']]
    latency = sorted(r['latency_seconds'] for r in ok)
    def count(key): return sum(bool(r.get('score', {}).get(key)) for r in results)
    summary = {'attempted': len(results), 'http_successes': len(ok),
               'response_format_passes': count('response_format_passed'),
               'required_evidence_id_coverage_passes': count('all_required_evidence_ids_cited'),
               'citation_check_passes': count('citation_check_passed'),
               'knowledge_format_passes': count('knowledge_format_passed'),
               'required_evidence_cited': sum(r.get('score', {}).get('required_evidence_cited', 0) for r in results),
               'required_evidence_total': sum(len(judges[r['sample_id']]['required_evidence_ids']) for r in results),
               'truncated_completions': sum(r.get('score', {}).get('finish_reason') == 'length' for r in results),
               'mean_latency_seconds': statistics.mean(latency) if latency else None,
               'p95_latency_seconds_nearest_rank': latency[math.ceil(.95*len(latency))-1] if latency else None,
               'domain_accuracy': None, 'domain_review': 'pending; citations do not prove entailment, factual accuracy or scope compliance',
               'tool_selection_tested': False, 'retrieval_tested': False, 'live_physics_execution_tested': False,
               'independent_test': False, 'retries': 0, 'fallback': False}
    save(args.output / 'summary.json', summary)
    with (args.output / '人工内容审核.csv').open('x', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['sample_id', 'title', 'knowledge_format_passed', '主要结论有原文支持', '型号与适用条件', '原文与推论区分', '无虚构设备结果', '内容结论', '备注'])
        for r in results:
            writer.writerow([r['sample_id'], judges[r['sample_id']]['title'], r.get('score', {}).get('knowledge_format_passed', False), '', '', '', '', '', ''])
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
