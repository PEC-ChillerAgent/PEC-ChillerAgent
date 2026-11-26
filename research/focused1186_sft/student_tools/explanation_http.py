"""Separate opt-in physics-language HTTP contract; no active candidate chosen."""
from student_tools.native_sft_data import require
from student_tools.explanation_protocol import VERSION,strict_json
from student_tools.readable_physics_evidence import SYSTEM_READABLE,VERSION as READABLE_VERSION,NAMES
from student_tools.joint_physics_support import WORKFLOW

MODEL_ID='chiller-physics-language-v1'

def validate_api_body(body):
    require(isinstance(body,dict) and set(body)=={'model','messages','stream','max_tokens','temperature'},'Unexpected HTTP fields')
    require(body['model']==MODEL_ID and body['stream'] is False,'Wrong model or streaming mode')
    require(type(body['max_tokens']) is int and body['max_tokens']==2048 and type(body['temperature']) in (int,float) and body['temperature']==0,'Frozen greedy budget required')
    mm=body['messages'];require(isinstance(mm,list) and len(mm)==2,'Two messages required')
    require(mm[0]=={'role':'system','content':SYSTEM_READABLE} and set(mm[1])=={'role','content'} and mm[1]['role']=='user','Wrong explanation system/history')
    require(isinstance(mm[1]['content'],str) and len(mm[1]['content'])<=50000,'Payload too large')
    p=strict_json(mm[1]['content'])
    require(set(p)=={'contract_version','question','tool_evidence','response_schema'} and p['contract_version']==VERSION,'Wrong evidence contract')
    require(isinstance(p['question'],str) and 0<len(p['question'].strip())<=12000,'Question required')
    e=p['tool_evidence'];require(e['task']=='physics' and e['status'] in ('success','partial'),'Physics evidence required')
    require(e['project_workflow']==WORKFLOW and e['readable_summary']['version']==READABLE_VERSION,'Frozen workflow/readable evidence required')
    require(set(e['metrics'])==set(NAMES) and set(e['readable_summary']['metrics'])==set(NAMES),'Five metrics required')
    # Rebuild the display from original fact IDs/metric links, rather than accept
    # contradictory availability/sign summaries. The application verifies run
    # pointers against its own repository before constructing this request.
    import copy,json
    from student_tools.readable_physics_evidence import readable_request
    from student_tools.explanation_protocol import SYSTEM
    original=copy.deepcopy(p);del original['tool_evidence']['readable_summary']
    regenerated=readable_request({'messages':[{'role':'system','content':SYSTEM},
                    {'role':'user','content':json.dumps(original,ensure_ascii=False,allow_nan=False)}],'tools':None})
    require(strict_json(regenerated['messages'][1]['content'])==p,'Readable evidence disagrees with original facts')
    expected={'type':'object','additionalProperties':False,'required':['answer'],'properties':{'answer':{'type':'string','minLength':1,'maxLength':6000}}}
    require(p['response_schema']==expected,'Response schema changed')
    require(all(e[k] is False for k in ('simulation_executed','retrieval_executed','measurement_alignment_verified','fault_diagnosis_performed')),'Unsupported execution state')
    return p

def make_body(request):
    body={'model':MODEL_ID,'messages':request['messages'],'stream':False,'max_tokens':2048,'temperature':0}
    validate_api_body(body)
    return body

def make_server(engine,token,*,port=0):
    from student_tools.selection_http import make_server as base
    server=base(engine,token,port=port,validator=validate_api_body,model_id=MODEL_ID)
    parent=server.RequestHandlerClass
    class Handler(parent):
        def auth(self):
            import hmac
            return hmac.compare_digest(self.headers.get('Authorization','').encode('utf-8'),('Bearer '+token).encode('utf-8'))
        def do_GET(self):
            if self.path=='/health' and self.auth():
                self.reply(200,{'status':'ok','model':MODEL_ID,'backend':engine.backend_kind,'service_identity':engine.identity,'training_run':False});return
            super().do_GET()
    server.RequestHandlerClass=Handler
    return server
