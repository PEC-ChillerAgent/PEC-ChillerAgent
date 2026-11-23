"""Background-only student comparison after the primary turn is committed."""
from copy import deepcopy
import json, math, threading, time
from energy_agent.config.student_shadow import StudentShadowSettings, EXPECTED_IDENTITY
from energy_agent.storage.chat import ChatStore
from energy_agent.storage.repository import utc_now
from energy_agent.providers.audit import clean_trace
from chiller_student.selection_shadow_bridge import prepare_shadow_from_events,present_shadow_response
from energy_agent.providers.student_selection import StudentSelectionClient, StudentSelectionError as ShadowError

_SLOT=threading.BoundedSemaphore(1)
FINAL_STATES={'recorded','failed','skipped','skipped_busy','configuration_error'}


class ShadowScopeError(ValueError):
    def __init__(self,code):super().__init__(code);self.code=code


def _record(repository,turn_id,payload,secret=''):
    # Shadow storage failures never change the committed primary answer.
    try:ChatStore(repository).record_audit(turn_id,'student_shadow',clean_trace({'created_at':utc_now(),**payload},secret))
    except Exception:pass


def latest_shadow(repository,turn_id):
    with repository._connection() as db:
        row=db.execute("SELECT payload FROM chat_audit_events WHERE turn_id=? AND kind='student_shadow' ORDER BY id DESC LIMIT 1",(turn_id,)).fetchone()
    return json.loads(row[0]) if row else {'state':'not_recorded'}


def _events(repository,turn_id):
    with repository._connection() as db:
        rows=db.execute("SELECT kind,payload FROM chat_audit_events WHERE turn_id=? AND kind IN ('context','tool_result') ORDER BY id",(turn_id,)).fetchall()
    return [{'kind':r[0],'payload':json.loads(r[1])} for r in rows]


def _pointer(artifact,pointer):
    if not isinstance(pointer,str) or not pointer.startswith('/'):raise ValueError('Invalid fact pointer')
    node=artifact
    for part in pointer[1:].split('/'):
        key=part.replace('~1','/').replace('~0','~')
        node=node[int(key)] if isinstance(node,list) else node[key]
    return node


def prepare_current_turn(repository,public_turn):
    if public_turn['status']!='completed':raise ValueError('Primary turn is not completed')
    events=_events(repository,public_turn['turn_id'])
    if not any(e['kind']=='tool_result' and e['payload'].get('call',{}).get('function',{}).get('name')=='chiller_analyze'
               for e in events):
        raise ShadowScopeError('NO_CURRENT_PHYSICS_RUN')
    prepared=prepare_shadow_from_events(public_turn,events)
    context=next(e['payload'] for e in events if e['kind']=='context')
    info=context['dataset_info'];actual=repository.get_dataset(info['dataset_id']).info.model_dump(mode='json')
    if actual!=info:raise ValueError('Audited dataset metadata differs from repository')
    artifact=repository.get_run(prepared['physics_run_id']);run=artifact['result']
    if run['task']!='physics' or run['dataset_id']!=info['dataset_id'] or run['asset_id']!=info['asset_id']:
        raise ValueError('Run/dataset binding differs from repository')
    if run['input_rows']!=1 or run['output_rows']!=1:raise ValueError('Only one-row physics supported')
    for fact in prepared['context']['facts'].values():
        value=_pointer(artifact,fact['pointer'])
        if type(value) not in (int,float) or not math.isfinite(value) or value!=fact['value']:
            raise ValueError('Audited fact differs from saved physical result')
    return prepared


class StudentShadowClient:
    def __init__(self,settings,*,transport=None):self.settings=settings;self.transport=transport
    def compare(self,prepared):
        result=StudentSelectionClient(self.settings,transport=self.transport).complete(prepared['body'])
        response=result['response']
        try:shadow=present_shadow_response(prepared,response)
        except (KeyError,ValueError,TypeError,IndexError):
            raw=response.get('choices',[{}])[0].get('message',{}).get('content')
            raise ShadowError('STUDENT_INVALID_SELECTION_RESPONSE',raw) from None
        return {'state':'recorded','mode':'shadow_only','student_request':prepared['body'],
                'student_http_response':response,'shadow':shadow,
                'reported_service_identity':result['reported_service_identity'],
                'elapsed_seconds':result['elapsed_seconds'],'semantic_review':'pending',
                'domain_accuracy':None,'primary_answer_changed':False,
                'teacher_label_approved':False,'app_shadow_hook_enabled':True}


def process_shadow(repository,public_turn,settings,*,transport=None):
    turn_id=public_turn['turn_id']
    try:
        if latest_shadow(repository,turn_id).get('state') in FINAL_STATES:return
        if not _SLOT.acquire(blocking=False):
            _record(repository,turn_id,{'state':'skipped_busy','reason_code':'LOCAL_SHADOW_SLOT_BUSY','primary_answer_changed':False});return
        try:
            _record(repository,turn_id,{'state':'started','primary_answer_changed':False})
            try:prepared=prepare_current_turn(repository,public_turn)
            except ShadowScopeError as exc:
                _record(repository,turn_id,{'state':'skipped','reason_code':exc.code,'primary_answer_changed':False});return
            except (ValueError,KeyError,LookupError,TypeError):
                _record(repository,turn_id,{'state':'skipped','reason_code':'OUTSIDE_SINGLE_ROW_PHYSICS_SCOPE_OR_BINDING_FAILED','primary_answer_changed':False});return
            try:result=StudentShadowClient(settings,transport=transport).compare(prepared)
            except ShadowError as exc:
                _record(repository,turn_id,{'state':'failed','error_code':exc.code,'raw_model_response':exc.raw_model_response,
                    'primary_answer_changed':False,'semantic_review':'pending'});return
            _record(repository,turn_id,result)
        finally:_SLOT.release()
    except Exception:
        _record(repository,turn_id,{'state':'failed','error_code':'SHADOW_EXECUTION_FAILED','primary_answer_changed':False})


def schedule_shadow(background_tasks,repository,public_turn):
    # API calls this only after ChatService has finished/audited its answer.
    try:
        settings=StudentShadowSettings.from_environment()
        if not settings.enabled:return
        previous=latest_shadow(repository,public_turn['turn_id']).get('state')
        if previous in FINAL_STATES|{'queued','started'}:return
        _record(repository,public_turn['turn_id'],{'state':'queued','mode':'shadow_only','primary_answer_changed':False})
        background_tasks.add_task(process_shadow,repository,deepcopy(public_turn),settings)
    except Exception:
        _record(repository,public_turn['turn_id'],{'state':'configuration_error','primary_answer_changed':False})


def recent_shadow(repository,limit=3):
    if not 1<=limit<=20:raise ValueError('Limit must be1..20')
    with repository._connection() as db:
        rows=db.execute("""SELECT e.turn_id,e.payload,t.public FROM chat_audit_events e
            JOIN (SELECT turn_id,MAX(id) AS latest FROM chat_audit_events WHERE kind='student_shadow' GROUP BY turn_id) q ON e.id=q.latest
            JOIN chat_turns t ON t.id=e.turn_id ORDER BY e.id DESC LIMIT ?""",(limit,)).fetchall()
    return [{'turn':json.loads(r[2]),'student_shadow':json.loads(r[1]),'source_events':_events(repository,r[0]),
             'training_label_approved':False} for r in rows]
