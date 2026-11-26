"""Shared data isolation and scoring for one continued selection/explanation LoRA."""
import copy
import json
from pathlib import Path
import random
import statistics
from types import SimpleNamespace

from student_tools.native_sft_data import require, token_digest
from student_tools.paired_support import sha, save, decode_completion
from student_tools.explanation_protocol import strict_json, validate_explanation
from student_tools.explanation_baseline_support import canonical_hash, score_completion

PURPOSE = 'selection80_continued_joint_physics_sft_v1'
WORKFLOW = {
    'version': 'chiller_project_workflow_v1',
    'facts': [
        '当前数据集和已保存的运行结果不会随补录自动修改。',
        '补录后上传或录入新数据，确认列映射和单位，选择新数据并新建对话，重新执行计算。',
        '新计算产生新的运行记录；历史报告保留原记录，不能当成已自动更新。',
    ],
}


def explanation_renderer():
    try:
        from student_tools.explanation_project_reporting import render_answer
    except ModuleNotFoundError as exc:
        if exc.name != 'student_tools.explanation_project_reporting': raise
        from energy_agent.agents.reporting import render_answer
    return render_answer


def with_workflow(request):
    """Supply application behavior as context, never as a hidden gold answer."""
    request = copy.deepcopy(request)
    payload = strict_json(request['messages'][1]['content'])
    require('tool_evidence' in payload and 'project_workflow' not in payload['tool_evidence'], 'Wrong explanation request')
    payload['tool_evidence']['project_workflow'] = copy.deepcopy(WORKFLOW)
    request['messages'][1]['content'] = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    return request


def selection_value(raw, request):
    payload = strict_json(request['messages'][1]['content'])
    candidate = strict_json(raw)
    require(isinstance(candidate, dict) and set(candidate) == {'schema_version', 'answer_topics', 'followup_check_ids'}, 'Selection fields differ')
    require(candidate['schema_version'] == 'physics_selection_v1', 'Selection version differs')
    for key, allowed, minimum in [('answer_topics', payload['allowed_topics'], 1),
                                  ('followup_check_ids', payload['allowed_checks'], 0)]:
        seq = candidate[key]
        require(isinstance(seq, list) and minimum <= len(seq) <= min(3, len(allowed)), 'Selection length differs')
        require(all(isinstance(x, str) and x in allowed for x in seq), 'Unknown selection')
        require(len(seq) == len(set(seq)), 'Duplicate selection')
    return candidate


def score_selection(completion, row, judge):
    result = {'protocol_passed': False, 'selection_gate_passed': False, 'domain_accuracy': None}
    try:
        value = selection_value(completion['content'], row['request'])
        stop = completion['finish_reason'] == 'stop'
        missing = {k: sorted(set(judge['required_' + k]) - set(value[k])) for k in ('answer_topics', 'followup_check_ids')}
        extra = {k: sorted(set(value[k]) - set(judge['allowed_' + k])) for k in ('answer_topics', 'followup_check_ids')}
        result.update(protocol_passed=stop, candidate=value, missing_required=missing, extra=extra,
                      selection_gate_passed=stop and not any(missing.values()) and not any(extra.values()))
    except (ValueError, TypeError, KeyError) as exc:
        result['protocol_error'] = str(exc)
    return result


def training_order(rows, seed=42):
    ids = sorted(r['sample_id'] for r in rows)
    require(len(ids) == len(set(ids)) and ids, 'Training IDs must be unique')
    random.Random(seed).shuffle(ids)
    return ids


class TraceCollator:
    def __init__(self, collator, order, epochs, path):
        self.collator, self.order, self.epochs = collator, list(order), epochs
        self.expected = self.order * epochs
        self.path, self.seen = Path(path), []

    def __call__(self, features):
        ids = [f['sample_id'] for f in features]
        start = len(self.seen)
        require(len(ids) == 1 and ids == self.expected[start:start + 1], 'Unknown/dev/repeated/out-of-order training sample')
        batch = self.collator(features)
        self.seen.extend(ids)
        with self.path.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'visit': start + 1, 'epoch': start // len(self.order) + 1, 'sample_id': ids[0]}) + '\n')
        return batch


