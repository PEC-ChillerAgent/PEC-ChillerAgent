import json

from fastapi.testclient import TestClient
import httpx
import pytest

from energy_agent.api.app import create_app
from energy_agent.api import chat
from energy_agent.config.llm import LLMConfigStore
from energy_agent.contracts.chat import LLMConfigUpdate, LLMSettings
from energy_agent.providers.compatible import CompatibleProvider, ProviderError


def configured(**extra):
    return LLMSettings(base_url="https://models.example/v1", model="fixture-model",
                       api_key="fixture-secret", **extra)


def test_real_transport_payload_and_reasoning_preservation():
    observed = []
    def fixture_server(request):
        # Protocol fixture, never used as a production model.
        observed.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer fixture-secret"
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": "已连接", "reasoning_content": "fixture-private"}}]})
    model = CompatibleProvider(configured(extra_body={"enable_thinking": False}), transport=httpx.MockTransport(fixture_server))
    first = model.complete([{"role": "user", "content": "测试"}], [{"type": "function", "function": {"name": "inspect_dataset", "parameters": {"type": "object", "properties": {}}}}])
    model.complete([{"role": "user", "content": "测试"}, first], [])
    assert observed[0]["model"] == "fixture-model"
    assert observed[0]["stream"] is False
    assert observed[0]["enable_thinking"] is False
    assert observed[1]["messages"][1]["reasoning_content"] == "fixture-private"


@pytest.mark.parametrize("status,code", [(401, "LLM_AUTH_FAILED"), (429, "LLM_RATE_LIMITED"), (500, "LLM_HTTP_ERROR"), (302, "LLM_HTTP_ERROR")])
def test_provider_errors_are_redacted_and_not_retried(status, code):
    calls = []
    def server(request):
        calls.append(request)
        return httpx.Response(status, text="upstream echoes fixture-secret")
    with pytest.raises(ProviderError) as error:
        CompatibleProvider(configured(), transport=httpx.MockTransport(server)).complete([], [])
    assert error.value.code == code
    assert "fixture-secret" not in str(error.value)
    assert len(calls) == 1


def test_config_key_is_hidden_preserved_and_not_reused_for_new_host(data_dir, monkeypatch):
    for name in ("OPENAI_API_KEY", "ENERGY_AGENT_LLM_API_KEY", "ENERGY_AGENT_LLM_MODEL", "ENERGY_AGENT_LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    store = LLMConfigStore(data_dir)
    saved = store.save(LLMConfigUpdate(base_url="https://a.example/v1", model="m", api_key="fixture-secret"))
    assert saved["has_api_key"] and "fixture-secret" not in json.dumps(saved)
    store.save(LLMConfigUpdate(base_url="https://a.example/v1", model="m2"))
    assert store.load().api_key.get_secret_value() == "fixture-secret"
    store.save(LLMConfigUpdate(base_url="https://b.example/v1", model="m3"))
    assert not store.public()["has_api_key"]


def test_f0_http_chat_spine_uses_explicit_protocol_fixture(data_dir, monkeypatch):
    def server(request):
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "协议测试已连接"}}]})
    monkeypatch.setattr(chat, "provider", lambda instance: CompatibleProvider(configured(), transport=httpx.MockTransport(server)))
    client = TestClient(create_app(data_dir))
    result = client.post("/agent/v1/chat/external", json={"message": "你好"})
    assert result.status_code == 200, result.text
    assert result.json()["answer"] == "协议测试已连接"
    assert "reasoning_content" not in result.text


def test_unconfigured_provider_fails_explicitly():
    with pytest.raises(ProviderError) as error:
        CompatibleProvider(LLMSettings()).complete([], [])
    assert error.value.code == "LLM_NOT_CONFIGURED"


