"""Opt-in physical analysis without the primary LLM configuration/provider."""
import json

from fastapi import APIRouter, Depends, HTTPException, Query

from energy_agent.agents.student_physics import StudentPhysicsService
from energy_agent.api.routes import call, runtime
from energy_agent.config.student_analysis import StudentAnalysisSettings
from energy_agent.contracts.chat import ChatRequest, ChatReply
from energy_agent.runtime import AgentRuntime
from energy_agent.storage.chat import ChatStore, SessionBusy

router = APIRouter(prefix='/agent/v1', tags=['学生物理分析 · 开发模式'])

def explanation_settings():
    from energy_agent.config.student_explanation import StudentExplanationSettings
    try:return StudentExplanationSettings.from_environment()
    except (ValueError,OSError,KeyError,TypeError):
        raise HTTPException(503,{'code':'STUDENT_EXPLANATION_RELEASE_UNAVAILABLE','message':'学生解释候选尚未完成发布配置。'}) from None

@router.get('/student-explanation/config')
def explanation_configuration():
    return explanation_settings().public()

@router.post('/student-explanation',response_model=ChatReply)
def explain(request:ChatRequest,instance:AgentRuntime=Depends(runtime)):
    config=explanation_settings()
    if not config.enabled:raise HTTPException(503,{'code':'STUDENT_EXPLANATION_DISABLED','message':'学生自然语言解释尚未启用。'})
    from energy_agent.agents.student_explanation import StudentExplanationService
    try:return call(StudentExplanationService(instance,config).send,request)
    except SessionBusy as exc:raise HTTPException(409,str(exc)) from exc


def settings():
    try:
        return StudentAnalysisSettings.from_environment()
    except (ValueError, OSError):
        raise HTTPException(503, {'code': 'STUDENT_CONFIGURATION_INVALID', 'message': '学生连接环境配置无效。'}) from None


@router.get('/student-analysis/config')
def configuration():
    return settings().public()


@router.post('/student-analysis', response_model=ChatReply)
def analyze(request: ChatRequest, instance: AgentRuntime = Depends(runtime)):
    config = settings()
    if not config.enabled:
        raise HTTPException(503, {'code': 'STUDENT_ANALYSIS_DISABLED', 'message': '学生物理分析尚未启用。'})
    try:
        return call(StudentPhysicsService(instance, config).send, request)
    except SessionBusy as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/student-analysis/recent')
def recent(limit: int = Query(3, ge=1, le=20), instance: AgentRuntime = Depends(runtime)):
    return _recent('student_physics',limit,instance)

@router.get('/student-explanation/recent')
def explanation_recent(limit: int = Query(3,ge=1,le=20), instance: AgentRuntime = Depends(runtime)):
    return _recent('student_explanation',limit,instance)

def _recent(backend,limit,instance):
    # Only student-path events; never expose legacy provider wire/reasoning.
    ChatStore(instance.repository)
    with instance.repository._connection() as db:
        rows = db.execute("SELECT id,public FROM chat_turns WHERE json_extract(public,'$.analysis_backend') = ? ORDER BY rowid DESC LIMIT ?", (backend,limit)).fetchall()
        records = []
        for turn_id, public in rows:
            events = db.execute("SELECT kind,payload FROM chat_audit_events WHERE turn_id=? AND kind LIKE 'student_%' ORDER BY id", (turn_id,)).fetchall()
            records.append({'turn': json.loads(public), 'events': [{'kind': k, 'payload': json.loads(v)} for k, v in events]})
    return {'records': records, 'training_labels_approved': False, 'independent_test': False}


@router.get('/student-analysis/sessions/{session_id}/turns/{turn_id}/review')
@router.get('/student-explanation/sessions/{session_id}/turns/{turn_id}/review')
def review(session_id: str, turn_id: str, instance: AgentRuntime = Depends(runtime)):
    turn = call(ChatStore(instance.repository).get_turn, session_id, turn_id)
    if turn.analysis_backend not in ('student_physics','student_explanation'):
        raise HTTPException(404, 'Not a student physical analysis turn')
    allowed = {'student_context', 'student_physics_result', 'student_request', 'student_response',
               'student_presentation', 'student_error', 'student_final', 'student_explanation_check',
               'student_planned_evidence', 'student_explanation_quality'}
    with instance.repository._connection() as db:
        rows = db.execute('SELECT kind,payload FROM chat_audit_events WHERE turn_id=? ORDER BY id', (turn_id,)).fetchall()
    events = [{'kind': key, 'payload': json.loads(value)} for key, value in rows if key in allowed]
    return {'turn': turn.model_dump(mode='json'), 'events': events,
            'artifacts': [call(instance.repository.get_run, run_id) for run_id in turn.tool_run_ids],
            'training_label_approved': False, 'independent_test': False}
