"""Conversation and provider-configuration endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pathlib import Path

from energy_agent.api.routes import call, runtime
from energy_agent.agents.chat import ChatService
from energy_agent.agents.reporting import markdown_report
from energy_agent.config.llm import LLMConfigStore
from energy_agent.contracts.chat import ChatReply, ChatRequest, LLMConfigUpdate
from energy_agent.providers.compatible import CompatibleProvider, ProviderError
from energy_agent.runtime import AgentRuntime
from energy_agent.storage.chat import ChatStore, SessionBusy

router = APIRouter(prefix="/agent/v1", tags=["智能分析 · 第二阶段"])
page_router = APIRouter()
WEB_DIR = Path(__file__).resolve().parents[2] / "chiller_app" / "web"


@page_router.get("/chat", include_in_schema=False)
def chat_page():
    return FileResponse(WEB_DIR / "chat.html")


def config_store(instance: AgentRuntime) -> LLMConfigStore:
    return LLMConfigStore(instance.repository.data_dir)


def provider(instance: AgentRuntime) -> CompatibleProvider:
    return CompatibleProvider(config_store(instance).load())


def provider_http_error(exc: ProviderError) -> HTTPException:
    return HTTPException(503, {"code": exc.code, "message": str(exc)})


@router.get("/llm/config")
def get_config(instance: AgentRuntime = Depends(runtime)):
    return call(config_store(instance).public)


@router.put("/llm/config")
def save_config(update: LLMConfigUpdate, instance: AgentRuntime = Depends(runtime)):
    return call(config_store(instance).save, update)


@router.post("/llm/test")
def test_connection(instance: AgentRuntime = Depends(runtime)):
    try:
        model = call(provider, instance)
        message = model.complete([{"role": "user", "content": "连接测试，请简短回复连接成功。"}], [])
        return {"connected": True, "model": model.settings.model, "message": (message.get("content") or "")[:200]}
    except ProviderError as exc:
        raise provider_http_error(exc) from exc


@router.post("/chat", response_model=ChatReply)
def chat(request: ChatRequest, instance: AgentRuntime = Depends(runtime)):
    try:
        return call(ChatService(instance, call(provider, instance)).send, request)
    except ProviderError as exc:
        raise provider_http_error(exc) from exc
    except SessionBusy as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/chat/sessions")
def sessions(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), instance: AgentRuntime = Depends(runtime)):
    return ChatStore(instance.repository).list_sessions(offset=offset, limit=limit)


@router.get("/chat/sessions/{session_id}")
def session(session_id: str, instance: AgentRuntime = Depends(runtime)):
    return call(ChatStore(instance.repository).get_session, session_id)


@router.get("/chat/sessions/{session_id}/turns/{turn_id}/report")
def report(session_id: str, turn_id: str, instance: AgentRuntime = Depends(runtime)):
    turn = call(ChatStore(instance.repository).get_turn, session_id, turn_id)
    return PlainTextResponse(markdown_report(turn), media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="{turn.turn_id}.md"'})
