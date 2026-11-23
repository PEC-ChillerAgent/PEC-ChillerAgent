import json

import httpx
import pytest

from energy_agent.agents.chat import ChatService
from energy_agent.contracts.chat import ChatContext, ChatRequest, LLMSettings
from energy_agent.distillation.export import export_candidate
from energy_agent.providers.compatible import CompatibleProvider
from energy_agent.runtime import AgentRuntime


def test_capture_snapshots_requests_repairs_metadata_and_masks_secrets(data_dir, physics_source):
    runtime = AgentRuntime(data_dir)
    ds = runtime.register_dataset(physics_source)
    requests = []

    def upstream(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            message = {"role": "assistant", "content": None, "reasoning_content": "private-chain",
                       "tool_calls": [{"id": "call_x", "type": "function", "function": {
                           "name": "chiller_analyze", "arguments": '{"task":"physics"}'}}]}
        elif len(requests) == 2:
            message = {"role": "assistant", "content": "COP是9999。", "reasoning_content": "private-chain"}
        else:
            tool = next(json.loads(m["content"]) for m in body["messages"] if m["role"] == "tool")
            fact = next(f for f in tool["facts"] if f["pointer"] == "/result/metrics/COP/value")
            message = {"role": "assistant", "content": "计算结果：{{fact:" + fact["fact_id"] + "}}。capture-secret"}
        return httpx.Response(200, json={"id": f"request-{len(requests)}", "model": "actual-version",
                                        "usage": {"prompt_tokens": 30, "completion_tokens": 10},
                                        "choices": [{"finish_reason": "stop", "message": message}]})

    provider = CompatibleProvider(LLMSettings(base_url="https://fixture.example/v1", model="configured-name",
                                  api_key="capture-secret", extra_body={"temperature": 0, "api_key": "capture-secret"}),
                                  transport=httpx.MockTransport(upstream))
    turn = ChatService(runtime, provider).send(ChatRequest(message="分析当前数据", context=ChatContext(asset_id=ds.asset_id, dataset_id=ds.dataset_id)))
    candidate = export_candidate(runtime.repository.path, turn.turn_id, "group-a")
    assert turn.report_mode == "model" and candidate["outcome"]["repair_rounds"] == 1
    assert candidate["capture_status"] == "application_trace" and not candidate["training_approved"]
    calls = [e["payload"] for e in candidate["events"] if e["kind"] == "model_call"]
    assert len(calls) == 3 and len(calls[0]["request"]["messages"]) == 2
    assert calls[0]["request"]["tools"] and calls[0]["request"]["temperature"] == 0
    assert calls[-1]["response"]["model"] == "actual-version"
    assert calls[-1]["response"]["usage"]["completion_tokens"] == 10
    assert calls[-1]["response"]["finish_reason"] == "stop"
    assert all(c["elapsed_ms"] >= 0 for c in calls)
    assert "capture-secret" not in json.dumps(candidate)
    assert "private-chain" not in json.dumps(candidate) and "reasoning_content" not in json.dumps(candidate)
    # Required private protocol fields still reach the provider, never the export.
    assert any(m.get("reasoning_content") == "private-chain" for m in requests[1]["messages"])
    validations = [e["payload"]["passed"] for e in candidate["events"] if e["kind"] == "validation"]
    assert validations == [False, True]
    assert candidate["runs"][turn.tool_run_ids[0]]["result"]["metrics"]["COP"]["value"] == pytest.approx(4.18)


def test_failed_provider_attempt_is_captured_without_error_body(data_dir):
    runtime = AgentRuntime(data_dir)
    provider = CompatibleProvider(LLMSettings(base_url="https://fixture.example/v1", model="fixture", api_key="capture-secret"),
                                  transport=httpx.MockTransport(lambda req: httpx.Response(429, text="capture-secret private-body")))
    turn = ChatService(runtime, provider).send(ChatRequest(message="你好"))
    candidate = export_candidate(runtime.repository.path, turn.turn_id, "general-pilot")
    call = next(e["payload"] for e in candidate["events"] if e["kind"] == "model_call")
    assert call["error_code"] == "LLM_RATE_LIMITED" and call["http_status"] == 429
    assert candidate["outcome"]["status"] == "failed"
    assert candidate["outcome"]["fallback_used"]
    assert "private-body" not in json.dumps(candidate) and "capture-secret" not in json.dumps(candidate)


def test_export_preserves_followup_context_and_marks_legacy_capture(data_dir, physics_source):
    runtime = AgentRuntime(data_dir)
    ds = runtime.register_dataset(physics_source)
    messages = iter([
        {"role": "assistant", "content": None, "tool_calls": [{"id": "t", "type": "function", "function": {
            "name": "chiller_analyze", "arguments": '{"task":"physics"}'}}]},
        {"role": "assistant", "content": "结果：{{fact:F7}}。"},
        {"role": "assistant", "content": "已有结果：{{fact:F7}}。"},
    ])
    provider = CompatibleProvider(LLMSettings(base_url="https://fixture.example/v1", model="fixture", api_key="secret"),
                                  transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"choices": [{"message": next(messages)}]})))
    service = ChatService(runtime, provider)
    first = service.send(ChatRequest(message="计算", context=ChatContext(asset_id=ds.asset_id, dataset_id=ds.dataset_id)))
    second = service.send(ChatRequest(message="解释", session_id=first.session_id))
    candidate = export_candidate(runtime.repository.path, second.turn_id, "group-a")
    assert candidate["outcome"]["history_evidence_reused"]
    assert candidate["prior_context_turns"][0]["public"]["turn_id"] == first.turn_id
    with runtime.repository._connection() as db:
        db.execute("DROP TABLE chat_audit_events")
    legacy = export_candidate(runtime.repository.path, second.turn_id, "group-a")
    assert legacy["capture_status"] == "legacy_or_partial" and legacy["events"] == []
    assert len(legacy["prior_context_turns"]) == 1 and legacy["runs"]
    with pytest.raises(ValueError, match="provenance group"):
        export_candidate(runtime.repository.path, second.turn_id, "")
