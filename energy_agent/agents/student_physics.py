"""Calculate first, then ask the frozen student to select explanation topics.

No teacher provider, model tool planning, history-derived results or automatic
teacher fallback. This is a bounded development path, not free-text analysis.
"""
import math
import re
import threading

from energy_agent.agents.reporting import fallback_text, render_answer, result_facts
from energy_agent.contracts.chat import AnswerSegment, ChatContext, ToolAction
from energy_agent.contracts.student_analysis import StudentAnalysisDetails
from energy_agent.providers.student_selection import StudentSelectionClient, StudentSelectionError
from energy_agent.storage.chat import ChatStore
from energy_agent.tools.chiller.tool import AssetMismatch
from chiller_student.selection_contract import selection_request_from_context, parse_selection, canonical_hash
from chiller_student.selection_http import MODEL_ID, validate_api_body
from chiller_student.selection_presentation_v2 import present_selection_v2
from chiller_student.selection_topic_glossary import add_topic_definitions
from chiller_student.structured_physics import build_context_from_payloads

_SLOT = threading.BoundedSemaphore(1)
OWNERSHIP = '学生选择解释重点和核查项，数值、公式及报告正文由程序依据本次计算生成；未调用 DeepSeek。'
LIMITS = '当前为受限开发模式，回答相关性仍需审核；不覆盖控制达标、故障确诊、知识检索、多行或动态仿真分析。'


def question_scope_reason(question):
    """Conservative explicit unsupported requests, not a semantic classifier.

    Every resulting report stays `limited`, including requests this small guard
    cannot identify. Passing it never certifies that all user intent is covered.
    """
    if re.search(r'控制.{0,12}(达标|合格|精度|稳定|不好|好不好|偏差)|是否.{0,6}(达标|超差)|'
                 r'(出水|设定).{0,30}(没达到|未达到|没达标|不达标|控制不好)|'
                 r'(温度|设定值).{0,12}(偏离|偏差|差多少)|'
                 r'\b(setpoint tracking|control compliance)\b', question, re.I):
        return '控制偏差与控制是否合格尚未接入当前学生任务。'
    if re.search(r'(确诊|什么故障|哪种故障|故障概率|维修方案|怎么维修|检修步骤|故障原因)|'
                 r'(查找|查询|检索|根据|按照|引用).{0,15}(手册|教材|文献|标准)|'
                 r'(运行|执行|帮我做|请做).{0,6}(动态仿真|仿真)|'
                 r'(预测|趋势分析|优化设定|优化控制|批量分析|多台机组)', question):
        return '该问题包含当前单行性能解释之外的诊断、知识或仿真任务。'
    return None


def reference_segments(text, facts):
    """Link code-owned [F…] references; never apply this to arbitrary model prose."""
    by_id = {f.fact_id: f for f in facts}
    segments, offset = [], 0
    for match in re.finditer(r'\[(F\d+)\]', text):
        if match.group(1) not in by_id:
            raise ValueError('Unknown program report fact')
        if match.start() > offset:
            segments.append(AnswerSegment(text=text[offset:match.start()]))
        segments.append(AnswerSegment(text=match.group(), fact_id=match.group(1)))
        offset = match.end()
    if offset < len(text):
        segments.append(AnswerSegment(text=text[offset:]))
    return segments