def test_environment_priority_and_host_change_do_not_reuse_local_key(data_dir, monkeypatch):
    for name in ("OPENAI_API_KEY", "ENERGY_AGENT_LLM_API_KEY", "ENERGY_AGENT_LLM_MODEL", "ENERGY_AGENT_LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    store = LLMConfigStore(data_dir)
    store.save(LLMConfigUpdate(base_url="https://a.example/v1", model="m", api_key="local-fixture"))
    monkeypatch.setenv("OPENAI_API_KEY", "environment-fixture")
    assert store.load().api_key.get_secret_value() == "local-fixture"
    assert "OPENAI_API_KEY" not in store.public()["environment_overrides"]
    monkeypatch.setenv("ENERGY_AGENT_LLM_BASE_URL", "https://b.example/v1")
    assert not store.load().configured
    assert store.load().api_key is None
    assert "OPENAI_API_KEY" not in store.public()["environment_overrides"]
    monkeypatch.setenv("ENERGY_AGENT_LLM_API_KEY", "new-host-fixture")
    assert store.load().configured


def test_generic_openai_key_fallback_only_for_openai_host(data_dir, monkeypatch):
    for name in ("ENERGY_AGENT_LLM_API_KEY", "ENERGY_AGENT_LLM_MODEL", "ENERGY_AGENT_LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-fixture")
    store = LLMConfigStore(data_dir)
    store.save(LLMConfigUpdate(base_url="https://thirdparty.example/v1", model="m"))
    assert store.load().api_key is None
    store.save(LLMConfigUpdate(base_url="https://api.openai.com/v1", model="m"))
    assert store.load().api_key.get_secret_value() == "openai-fixture"
    assert "OPENAI_API_KEY" in store.public()["environment_overrides"]
    store.save(LLMConfigUpdate(base_url="https://api.openai.com/v1", model="m", api_key="local-fixture"))
    assert store.load().api_key.get_secret_value() == "local-fixture"
    assert "OPENAI_API_KEY" not in store.public()["environment_overrides"]


@pytest.mark.parametrize("url", ["https://provider.example:bad/v1", "http://127.0.0.1:99999/v1"])
def test_malformed_port_rejected_before_network(data_dir, url):
    client = TestClient(create_app(data_dir))
    response = client.put("/agent/v1/llm/config", json={"base_url": url, "model": "m", "api_key": "fixture"})
    assert response.status_code == 422


def test_transport_invalid_url_is_a_redacted_provider_error():
    def server(request):
        raise httpx.InvalidURL("fixture-secret")
    model = CompatibleProvider(configured(), transport=httpx.MockTransport(server))
    with pytest.raises(ProviderError) as error:
        model.complete([], [])
    assert error.value.code == "LLM_CONNECTION_FAILED"
    assert "fixture-secret" not in str(error.value)


def test_duplicate_tool_call_ids_rejected_before_execution():
    calls = [{"id": "same", "type": "function", "function": {"name": name, "arguments": "{}"}} for name in ("inspect_dataset", "chiller_analyze")]
    payload = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": calls}}]}
    model = CompatibleProvider(configured(), transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload)))
    with pytest.raises(ProviderError) as error:
        model.complete([], [])
    assert error.value.code == "LLM_INVALID_RESPONSE"


@pytest.mark.parametrize("payload", [{"choices": []}, {"choices": [{"message": {"role": "assistant", "tool_calls": [1]}}]},
                                    {"choices": [{"message": {"role": "assistant", "content": None}}]}])
def test_malformed_model_packets_fail_as_redacted_provider_error(payload):
    model = CompatibleProvider(configured(), transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload)))
    with pytest.raises(ProviderError) as error:
        model.complete([], [])
    assert error.value.code == "LLM_INVALID_RESPONSE"


def test_timeout_does_not_repeat_paid_request():
    calls = []
    def server(request):
        calls.append(request)
        raise httpx.ReadTimeout("fixture-secret")
    model = CompatibleProvider(configured(), transport=httpx.MockTransport(server))
    with pytest.raises(ProviderError) as error:
        model.complete([], [])
    assert error.value.code == "LLM_TIMEOUT" and len(calls) == 1
    assert "fixture-secret" not in str(error.value)


def test_config_http_masks_key_and_missing_setup_is_explicit(data_dir, monkeypatch):
    for name in ("OPENAI_API_KEY", "ENERGY_AGENT_LLM_API_KEY", "ENERGY_AGENT_LLM_MODEL", "ENERGY_AGENT_LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    client = TestClient(create_app(data_dir))
    assert client.get("/agent/v1/llm/config").json()["configured"] is False
    response = client.post("/agent/v1/chat/external", json={"message": "你好"})
    assert response.status_code == 503 and response.json()["detail"]["code"] == "LLM_NOT_CONFIGURED"
    response = client.put("/agent/v1/llm/config", json={"base_url": "https://fixture.example/v1", "model": "fixture", "api_key": "private-fixture-key"})
    assert response.status_code == 200
    assert response.json()["has_api_key"]
    assert "private-fixture-key" not in response.text
    assert "private-fixture-key" not in client.get("/agent/v1/llm/config").text
