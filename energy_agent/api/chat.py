"""Conversation and provider-configuration endpoints."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
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
from energy_agent.config.student_shadow import StudentShadowSettings
from energy_agent.providers.student_shadow import schedule_shadow, latest_shadow, recent_shadow

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
def primary_chat(request: ChatRequest, instance: AgentRuntime = Depends(runtime)):
    """Default API follows the same compute-first focused1186 path as the page."""
    from energy_agent.api.focused_analysis import analyze
    return analyze(request, instance)


@router.post("/chat/external", response_model=ChatReply)
def chat(request: ChatRequest, background_tasks: BackgroundTasks, instance: AgentRuntime = Depends(runtime)):
    try:
        reply = call(ChatService(instance, call(provider, instance)).send, request)
        schedule_shadow(background_tasks, instance.repository, reply.model_dump(mode="json"))
        return reply
    except ProviderError as exc:
        raise provider_http_error(exc) from exc
    except SessionBusy as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/student-shadow/config")
def student_shadow_config():
    try:
        return StudentShadowSettings.from_environment().public()
    except (ValueError, OSError):
        return {"enabled": False, "configuration_error": True, "primary_model_changed": False}


@router.get("/student-shadow/recent")
def student_shadow_recent(limit: int = Query(3, ge=1, le=20), instance: AgentRuntime = Depends(runtime)):
    return {"records": call(recent_shadow, instance.repository, limit), "training_labels_approved": False}


@router.get("/chat/sessions/{session_id}/turns/{turn_id}/student-shadow")
def student_shadow_result(session_id: str, turn_id: str, instance: AgentRuntime = Depends(runtime)):
    call(ChatStore(instance.repository).get_turn, session_id, turn_id)
    return call(latest_shadow, instance.repository, turn_id)


@router.get("/chat/sessions/{session_id}/turns/{turn_id}/student-shadow/report")
def student_shadow_report(session_id: str, turn_id: str, instance: AgentRuntime = Depends(runtime)):
    turn = call(ChatStore(instance.repository).get_turn, session_id, turn_id)
    result = call(latest_shadow, instance.repository, turn_id)
    lines = ["# 页面回答与学生对照", "用户问题：" + turn.user_message,
             "## 页面原回答", turn.answer, "## 学生对照状态", result["state"]]
    if result["state"] == "recorded":
        record = result["shadow"]
        lines += ["模型原始选择：", "```json\n" + record["raw_model_response"] + "\n```",
                  "## 程序按学生选择生成的报告", record["presentation"]["answer_markdown"],
                  "数值、公式及固定判断边界由程序提供；原模型选项未修复，内容仍待审核。"]
    else:
        lines += ["本条对照尚未完成或未进入试用范围，请刷新学生状态。"]
    return PlainTextResponse("\n\n".join(lines) + "\n", media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="{turn_id}_student_shadow.md"'})


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
