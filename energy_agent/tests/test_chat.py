import json

from fastapi.testclient import TestClient
import httpx
import pytest

from energy_agent.agents.chat import ChatService
from energy_agent.agents.reporting import render_answer
from energy_agent.api.app import create_app
from energy_agent.api import chat
from energy_agent.contracts.chat import ChatContext, ChatRequest, LLMSettings
from energy_agent.providers.compatible import CompatibleProvider
from energy_agent.runtime import AgentRuntime
from energy_agent.storage.chat import ChatStore, SessionBusy


def tool_call(name="chiller_analyze", arguments=None, call_id="call_a"):
    return {"role": "assistant", "content": None, "reasoning_content": "fixture-private-reasoning", "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments if arguments is not None else {"task": "physics"})}}]}


def grounded_answer(body):
    for message in reversed(body["messages"]):
        if message["role"] == "tool":
            payload = json.loads(message["content"])
            facts = payload.get("facts", [])
            fact = next((f for f in facts if f["label"].startswith("实测COP（")), None)
            if fact:
                return {"role": "assistant", "content": "实测COP的有效输出点均值为 {{fact:" + fact["fact_id"] + "}}。结果来自水侧测量。", "reasoning_content": "fixture-final-private"}
    return {"role": "assistant", "content": "请补充必要输入后继续分析。", "reasoning_content": "fixture-final-private"}


class ProtocolFixture:
    """Explicit test-only upstream protocol fixture, never a production provider."""
    def __init__(self, steps):
        self.steps, self.requests = list(steps), []
    def handle(self, request):
        body = json.loads(request.content)
        self.requests.append(body)
        step = self.steps.pop(0)
        if isinstance(step, int):
            return httpx.Response(step, text="fixture-secret must not leak")
        message = step(body) if callable(step) else step
        return httpx.Response(200, json={"choices": [{"message": message}]})
    def provider(self):
        return CompatibleProvider(LLMSettings(base_url="https://fixture.example/v1", model="fixture-model", api_key="fixture-secret"),
                                  transport=httpx.MockTransport(self.handle))


def bound_request(runtime, source, message="分析当前机组能效"):
    dataset = runtime.register_dataset(source)
    return ChatRequest(message=message, context=ChatContext(asset_id=dataset.asset_id, dataset_id=dataset.dataset_id))


def test_real_tool_cycle_grounded_report_and_saved_history(data_dir, physics_source):
    runtime = AgentRuntime(data_dir)
    fixture = ProtocolFixture([tool_call(), grounded_answer])
    request = bound_request(runtime, physics_source)
    reply = ChatService(runtime, fixture.provider()).send(request)
    assert reply.status == "completed"
    assert "4.18" in reply.answer
    assert reply.tool_calls[0].task == "physics"
    assert len(reply.tool_run_ids) == 1
    fact = next(f for f in reply.facts if f.label.startswith("实测COP（"))
    artifact = runtime.repository.get_run(fact.run_id)
    assert artifact["result"]["metrics"]["COP"]["value"] == fact.value
    assert any(segment.fact_id == fact.fact_id for segment in reply.segments)
    public = ChatStore(runtime.repository).get_session(reply.session_id)
    assert public["turns"][0]["answer"] == reply.answer
    assert "fixture-private" not in json.dumps(public)
    assert "reasoning_content" not in json.dumps(public)


def test_next_turn_preserves_private_protocol_messages_and_context(data_dir, physics_source):
    runtime = AgentRuntime(data_dir)
    fixture = ProtocolFixture([tool_call(), grounded_answer,
                               {"role": "assistant", "content": "该结论来自上一轮的水侧测量，请结合负荷和模型适用范围判断。"}])
    first = ChatService(runtime, fixture.provider()).send(bound_request(runtime, physics_source))
    second = ChatService(AgentRuntime(data_dir), fixture.provider()).send(ChatRequest(session_id=first.session_id, message="解释上一轮结果"))
    assert second.status == "completed"
    transcript = fixture.requests[2]["messages"]
    assert any(message.get("reasoning_content") == "fixture-private-reasoning" for message in transcript)
    assert any(message.get("reasoning_content") == "fixture-final-private" for message in transcript)
    assert len(ChatStore(runtime.repository).get_session(first.session_id)["turns"]) == 2


def test_model_cannot_override_dataset_or_invoke_unknown_tool(data_dir, physics_source):
    runtime = AgentRuntime(data_dir)
    fixture = ProtocolFixture([tool_call(arguments={"task": "physics", "dataset_id": "another"}), grounded_answer])
    reply = ChatService(runtime, fixture.provider()).send(bound_request(runtime, physics_source))
    assert reply.status == "needs_input"
    assert reply.tool_run_ids == []
    assert reply.tool_calls[0].status == "needs_input"
    assert "facts" not in json.loads(fixture.requests[1]["messages"][-1]["content"])


def test_unsupported_numbers_are_repaired_using_real_facts(data_dir, physics_source):
    runtime = AgentRuntime(data_dir)
    fixture = ProtocolFixture([tool_call(), {"role": "assistant", "content": "COP是9999。"}, grounded_answer])
    reply = ChatService(runtime, fixture.provider()).send(bound_request(runtime, physics_source))
    assert "9999" not in reply.answer
    assert "4.18" in reply.answer
    assert reply.model_calls == 3
    assert reply.report_mode == "model"


def test_repeated_unverified_numbers_fall_back_to_tool_facts(data_dir, physics_source):
    runtime = AgentRuntime(data_dir)
    fixture = ProtocolFixture([tool_call(), {"role": "assistant", "content": "COP是9999。"},
                               {"role": "assistant", "content": "COP是8888。"}])
    reply = ChatService(runtime, fixture.provider()).send(bound_request(runtime, physics_source))
    assert reply.report_mode == "tool_facts"
    assert "9999" not in reply.answer and "8888" not in reply.answer
    assert "4.18" in reply.answer
    assert reply.notices


def test_known_identifiers_in_repaired_answer_do_not_discard_tool_explanation(data_dir, physics_source):
    runtime = AgentRuntime(data_dir)
    request = bound_request(runtime, physics_source)

    def repaired_answer(body):
        result = grounded_answer(body)
        result["content"] = (f"当前绑定数据 {request.context.dataset_id[:11]}…，机组 {request.context.asset_id}。\n"
                             + result["content"] + "\n需要覆盖不同工况的数据；当前结果不能用于独立确诊。")
        return result

    fixture = ProtocolFixture([tool_call(), {"role": "assistant", "content": "能量偏差约为9999 kW。"}, repaired_answer])
    reply = ChatService(runtime, fixture.provider()).send(request)
    assert reply.status == "completed" and reply.report_mode == "model"
    assert reply.model_calls == 3 and not reply.notices
    assert "4.18" in reply.answer and "需要覆盖不同工况的数据" in reply.answer
    assert request.context.asset_id not in reply.answer and "ds_" not in reply.answer
    assert "9999" not in reply.answer
    assert any(segment.fact_id for segment in reply.segments)
    correction = fixture.requests[2]["messages"][-1]["content"]
    assert "数值结论必须使用可核对的fact占位符" in correction
    assert "不要复述数据集、机组或运行编号" in correction
    saved = ChatStore(runtime.repository).get_session(reply.session_id)["turns"][0]
    assert saved["answer"] == reply.answer and saved["report_mode"] == "model"


def test_grounded_nonzero_balance_explanation_does_not_trigger_fallback(data_dir, physics_source):
    runtime = AgentRuntime(data_dir)

    def balance_explanation(body):
        facts = json.loads(body["messages"][-1]["content"])["facts"]
        fact = next(fact for fact in facts if fact["label"].startswith("实测能量偏差（"))
        return {"role": "assistant", "content": "能量平衡偏差：{{fact:" + fact["fact_id"]
                + "}}。\n能量平衡偏差在均值上不为零，需要检查计量边界与单位。这是候选解释之一。"}

    fixture = ProtocolFixture([tool_call(), balance_explanation])
    reply = ChatService(runtime, fixture.provider()).send(bound_request(runtime, physics_source))
    assert reply.report_mode == "model" and reply.status == "completed"
    assert reply.model_calls == 2 and not reply.notices
    assert "需要检查计量边界与单位" in reply.answer and "4.5 kW" in reply.answer
    assert len([segment for segment in reply.segments if segment.fact_id]) == 2


@pytest.mark.parametrize("identifier", [
    "chiller_01", "ds_0123456789abcdef0123456789abcdef", "ds_01234567…", "ds_01234567...",
    "run_abcdef0123456789abcdef0123456789", "run_abcdef01…",
])
def test_reference_normalization_preserves_fact_segments(identifier):
    from energy_agent.contracts.chat import ChatFact
    references = {"chiller_01": "当前机组", "ds_0123456789abcdef0123456789abcdef": "当前数据集",
                  "run_abcdef0123456789abcdef0123456789": "该分析运行"}
    fact = ChatFact(fact_id="F1", label="实测COP", value=4.18, unit="1", pointer="/cop", origin="measured_derived")
    answer, segments = render_answer(f"分析对象：`{identifier}`。\n计算结果：{{{{fact:F1}}}}。", [fact], reference_names=references)
    assert identifier not in answer and "4.18" in answer
    assert [segment.fact_id for segment in segments if segment.fact_id] == ["F1"]


@pytest.mark.parametrize("text", [
    "当前机组 chiller_01 的COP是4.18。", "当前机组 chiller_01 的功率为五百瓦。",
    "机组 chiller_0100。", "数据 ds_ffffffff…。", "数据 ds_0123456…。",
    "数据 ds_01234567。", "结果{{fact:F999}}。", "结果{{unknown:bad}}。",
])
def test_known_identifiers_do_not_exempt_unknown_numbers_or_references(text):
    references = {"chiller_01": "当前机组", "ds_0123456789abcdef0123456789abcdef": "当前数据集"}
    with pytest.raises(ValueError):
        render_answer(text, [], reference_names=references)


def test_ambiguous_short_reference_is_not_rewritten():
    references = {"ds_0123456789abcdef0123456789abcdef": "当前数据集",
                  "ds_01234567ffffffffffffffffffffffff": "其他数据集"}
    with pytest.raises(ValueError):
        render_answer("数据 ds_01234567…。", [], reference_names=references)


def test_asset_identifier_cannot_replace_a_fact_placeholder():
    from energy_agent.contracts.chat import ChatFact
    fact = ChatFact(fact_id="F1", label="实测COP", value=4.18, unit="1", pointer="/cop", origin="measured_derived")
    answer, segments = render_answer("机组 F1。计算结果：{{fact:F1}}。", [fact], reference_names={"F1": "当前机组"})
    assert "4.18" in answer and any(segment.fact_id == "F1" for segment in segments)


@pytest.mark.parametrize("text", ["COP为4.18", "COP为四点一八", "概率百分之五", "结果是{{fact:F999}}", "{{unknown:bad}}",
                                  "实测COP为五", "总共五个样本", "功率为五百瓦", "有效点数为壹佰"])
def test_unverified_arabic_chinese_or_unknown_fact_references_rejected(text):
    with pytest.raises(ValueError):
        render_answer(text, [])


def test_provider_failure_after_tool_keeps_evidence_and_redacts_error(data_dir, physics_source):
    runtime = AgentRuntime(data_dir)
    fixture = ProtocolFixture([tool_call(), 401])
    reply = ChatService(runtime, fixture.provider()).send(bound_request(runtime, physics_source))
    assert reply.status == "failed"
    assert reply.error_code == "LLM_AUTH_FAILED"
    assert reply.tool_run_ids and "4.18" in reply.answer
    assert "fixture-secret" not in reply.model_dump_json()
    assert ChatStore(runtime.repository).get_session(reply.session_id)["turns"][0]["status"] == "failed"


def test_missing_bound_dataset_and_model_are_explained(data_dir, physics_source):
    runtime = AgentRuntime(data_dir)
    fixture = ProtocolFixture([tool_call(), grounded_answer])
    reply = ChatService(runtime, fixture.provider()).send(ChatRequest(message="分析能效"))
    assert reply.status == "needs_input" and not reply.tool_run_ids
    fixture = ProtocolFixture([tool_call(arguments={"task": "simulate"}), grounded_answer])
    reply = ChatService(runtime, fixture.provider()).send(bound_request(runtime, physics_source))
    assert reply.status == "needs_input" and not reply.tool_run_ids


def test_session_concurrent_send_is_rejected_without_model_call(data_dir):
    runtime = AgentRuntime(data_dir)
    store = ChatStore(runtime.repository)
    session, pending = store.begin(ChatRequest(message="pending"), "fixture-model")
    fixture = ProtocolFixture([])
    with pytest.raises(SessionBusy):
        ChatService(runtime, fixture.provider()).send(ChatRequest(message="next", session_id=session["session_id"]))
    assert fixture.requests == []
    pending.status = "failed"
    store.finish(session, pending, [])


def test_expired_interrupted_session_can_continue(data_dir):
    runtime = AgentRuntime(data_dir)
    store = ChatStore(runtime.repository)
    session, pending = store.begin(ChatRequest(message="old"), "fixture-model")
    with runtime.repository._connection() as db:
        db.execute("UPDATE chat_sessions SET busy_until=0 WHERE id=?", (session["session_id"],))
    fixture = ProtocolFixture([{"role": "assistant", "content": "可以继续分析。"}])
    reply = ChatService(runtime, fixture.provider()).send(ChatRequest(message="继续", session_id=session["session_id"]))
    view = store.get_session(session["session_id"])
    assert view["turns"][0]["error_code"] == "TURN_INTERRUPTED"
    assert reply.status == "completed"


def test_tool_and_model_call_budgets_are_bounded(data_dir):
    runtime = AgentRuntime(data_dir)
    fixture = ProtocolFixture([tool_call(name="inspect_dataset", arguments={}, call_id=f"call_{i}") for i in range(4)])
    reply = ChatService(runtime, fixture.provider()).send(ChatRequest(message="帮我检查"))
    assert reply.status == "limited" and reply.model_calls == 4
    assert reply.error_code == "MODEL_CALL_LIMIT"


def test_chat_http_history_report_and_no_private_reasoning(data_dir, physics_source, monkeypatch):
    runtime = AgentRuntime(data_dir)
    request = bound_request(runtime, physics_source)
    fixture = ProtocolFixture([tool_call(), grounded_answer])
    monkeypatch.setattr(chat, "provider", lambda instance: fixture.provider())
    client = TestClient(create_app(data_dir))
    response = client.post("/agent/v1/chat/external", json=request.model_dump(mode="json"))
    assert response.status_code == 200, response.text
    reply = response.json()
    view = client.get(f'/agent/v1/chat/sessions/{reply["session_id"]}')
    assert "reasoning_content" not in view.text
    assert client.get("/agent/v1/chat/sessions").json()[0]["session_id"] == reply["session_id"]
    report = client.get(f'/agent/v1/chat/sessions/{reply["session_id"]}/turns/{reply["turn_id"]}/report')
    assert report.status_code == 200
    assert "4.18" in report.text and "JSON Pointer" in report.text
    assert "attachment" in report.headers["content-disposition"]
    assert client.get("/agent/v1/chat/sessions/missing").status_code == 404


def test_clarification_can_use_ordinary_classifier_words():
    text, segments = render_answer("请先选择一个数据集，再发送分析问题。", [])
    assert text == "请先选择一个数据集，再发送分析问题。"


def test_fact_label_and_origin_are_visible_and_wrong_attribution_is_rejected():
    from energy_agent.contracts.chat import ChatFact
    fact = ChatFact(fact_id="F1", run_id="r", label="模型COP（有效输出点均值）", value=7.5, unit="1", pointer="/cop", origin="model")
    for text in ("实测COP为{{fact:F1}}。", "模型功率为{{fact:F1}}。", "{{fact:F1}}是实测COP。", "{{fact:F1}}是模型功率。"):
        with pytest.raises(ValueError):
            render_answer(text, [fact])
    answer, _ = render_answer("计算结果：{{fact:F1}}。", [fact])
    assert "模型COP（有效输出点均值）" in answer and "模型：7.5" in answer


def test_unbound_general_knowledge_numbers_are_not_equipment_results(data_dir):
    from energy_agent.agents.reporting import markdown_report
    runtime = AgentRuntime(data_dir)
    fixture = ProtocolFixture([{"role": "assistant", "content": "COP为制冷量除以功率，例如500 kW除以100 kW得到5。这个例子不是当前设备计算结果。"}])
    reply = ChatService(runtime, fixture.provider()).send(ChatRequest(message="举例解释COP"))
    assert reply.status == "completed" and reply.report_mode == "message" and reply.model_calls == 1
    assert reply.tool_run_ids == [] and reply.notices
    assert "非设备数值报告" in markdown_report(reply)


def test_tool_unexpected_error_keeps_valid_history_for_following_turn(data_dir, physics_source, monkeypatch):
    runtime = AgentRuntime(data_dir)
    def broken(*args, **kwargs):
        raise RuntimeError("private-fixture-secret")
    monkeypatch.setattr(runtime.registry, "execute", broken)
    fixture = ProtocolFixture([tool_call(), {"role": "assistant", "content": "工具执行未完成，请稍后再试。"},
                               {"role": "assistant", "content": "可以继续提问。"}])
    first = ChatService(runtime, fixture.provider()).send(bound_request(runtime, physics_source))
    assert first.status == "failed" and not first.tool_run_ids
    assert "private-fixture-secret" not in first.model_dump_json()
    second = ChatService(runtime, fixture.provider()).send(ChatRequest(session_id=first.session_id, message="继续"))
    assert second.status == "completed"
    transcript = fixture.requests[2]["messages"]
    position = next(i for i, item in enumerate(transcript) if item.get("tool_calls"))
    assert transcript[position+1]["role"] == "tool"
    assert transcript[position+1]["tool_call_id"] == "call_a"


def test_exception_after_tool_result_also_completes_protocol_pairs(data_dir, physics_source, monkeypatch):
    import energy_agent.agents.chat as module
    runtime = AgentRuntime(data_dir)
    def broken(*args, **kwargs):
        raise RuntimeError("fixture-processing-error")
    monkeypatch.setattr(module, "result_facts", broken)
    fixture = ProtocolFixture([tool_call()])
    reply = ChatService(runtime, fixture.provider()).send(bound_request(runtime, physics_source))
    assert reply.status == "failed"
    wire = ChatStore(runtime.repository).recent(reply.session_id)[0]["wire"]
    assert [item["role"] for item in wire] == ["user", "assistant", "tool", "assistant"]
    assert wire[2]["tool_call_id"] == "call_a"


@pytest.mark.parametrize("task", ["simulate", "compare"])
def test_model_routes_simulation_and_comparison_through_existing_tool(data_dir, task):
    from chiller_app.model.electric_eir import DEFAULT_RECORD
    from energy_agent.contracts.tools import SelectedSimulation
    runtime = AgentRuntime(data_dir)
    source = {"asset_id": "a", "records": [{"tei": 13.89, "tci": 26.67, "me": 10.35, "mc": 19.24, "p": 45}],
              "schema": {"column_map": {"TEI_K": "tei", "TCI_K": "tci", "evap_flow_kg_s": "me", "cond_flow_kg_s": "mc", "P_W": "p"},
                         "temperature_unit": "C", "flow_unit": "kg/s", "power_unit": "kW"}}
    dataset = runtime.register_dataset(source)
    context = ChatContext(asset_id="a", dataset_id=dataset.dataset_id,
                          simulation=SelectedSimulation(record_id=DEFAULT_RECORD, mode="steady", kind="series", setpoint=8.89))
    def answer(body):
        facts = json.loads(body["messages"][-1]["content"])["facts"]
        prefix = "模型COP（" if task == "simulate" else "实测功率比较mae"
        fact = next(f for f in facts if f["label"].startswith(prefix))
        return {"role": "assistant", "content": "已完成所选任务，对应结果为 {{fact:" + fact["fact_id"] + "}}。"}
    fixture = ProtocolFixture([tool_call(arguments={"task": task}), answer])
    reply = ChatService(runtime, fixture.provider()).send(ChatRequest(message="执行配置对应的分析", context=context))
    assert reply.status == "completed"
    assert reply.tool_calls[0].task == task
    artifact = runtime.repository.get_run(reply.tool_run_ids[0])
    assert artifact["result"]["task"] == task
    assert artifact["model_output"]["metadata"]["performance_record"] == DEFAULT_RECORD


def test_fact_history_does_not_carry_unused_old_facts_forever(data_dir, physics_source):
    runtime = AgentRuntime(data_dir)
    fixture = ProtocolFixture([tool_call(), grounded_answer, {"role": "assistant", "content": "可以继续提问。"},
                               {"role": "assistant", "content": "仍可查看历史运行。"}])
    first = ChatService(runtime, fixture.provider()).send(bound_request(runtime, physics_source))
    second = ChatService(runtime, fixture.provider()).send(ChatRequest(session_id=first.session_id, message="你好"))
    assert [fact.fact_id for fact in second.facts] == ["F0"]
    third = ChatService(runtime, fixture.provider()).send(ChatRequest(session_id=first.session_id, message="继续"))
    assert [fact.fact_id for fact in third.facts] == ["F0"]


def test_parallel_tool_packets_respect_budget_and_keep_pairs_complete(data_dir, physics_source):
    runtime = AgentRuntime(data_dir)
    packet = tool_call()
    packet["tool_calls"] = [tool_call(call_id=f"call_{i}")["tool_calls"][0] for i in range(6)]
    fixture = ProtocolFixture([packet])
    reply = ChatService(runtime, fixture.provider()).send(bound_request(runtime, physics_source))
    assert reply.status == "limited" and reply.error_code == "TOOL_CALL_LIMIT"
    assert len(reply.tool_run_ids) == 4 and len(reply.tool_calls) == 6
    wire = ChatStore(runtime.repository).recent(reply.session_id)[0]["wire"]
    assert len([item for item in wire if item["role"] == "tool"]) == 6


def test_chat_pages_and_workbench_transfer_entry_are_available(data_dir):
    client = TestClient(create_app(data_dir))
    assert client.get("/chat").status_code == 200
    assert "模型连接配置" in client.get("/chat").text
    assert client.get("/static/chat.js").status_code == 200
    assert client.get("/static/chat.css").status_code == 200
    from chiller_app.api.fastapi_app import app
    original = TestClient(app)
    assert 'id="send-to-chat"' in original.get("/").text
    assert original.get("/chat").status_code == 200