def prepare_physics_selection(repository, info, result, facts, question):
    """Validate real immutable artifacts, then build the unchanged v1 request."""
    actual = repository.get_dataset(info.dataset_id).info
    artifact = repository.get_run(result['run_id'])
    expected = {'asset_id': info.asset_id, 'dataset_id': info.dataset_id,
                'task': 'physics', 'preview_rows': 0, 'simulation': None}
    if (actual != info or artifact['result'] != result or result['request'] != expected
            or result['asset_id'] != info.asset_id or result['dataset_id'] != info.dataset_id
            or result['dataset_version'] != info.version or result['task'] != 'physics'
            or result['input_rows'] != 1 or result['output_rows'] != 1
            or artifact['model_output']['metadata']['operation'] != 'calculate'
            or artifact['model_output']['metadata']['schema'] != info.effective_schema.model_dump(mode='json')):
        raise ValueError('Current physics result binding mismatch')
    for fact in facts:
        if fact.run_id != result['run_id'] or fact.dataset_id not in (None, info.dataset_id):
            raise ValueError('Cross-run fact')
        value = artifact
        for key in fact.pointer.lstrip('/').split('/'):
            value = value[int(key)] if isinstance(value, list) else value[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value != fact.value:
            raise ValueError('Physics fact pointer mismatch')
    payload = {key: result[key] for key in ('status', 'run_id', 'missing_inputs', 'warnings', 'errors', 'notes')}
    payload['facts'] = [f.model_dump(mode='json') for f in facts]
    context = build_context_from_payloads({'status': 'success', 'dataset': info.model_dump(mode='json')}, payload)
    compressed = add_topic_definitions(selection_request_from_context(question, context))
    body = {'model': MODEL_ID, 'messages': compressed['messages'], 'stream': False,
            'max_tokens': 2048, 'temperature': 0}
    validate_api_body(body)
    return context, body, canonical_hash(compressed)


class StudentPhysicsService:
    model_id = MODEL_ID
    analysis_backend = 'student_physics'
    ownership_notice = OWNERSHIP
    scope_reason = staticmethod(question_scope_reason)

    def details(self):
        return StudentAnalysisDetails()

    def __init__(self, runtime, settings, *, client=None):
        self.runtime, self.settings = runtime, settings
        self.store = ChatStore(runtime.repository)
        self.client = client or StudentSelectionClient(settings)

    def send(self, request):
        if not self.settings.enabled:
            raise ValueError('学生物理分析未启用，请先设置本机学生连接配置。')
        if request.context and request.context.dataset_id:
            info = self.runtime.repository.get_dataset(request.context.dataset_id).info
            if info.asset_id != request.context.asset_id:
                raise AssetMismatch('会话设备与数据集不一致')
        session, turn = self.store.begin(request, self.model_id, analysis_backend=self.analysis_backend)
        detail = turn.student_analysis = self.details()
        turn.report_mode = 'message'
        turn.notices = [self.ownership_notice, LIMITS,
                        '本模式只使用本条完整问题和绑定数据，不理解“上一条/刚才”等跨问题指代；每次重新计算。']
        results = []
        def audit(kind, payload):
            self.store.record_audit(turn.turn_id, kind, payload)
        try:
            context = ChatContext.model_validate(session['context'])
            info = self.runtime.repository.get_dataset(context.dataset_id).info if context.dataset_id else None
            audit('student_context', {'binding': context.model_dump(mode='json'),
                  'dataset_info': info.model_dump(mode='json') if info else None,
                  'user_message': request.message, 'prior_turns_used': False,
                  'integration_version': detail.integration_version, 'teacher_calls': 0})
            reason = ('请先选择单条工况数据集。' if info is None else
                      '学生模式暂不支持仿真设置；请新建不含仿真配置的对话。' if context.simulation else
                      '学生模式暂只支持单条工况，多行数据请使用计算工作台。' if info.row_count != 1 else
                      '该流量单位未进入当前学生协议，请先核对并使用支持的单位。'
                      if info.effective_schema.flow_unit not in ('kg/s', 'm3/h', 'us_gpm') else
                      self.scope_reason(request.message))
            if reason:
                detail.state = 'out_of_scope'
                turn.status = 'needs_input' if info is None else 'limited'
                turn.error_code, turn.answer = 'STUDENT_SCOPE_UNSUPPORTED', reason + ' 本次未调用学生或 DeepSeek。'
                turn.segments = [AnswerSegment(text=turn.answer)]
            else:
                self._analyze(request, session, turn, info, results, audit)
        except StudentSelectionError as exc:
            detail.state = 'failed'
            turn.status, turn.error_code = 'failed', exc.code
            audit('student_error', {'error_code': exc.code, 'raw_model_response': exc.raw_model_response,
                                    'teacher_calls': 0, 'retries': 0})
            turn.notices.append('学生服务未生成有效报告，已保留本次工具结果；未自动重试或切换教师。')
            self._fallback(turn, results)
        except Exception:
            detail.state = 'failed'
            turn.status, turn.error_code = 'failed', 'STUDENT_PHYSICS_EXECUTION_FAILED'
            audit('student_error', {'error_code': turn.error_code, 'teacher_calls': 0})
            turn.notices.append('计算或证据核验未完成；未采用学生报告，也未调用 DeepSeek。')
            self._fallback(turn, results)
        self.store.finish(session, turn, [])
        audit('student_final', {'public_turn': turn.model_dump(mode='json'), 'teacher_calls': 0,
                               'training_label_approved': False, 'automatic_semantic_pass': False})
        return turn

    def _analyze(self, request, session, turn, info, results, audit):
        self.store.renew(turn)
        result = self.runtime.analyze({'asset_id': info.asset_id, 'dataset_id': info.dataset_id,
                                      'task': 'physics', 'preview_rows': 0}).model_dump(mode='json')
        # Do not publish numbers before result identity has been checked.
        facts = result_facts(result, session['fact_counter'])
        artifact = self.runtime.repository.get_run(result['run_id'])
        if (artifact['result'] != result or result['dataset_id'] != info.dataset_id
                or result['asset_id'] != info.asset_id or result['dataset_version'] != info.version
                or result['task'] != 'physics'):
            raise ValueError('Current calculation identity mismatch')
        turn.tool_run_ids = [result['run_id']]
        turn.tool_calls = [ToolAction(name='chiller_analyze', task='physics', status=result['status'], run_id=result['run_id'])]
        turn.facts = facts
        results.append(result)
        audit('student_physics_result', {'result': result, 'facts': [f.model_dump(mode='json') for f in facts],
                                         'execution_owner': 'python', 'teacher_calls': 0})
        if result['status'] not in ('success', 'partial') or result['errors']:
            turn.status = 'needs_input' if result['status'] == 'needs_input' else 'failed'
            turn.error_code = 'PHYSICS_RESULT_UNAVAILABLE'
            self._fallback(turn, results)
            return
        try:
            context, body, digest = prepare_physics_selection(self.runtime.repository, info, result, facts, request.message)
        except (ValueError, KeyError, TypeError, IndexError):
            # Failed evidence verification is not a valid numerical fallback.
            turn.facts, turn.tool_run_ids, turn.tool_calls = [], [], []
            results.clear()
            raise
        detail = turn.student_analysis
        detail.request_sha256, detail.evidence_sha256 = digest, context['source_sha256']
        detail.evidence_markdown = present_selection_v2(context, {'schema_version': 'physics_selection_v1',
                                    'answer_topics': ['metrics'], 'followup_check_ids': []})['evidence_markdown']
        # Evidence is program-owned; this placeholder choice is never sent,
        # saved as the student's choice or included in the primary answer.
        if not _SLOT.acquire(blocking=False):
            raise StudentSelectionError('STUDENT_LOCAL_BUSY_NO_RETRY')
        try:
            self.store.renew(turn)
            audit('student_request', {'request': body, 'request_sha256': digest, 'teacher_calls': 0})
            turn.model_calls = 1
            response = self.client.complete(body)
            audit('student_response', response)
            raw = response['response']
            choice = raw.get('choices')
            if (raw.get('model') != MODEL_ID or not isinstance(choice, list) or len(choice) != 1
                    or choice[0].get('finish_reason') != 'stop'
                    or choice[0].get('message', {}).get('role') != 'assistant'):
                raise StudentSelectionError('STUDENT_INVALID_SELECTION_RESPONSE')
            content = choice[0]['message'].get('content')
            try:
                selection = parse_selection(content, context)
            except (ValueError, TypeError):
                raise StudentSelectionError('STUDENT_INVALID_SELECTION_RESPONSE', content) from None
            presentation = present_selection_v2(context, selection)
            turn.answer = presentation['answer_markdown']
            turn.segments = reference_segments(turn.answer, facts)
            turn.report_mode, turn.status = 'student_selection', 'limited'
            detail.state, detail.selection = 'reported', selection
            detail.upstream_service_identity = response['reported_service_identity']
            detail.elapsed_seconds = response['elapsed_seconds']
            audit('student_presentation', {'presentation': presentation,
                  'application_mode': detail.mode, 'teacher_calls': 0, 'model_selection_repaired': False})
        finally:
            _SLOT.release()

    @staticmethod
    def _fallback(turn, results):
        if results:
            turn.answer, turn.segments = render_answer(fallback_text(turn.facts, results), turn.facts)
            turn.report_mode = 'tool_facts'
        else:
            turn.answer = '本次学生物理分析未完成。请检查数据绑定、计算结果或服务配置。'
            turn.segments = [AnswerSegment(text=turn.answer)]
            turn.report_mode = 'message'