def verify_package(path):
    path = Path(path).resolve()
    root, manifest = path.parent, strict_json(path.read_bytes())
    require(manifest['purpose'] == PURPOSE and manifest['environment_spec_hash'] == '5befcb78', 'Wrong package/environment')
    require(len(manifest['files']) == len({e['path'] for e in manifest['files']}), 'Duplicate manifest file')
    for entry in manifest['files']:
        file = (root / entry['path']).resolve()
        require(file.is_relative_to(root) and sha(file) == entry['sha256'], 'Package drift: ' + entry['path'])
    load = lambda name: [strict_json(l) for l in (root / name).read_text(encoding='utf-8').splitlines() if l.strip()]
    train = load('data/train.messages.jsonl')
    evaluation = load('data/eval_inputs.jsonl')
    judges = load('data/judge_only.jsonl')
    plan = strict_json((root / 'training_plan.json').read_bytes())
    require(plan['purpose'] == PURPOSE and plan['epochs'] == 2 and plan['learning_rate'] == 2e-5
            and plan['resume_optimizer'] is False and plan['initialization'] == 'verified_selection80_adapter'
            and plan['batch_size'] == plan['gradient_accumulation_steps'] == 1, 'Plan changed')
    require(len(train) == plan['train_rows'] and plan['optimizer_steps'] == len(train) * 2, 'Training size differs')
    require(len(evaluation) == plan['evaluation_cases'] == len(judges), 'Eval size differs')
    require(len({r['sample_id'] for r in train}) == len(train), 'Repeated training ID')
    require(len({r['case_id'] for r in evaluation}) == len(evaluation), 'Repeated eval ID')
    lookup = {r['case_id']: r for r in judges}
    require(set(lookup) == {r['case_id'] for r in evaluation}, 'Eval/judge IDs differ')
    excluded = set(plan['excluded_parent_source_record_ids'])
    require(not excluded & {r['parent_source_record_id'] for r in train}, 'Held parent entered new gradients')
    hashes = []
    for row in train:
        require(row['assigned_split'] == 'train' and row['training_approved'] is True, 'Unapproved row')
        require(row['family'] in ('selection', 'explanation'), 'Unknown task family')
        require([m['role'] for m in row['messages']] == ['system', 'user', 'assistant'], 'Unexpected message history')
        request = {'messages': row['messages'][:-1], 'tools': None}
        hashes.append(canonical_hash(request))
        require(hashes[-1] == row['request_sha256'], 'Training request changed')
        answer = row['messages'][-1]['content']
        if row['family'] == 'selection':
            selection_value(answer, request)
        else:
            facts = strict_json(request['messages'][1]['content'])['tool_evidence']['facts']
            validate_explanation(answer, [SimpleNamespace(**f) for f in facts], renderer=explanation_renderer())
    require(len(hashes) == len(set(hashes)), 'Duplicate training request')
    for row in evaluation:
        require(set(row) == {'case_id', 'family', 'evaluation_group', 'request', 'request_sha256', 'prompt_reference'}, 'Labels/metadata in model row')
        request = row['request']
        require(set(request) == {'messages', 'tools'} and request['tools'] is None, 'Unexpected model input')
        require([m['role'] for m in request['messages']] == ['system', 'user'], 'Target in model input')
        require(canonical_hash(request) == row['request_sha256'], 'Eval request changed')
        require(row['request_sha256'] not in set(hashes), 'Exact evaluation prompt in gradients')
        if row['family'] == 'explanation':
            payload = strict_json(request['messages'][1]['content'])
            require(payload['tool_evidence']['facts'] == lookup[row['case_id']]['facts'], 'Judge fact table mismatch')
            require(payload['tool_evidence']['project_workflow'] == WORKFLOW, 'Project context drift')
    require(plan['train_visit_order'] == training_order(train) * 2, 'Sample order changed')
    require(plan['planned_answers'] == 3 * len(evaluation), 'Eval plan changed')
    return root, manifest, plan, train, evaluation, lookup


def summarize(records, evaluation):
    expected = {(a, r['case_id']) for a in ('selection80_before', 'joint_epoch1', 'joint_epoch2') for r in evaluation}
    observed = {(r['arm'], r['case_id']) for r in records}
    require(len(records) == len(observed) and observed <= expected, 'Repeated/unknown output')
    groups = {}
    for group in sorted({r['evaluation_group'] for r in evaluation}):
        groups[group] = {}
        for arm in ('selection80_before', 'joint_epoch1', 'joint_epoch2'):
            rr = [r for r in records if r['evaluation_group'] == group and r['arm'] == arm]
            item = {'answers': len(rr), 'protocol_passes': sum(r['score']['protocol_passed'] for r in rr),
                    'truncated': sum(r['completion']['finish_reason'] == 'length' for r in rr),
                    'mean_generation_seconds': statistics.mean(r['generation_seconds'] for r in rr) if rr else None}
            if group.startswith('selection'):
                item['selection_gate_passes'] = sum(r['score']['selection_gate_passed'] for r in rr)
            else:
                item['protocol_and_coverage_passes'] = sum(r['score']['protocol_and_coverage_passed'] for r in rr)
                item['numeric_required_cases'] = sum(r['score']['required_fact_count'] > 0 for r in rr)
                item['numeric_required_coverage_passes'] = sum(r['score']['required_fact_count'] > 0 and r['score']['required_fact_coverage_passed'] for r in rr)
            groups[group][arm] = item
    return {'complete': observed == expected, 'answers': len(records), 'expected_answers': len(expected),
            'groups': groups, 'training_run': any(r['arm'] != 'selection80_before' for r in records),
            'independent_test': False, 'domain_accuracy': None, 'semantic_review': 'pending',
            'deployment_approved': False, 'teacher_calls': 0, 'retries': 0,
            'scope': 'Seen development questions, same RP1043 source family; prior checkpoint has historical exposure. New gradients exclude declared parent records. Protocol/selection coverage is not physics accuracy.'}
