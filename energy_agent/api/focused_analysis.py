"""Primary Python calculation -> focused1186 explanation application routes."""
from fastapi import APIRouter, Depends, HTTPException
from energy_agent.api.routes import call, runtime
from energy_agent.config.student_focused import StudentFocusedSettings
from energy_agent.contracts.chat import ChatReply, ChatRequest
from energy_agent.runtime import AgentRuntime
from energy_agent.storage.chat import SessionBusy

router = APIRouter(prefix='/agent/v1', tags=['学生智能分析'])


def settings():
    try:
        return StudentFocusedSettings.from_environment()
    except (ValueError, OSError):
        raise HTTPException(503, {'code': 'STUDENT_CONFIGURATION_INVALID', 'message': '学生服务连接配置无效。'}) from None


@router.get('/analysis/config')
def configuration():
    return settings().public()


@router.post('/analysis', response_model=ChatReply)
def analyze(request: ChatRequest, instance: AgentRuntime = Depends(runtime)):
    config = settings()
    if not config.enabled:
        raise HTTPException(503, {'code': 'STUDENT_ANALYSIS_DISABLED', 'message': '学生分析已停用。'})
    from energy_agent.agents.student_explanation import StudentExplanationService
    try:
        return call(StudentExplanationService(instance, config).send, request)
    except SessionBusy as exc:
        raise HTTPException(409, str(exc)) from exc
