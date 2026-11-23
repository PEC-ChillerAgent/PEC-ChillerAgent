"""Student-authored physics explanations after real Python tools."""
import json
from energy_agent.agents.student_physics import StudentPhysicsService,prepare_physics_selection,question_scope_reason,_SLOT
from energy_agent.contracts.chat import AnswerSegment,ToolAction
from energy_agent.contracts.student_analysis import StudentAnalysisDetails
from energy_agent.providers.student_explanation import StudentExplanationClient
from energy_agent.providers.student_selection import StudentSelectionError
from energy_agent.storage.chat import ChatStore
from chiller_student.evidence_explanation import prepare_explanation
from chiller_student.joint_physics_support import with_workflow,canonical_hash
from chiller_student.readable_physics_evidence import readable_request
from chiller_student.explanation_http import MODEL_ID,make_body
from chiller_student.explanation_protocol import validate_explanation
from chiller_student.explanation_number_gate_v3 import render_answer,verified_redundant_zero_counts,VERSION as NUMBER_GATE_VERSION
from chiller_student.explanation_consistency_v2 import check_consistency
from chiller_student.selection_presentation_v2 import present_selection_v2

def bind_planned_facts(request,artifact,validator=None):
    """Every added count must point to this actual saved Python ToolResult."""
    import math
    from energy_agent.contracts.chat import ChatFact
    from chiller_student.planned_explanation import validate_request
    payload=(validator or validate_request)(request);facts=[ChatFact.model_validate(f) for f in payload['tool_evidence']['facts']]
    for f in facts:
        if f.run_id!=artifact['result']['run_id'] or f.dataset_id not in (None,artifact['result']['dataset_id']):raise ValueError('Cross-run planned fact')
        value=artifact
        for k in f.pointer.lstrip('/').split('/'):value=value[int(k)] if isinstance(value,list) else value[k]
        if type(value) not in (int,float) or not math.isfinite(value) or value!=f.value:raise ValueError('Planned fact pointer mismatch')
    return facts

def explanation_scope_reason(question):
    # A status question is not an instruction to launch a simulation. Remove
    # only this explicit construction before the conservative scope check;
    # another sentence requesting an actual simulation remains blocked.
    import re
    status_only=re.sub(r'(?:是否|有没有|已经)(?:实际)?(?:执行|运行|完成)(?:了|过)?(?:动态)?(?:仿真|模拟)', '查询本次计算执行状态', question)
    status_only=re.sub(r'(?:是否|能否|可否|能不能|可不可以)(?:直接|据此|由此|仅凭[^。；\n]{0,10}){0,2}(?:确诊|诊断|认定|断言|确定)[^。；\n]{0,8}(?:故障|损失)', '查询本次证据是否足够', status_only)
    status_only=re.sub(r'(?:不能|不可以)(?:据此|直接)?确诊[^。；\n]{0,8}故障', '证据不足的边界', status_only)
    status_only=re.sub(r'这(?:些)?(?:结果|数值|残差|证据|数据|记录)?(?:能|可以|足以)(?:说明|判断|确定)[^。；\n]{0,8}(?:什么故障|哪种故障)(?:吗|么|？|\?)', '查询当前证据边界', status_only)
    return question_scope_reason(status_only)

