"""Real Python execution with a synthetic HTTP transport; no GPU accuracy claims."""
import copy
from dataclasses import replace
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from chiller_student.focused_contract import IDENTITY, MODEL_ID, validate_api_body
from chiller_student.joint_physics_support import canonical_hash
from chiller_student.native_sft_data import token_digest
from energy_agent.agents.student_explanation import StudentExplanationService
from energy_agent.api.app import create_app
from energy_agent.config.llm import LLMConfigStore
from energy_agent.config.student_focused import StudentFocusedSettings
from energy_agent.contracts.chat import ChatRequest
from energy_agent.providers.compatible import CompatibleProvider
from energy_agent.providers.student_explanation import StudentExplanationClient
from energy_agent.runtime import AgentRuntime


ANSWER = '制冷量为{{fact:F3}}，输入功率为{{fact:F1}}，COP为{{fact:F7}}。COP表示单位输入功率对应的制冷量，两个功率单位相除后为无量纲。'


@pytest.fixture(autouse=True)
def forbid_external_models(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('External provider/configuration must never be used by primary student analysis')
    monkeypatch.setattr(CompatibleProvider, 'complete', forbidden)
    monkeypatch.setattr(LLMConfigStore, 'load', forbidden)
    for name in ['ENABLED', 'URL', 'TOKEN_FILE', 'TIMEOUT_S']:
        monkeypatch.delenv('ENERGY_AGENT_STUDENT_FOCUSED_' + name, raising=False)


class Transport:
    def __init__(self, runtime, mode='ok'):
        self.runtime = runtime
        self.mode = mode
        self.requests = []
        self.bodies = []

    def handle(self, request):
        self.requests.append(request)
        with self.runtime.repository._connection() as db:
            assert db.execute('SELECT COUNT(*) FROM runs').fetchone()[0] >= 1
        if self.mode == 'timeout':
            raise httpx.ReadTimeout('fixture timeout', request=request)
        identity = dict(IDENTITY)
        if self.mode == 'wrong_model':
            identity['adapter_model_sha256'] = 'a' * 64
        if request.method == 'GET':
            return httpx.Response(200, json={'status': 'ok', 'backend': 'real_qwen3_8b_bf16_lora_fp32',
                                             'service_identity': identity})
        body = json.loads(request.content)
        payload = validate_api_body(body)
        self.bodies.append(body)
        assert all(f['run_id'] for f in payload['tool_evidence']['facts'])
        content = json.dumps({'answer': ANSWER}, ensure_ascii=False)
        if self.mode == 'bad_json':
            content = 'not a valid answer envelope'
        if self.mode == 'contradiction':
            content = json.dumps({'answer': '本次已经确认机组故障。'}, ensure_ascii=False)
        ids = [42]
        completion = {'content': content, 'finish_reason': 'stop', 'completion_tokens': 1,
                      'completion_token_ids': ids, 'completion_token_ids_sha256': token_digest(ids)}
        audit = {'service_identity': identity, 'completion': completion,
                 'score_trace': [{'argmax_token_id': 42}], 'rng_before': {}, 'rng_after': {},
                 'state_before': {}, 'state_after': {},
                 'request_sha256': canonical_hash({'messages': body['messages'], 'tools': None}),
                 'actual_generation_config': {'passed': True, 'actual_prepared_generation_config':
                                             {'do_sample': False, 'max_new_tokens': 2048}}}
        if self.mode == 'replay':
            audit['request_sha256'] = 'f' * 64
        return httpx.Response(200, json={'model': MODEL_ID, 'choices': [{'finish_reason': 'stop',
                                       'message': {'role': 'assistant', 'content': content}}],
                                       'chiller_development_audit': audit})


def setup(data_dir, physics_source, mode='ok'):
    runtime = AgentRuntime(data_dir)
    info = runtime.register_dataset(physics_source)
    token = data_dir / 'test-only.token'
    token.write_text('synthetic-focused-transport-test-token', encoding='utf-8')
    settings = StudentFocusedSettings(token_file=token, service_identity=dict(IDENTITY))
    transport = Transport(runtime, mode)
    client = StudentExplanationClient(settings, transport=httpx.MockTransport(transport.handle))
    service = StudentExplanationService(runtime, settings, client=client)
    request = ChatRequest(message='请给出本次制冷量、输入功率和COP，并解释COP表示什么。',
                          context={'asset_id': info.asset_id, 'dataset_id': info.dataset_id})
    return service, request, transport


def test_current_python_run_precedes_focused_request_and_values_are_bound(data_dir, physics_source):
    service, request, transport = setup(data_dir, physics_source)
    turn = service.send(request)
    assert turn.report_mode == 'student_explanation', turn.model_dump()
    assert turn.model == MODEL_ID and turn.analysis_backend == 'student_explanation'
    assert turn.student_analysis.upstream_service_identity == IDENTITY
    assert turn.student_analysis.teacher_calls == 0 and turn.student_analysis.teacher_fallback is False
    assert turn.student_analysis.model_authored_factual_text is True
    assert len(turn.tool_run_ids) == len(turn.tool_calls) == 1
    assert '4.18' in turn.answer and '{{fact:' not in turn.answer
    body = transport.bodies[0]
    payload = validate_api_body(body)
    assert {f['run_id'] for f in payload['tool_evidence']['facts']} == set(turn.tool_run_ids)
    assert any(t['task_id'] == 'COP_meaning' for t in payload['tool_evidence']['answer_task_plan']['tasks'])
    assert len(transport.requests) == 2


def test_application_grammar_exemption_does_not_allow_unreferenced_measurements(data_dir, physics_source):
    from chiller_student.focused_output import render_answer
    service, request, _ = setup(data_dir, physics_source)
    turn = service.send(request)
    with pytest.raises(ValueError):
        render_answer('输入功率为500 kW，两个功率单位相除抵消。', turn.facts)


@pytest.mark.parametrize('mode,error', [('timeout', 'STUDENT_TIMEOUT_NO_RETRY'),
    ('wrong_model', 'STUDENT_IDENTITY_MISMATCH'), ('bad_json', 'STUDENT_EXPLANATION_FORMAT_REJECTED'),
    ('contradiction', 'STUDENT_EXPLANATION_KNOWN_CONTRADICTION'), ('replay', 'STUDENT_REQUEST_BINDING_MISMATCH')])
def test_invalid_service_response_falls_back_to_current_python_facts(data_dir, physics_source, mode, error):
    service, request, transport = setup(data_dir, physics_source, mode)
    turn = service.send(request)
    assert turn.error_code == error, turn.model_dump()
    assert turn.report_mode == 'tool_facts' and '4.18' in turn.answer
    assert turn.student_analysis.model_authored_factual_text is False
    assert turn.student_analysis.teacher_calls == 0 and len(transport.requests) <= 2
    with service.runtime.repository._connection() as db:
        audits = str(db.execute('SELECT payload FROM chat_audit_events WHERE turn_id=?', (turn.turn_id,)).fetchall())
    assert service.settings.token_file.read_text() not in audits


def test_each_question_computes_new_run_and_no_old_fact_context_is_reused(data_dir, physics_source):
    service, request, transport = setup(data_dir, physics_source)
    first = service.send(request)
    second = service.send(ChatRequest(message=request.message, session_id=first.session_id))
    assert first.tool_run_ids != second.tool_run_ids
    assert len(transport.bodies) == 2
    for body, turn in zip(transport.bodies, [first, second]):
        e = validate_api_body(body)['tool_evidence']
        assert {f['run_id'] for f in e['facts']} == set(turn.tool_run_ids)


def test_unsupported_simulation_does_not_call_student_or_external_model(data_dir, physics_source):
    service, request, transport = setup(data_dir, physics_source)
    request.message = '请运行动态仿真并预测温度趋势。'
    turn = service.send(request)
    assert turn.error_code == 'STUDENT_SCOPE_UNSUPPORTED' and not turn.tool_run_ids
    assert transport.requests == [] and turn.student_analysis.teacher_calls == 0


def test_primary_api_uses_focused_without_loading_external_configuration(data_dir, physics_source, monkeypatch):
    service, request, transport = setup(data_dir, physics_source)
    monkeypatch.setenv('ENERGY_AGENT_STUDENT_FOCUSED_TOKEN_FILE', str(service.settings.token_file))
    import energy_agent.agents.student_explanation as module
    monkeypatch.setattr(module, 'StudentExplanationClient', lambda settings: StudentExplanationClient(
        settings, transport=httpx.MockTransport(transport.handle)))
    app = create_app(data_dir)
    app.state.energy_runtime = service.runtime
    client = TestClient(app)
    config = client.get('/agent/v1/analysis/config').json()
    assert config['enabled'] and config['candidate'] == 'focused1186'
    response = client.post('/agent/v1/analysis', json=request.model_dump(mode='json'))
    assert response.status_code == 200
    assert response.json()['report_mode'] == 'student_explanation', response.json()
    assert response.json()['model'] == MODEL_ID
    default_response = client.post('/agent/v1/chat', json=request.model_dump(mode='json'))
    assert default_response.status_code == 200 and default_response.json()['model'] == MODEL_ID
    assert default_response.json()['report_mode'] == 'student_explanation'
    monkeypatch.setenv('ENERGY_AGENT_STUDENT_FOCUSED_ENABLED', '0')
    assert client.post('/agent/v1/analysis', json=request.model_dump(mode='json')).status_code == 503


@pytest.mark.parametrize('url', ['http://remote.example', 'https://user:password@example.com', 'http://127.0.0.1/path'])
def test_focused_transport_rejects_unsafe_configuration(monkeypatch, url):
    monkeypatch.setenv('ENERGY_AGENT_STUDENT_FOCUSED_URL', url)
    with pytest.raises(ValueError):
        StudentFocusedSettings.from_environment()