class StudentExplanationService(StudentPhysicsService):
    model_id=MODEL_ID
    analysis_backend='student_explanation'
    scope_reason=staticmethod(explanation_scope_reason)
    ownership_notice='先由 Python 计算，再由学生撰写解释；数值由计算事实引用填入。未调用 DeepSeek，解释仍需核对。'

    def __init__(self,runtime,settings,*,client=None):
        self.runtime,self.settings=runtime,settings
        self.store=ChatStore(runtime.repository)
        self.client=client or StudentExplanationClient(settings)
        self.number_renderer=render_answer
        self.number_gate_version=NUMBER_GATE_VERSION
        gate=getattr(settings,'number_gate_version','v3')
        if gate=='v4':
            from chiller_student.explanation_number_gate_v4 import render_answer as v4,VERSION as V4_VERSION
            self.number_renderer,self.number_gate_version=v4,V4_VERSION
        elif gate!='v3':raise ValueError('Unknown student explanation number gate')
        self.quality_guard_enabled=getattr(settings,'quality_guard_enabled',False)
        from chiller_student.planned_explanation import MODEL_ID as planned_model
        self.planned_contract=bool(settings.service_identity and settings.service_identity['model']==planned_model)
        from chiller_student.focused_contract import MODEL_ID as focused_model
        self.focused_contract=bool(settings.service_identity and settings.service_identity['model']==focused_model)
        self.consistency_checker=check_consistency
        if self.planned_contract:
            from chiller_student.explanation_number_gate_v6 import render_answer as v6,VERSION as V6_VERSION
            from chiller_student.typed_physics_claims import check_claims
            self.model_id=planned_model
            self.number_renderer,self.number_gate_version=v6,V6_VERSION
            self.consistency_checker=check_claims;self.quality_guard_enabled=True
        if self.focused_contract:
            from chiller_student.focused_output import render_answer as v8,VERSION as V8_VERSION
            from chiller_student.typed_physics_claims_v3 import check_claims
            self.model_id=focused_model
            self.number_renderer,self.number_gate_version=v8,V8_VERSION
            self.consistency_checker=check_claims;self.quality_guard_enabled=True

    def details(self):
        # Set model ownership only after a validated answer is actually shown.
        version='student-focused1186-20261123.1' if self.focused_contract else 'student-planned-explanation-20261118.1' if self.planned_contract else 'student-explanation-20261117.4' if self.number_gate_version!=NUMBER_GATE_VERSION or self.quality_guard_enabled else 'student-explanation-20261117.3'
        return StudentAnalysisDetails(integration_version=version,mode='student_explanation_development_v1')

    def _analyze(self,request,session,turn,info,results,audit):
        self.store.renew(turn)
        result=self.runtime.analyze({'asset_id':info.asset_id,'dataset_id':info.dataset_id,'task':'physics','preview_rows':0}).model_dump(mode='json')
        artifact=self.runtime.repository.get_run(result['run_id'])
        if artifact['result']!=result:raise ValueError('Calculation identity mismatch')
        # IDs are scoped to the individual turn and its run. Fresh F1... matches
        # the trained request contract; prior-turn fact IDs are never reused as evidence.
        prepared=prepare_explanation(info.model_dump(mode='json'),artifact,request.message)
        facts=prepared['facts']
        context,_,_=prepare_physics_selection(self.runtime.repository,info,result,facts,request.message)
        turn.facts=facts;turn.tool_run_ids=[result['run_id']]
        turn.tool_calls=[ToolAction(name='chiller_analyze',task='physics',status=result['status'],run_id=result['run_id'])]
        results.append(result)
        audit('student_physics_result',{'result':result,'facts':[f.model_dump(mode='json') for f in facts],'execution_owner':'python','teacher_calls':0})
        detail=turn.student_analysis
        detail.evidence_sha256=prepared['evidence_sha256']
        detail.evidence_markdown=present_selection_v2(context,{'schema_version':'physics_selection_v1','answer_topics':['metrics'],'followup_check_ids':[]})['evidence_markdown']
        evidence=readable_request(with_workflow({'messages':prepared['messages'],'tools':None}))
        if self.planned_contract or self.focused_contract:
            from chiller_student.task_explanation import from_v1
            if self.focused_contract:
                from chiller_student.focused_contract import from_task_request,make_body as planned_body,validate_request as request_validator
            else:
                from chiller_student.planned_explanation import from_task_request,make_body as planned_body,validate_request as request_validator
            evidence=from_task_request(from_v1(evidence))
            try:facts=bind_planned_facts(evidence,artifact,validator=request_validator)
            except (ValueError,KeyError,IndexError,TypeError):
                turn.facts=[];turn.tool_run_ids=[];turn.tool_calls=[];results.clear();raise
            turn.facts=facts;body=planned_body(evidence)
            audit('student_planned_evidence',{'facts':[f.model_dump(mode='json') for f in facts],
                'tasks':json.loads(evidence['messages'][1]['content'])['tool_evidence']['answer_task_plan'],
                'run_id':result['run_id'],'teacher_calls':0,'automatic_semantic_pass':False})
        else:body=make_body(evidence)
        detail.request_sha256=canonical_hash(evidence)
        if not _SLOT.acquire(blocking=False):raise StudentSelectionError('STUDENT_LOCAL_BUSY_NO_RETRY')
        try:
            self.store.renew(turn);audit('student_request',{'request':body,'request_sha256':detail.request_sha256,'teacher_calls':0})
            turn.model_calls=1;response=self.client.complete(body);audit('student_response',response)
            raw=response['response'];choices=raw.get('choices')
            if (raw.get('model')!=self.model_id or not isinstance(choices,list) or len(choices)!=1
                or choices[0].get('finish_reason')!='stop' or choices[0].get('message',{}).get('role')!='assistant'):
                raise StudentSelectionError('STUDENT_INVALID_EXPLANATION_RESPONSE')
            content=choices[0]['message'].get('content')
            try:
                presentation=validate_explanation(content,facts,renderer=self.number_renderer)
                presentation['numeric_gate_version']=self.number_gate_version
                presentation['verified_redundant_zero_counts']=verified_redundant_zero_counts(presentation['model_authored_answer_template'],facts)
                consistency=self.consistency_checker(content,evidence)
            except (ValueError,TypeError,KeyError):
                raise StudentSelectionError('STUDENT_EXPLANATION_FORMAT_REJECTED',content) from None
            detail.consistency_check=consistency
            audit('student_explanation_check',{'presentation':presentation,'consistency':consistency,'automatic_semantic_pass':False})
            if self.quality_guard_enabled:
                from chiller_student.explanation_quality import check_repetition
                quality=check_repetition(presentation['model_authored_answer_template'])
                audit('student_explanation_quality',quality)
                if not quality['passed_repetition_check']:
                    raise StudentSelectionError('STUDENT_EXPLANATION_REPETITION_REJECTED',content)
            if not consistency['passed_known_checks']:
                raise StudentSelectionError('STUDENT_EXPLANATION_KNOWN_CONTRADICTION',content)
            turn.answer=presentation['rendered_answer'];turn.segments=[AnswerSegment.model_validate(s) for s in presentation['segments']]
            turn.status='limited';turn.report_mode='student_explanation';detail.state='reported'
            detail.narrative_owner='student_model';detail.model_authored_factual_text=True
            detail.upstream_service_identity=response['reported_service_identity'];detail.elapsed_seconds=response['elapsed_seconds']
        finally:_SLOT.release()
