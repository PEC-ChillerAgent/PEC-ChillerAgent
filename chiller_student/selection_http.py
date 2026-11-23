"""Loopback-only development Chat Completions subset for bounded selections."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac, json, threading, time, uuid
from chiller_student.selection_contract import SYSTEM,TOPICS,schema
from chiller_student.selection_topic_glossary import TOPIC_DEFINITIONS
from chiller_student.physics_evidence import METRICS,FIELDS
from chiller_student.native_sft_data import require

MODEL_ID='chiller-selection-80'
BODY_LIMIT=65536


def strict_json(raw):
    def unique(pairs):
        obj={}
        for key,value in pairs:
            require(key not in obj,'Duplicate JSON key');obj[key]=value
        return obj
    def constant(value):raise ValueError('Nonfinite JSON constant')
    return json.loads(raw,object_pairs_hook=unique,parse_constant=constant)


def validate_api_body(body):
    require(isinstance(body,dict) and set(body)=={'model','messages','stream','max_tokens','temperature'},'Unsupported API fields')
    require(body['model']==MODEL_ID,'Wrong model: use bounded selection model')
    require(body['stream'] is False and type(body['max_tokens']) is int and body['max_tokens']==2048,'Only nonstreaming2048 budget supported')
    require(type(body['temperature']) in (float,int) and body['temperature']==0,'Greedy temperature0 required')
    messages=body['messages']
    require(isinstance(messages,list) and len(messages)==2,'Exactly system/user messages required')
    require(all(isinstance(x,dict) and set(x)=={'role','content'} and isinstance(x['content'],str) for x in messages),'Unsupported message shape')
    require(messages[0]=={'role':'system','content':SYSTEM} and messages[1]['role']=='user','Use frozen bounded selection system')
    p=strict_json(messages[1]['content'])
    require(isinstance(p,dict) and set(p)=={'question','analysis_status','metric_status','allowed_topics','allowed_checks','response_schema','topic_definitions'},'Unsupported selection payload')
    require(isinstance(p['question'],str) and 0<len(p['question'].strip())<=12000,'Invalid question')
    require(p['analysis_status'] in ('success','partial'),'Unsupported analysis status')
    require(p['allowed_topics']==list(TOPICS) and p['topic_definitions']==TOPIC_DEFINITIONS,'Frozen glossary changed')
    status=p['metric_status'];require(isinstance(status,dict) and set(status)==set(METRICS),'Wrong metrics')
    for item in status.values():
        require(isinstance(item,dict) and set(item)=={'available','missing_internal_fields','unmapped_fields'} and type(item['available']) is bool,'Invalid metric status')
        for key in ('missing_internal_fields','unmapped_fields'):
            require(isinstance(item[key],list) and all(isinstance(x,str) and x in FIELDS for x in item[key]) and len(item[key])==len(set(item[key])),'Invalid missing fields')
    checks=p['allowed_checks'];require(isinstance(checks,dict) and 3<=len(checks)<=13,'Invalid check pool')
    from chiller_student.structured_physics import BASE_CHECKS
    require(all(checks.get(k)==v for k,v in BASE_CHECKS.items()),'Base checks changed')
    valid=set(BASE_CHECKS)|{'verify_input:'+f for f in FIELDS}|{'verify_positive_power','reanalyze_new_dataset'}
    require(set(checks)<=valid and all(isinstance(v,str) and len(v)<=1000 for v in checks.values()),'Unknown check pool')
    require(p['response_schema']==schema({'allowed_checks':checks}),'Selection schema changed')
    return p


def make_server(engine,token,*,port=0,validator=validate_api_body,model_id=MODEL_ID):
    require(isinstance(token,str) and len(token)>=24,'Use a random development bearer token')
    gate=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        server_version='ChillerSelectionDev/1'
        def log_message(self,*args):pass
        def reply(self,status,obj):
            wire=json.dumps(obj,ensure_ascii=False,allow_nan=False).encode('utf-8')
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(wire)));self.end_headers();self.wfile.write(wire)
        def auth(self):
            return hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token)
        def do_GET(self):
            if not self.auth():self.reply(401,{'error':{'code':'authentication_required'}});return
            if self.path=='/health':
                self.reply(200,{'status':'ok','model':model_id,'scope':'bounded_selection_shadow_only','backend':engine.backend_kind,'training_run':False});return
            if self.path=='/v1/models':
                self.reply(200,{'object':'list','data':[{'id':model_id,'object':'model','owned_by':'local-development'}]});return
            self.reply(404,{'error':{'code':'unknown_path'}})
        def do_POST(self):
            if not self.auth():self.reply(401,{'error':{'code':'authentication_required'}});return
            if self.path!='/v1/chat/completions':self.reply(404,{'error':{'code':'unknown_path'}});return
            if self.headers.get('Transfer-Encoding') is not None:self.reply(400,{'error':{'code':'unsupported_transfer_encoding'}});return
            try:length=int(self.headers.get('Content-Length','0'))
            except ValueError:self.reply(400,{'error':{'code':'invalid_content_length'}});return
            if length<=0 or length>BODY_LIMIT:self.reply(413,{'error':{'code':'body_limit'}});return
            self.connection.settimeout(10)
            try:
                raw=self.rfile.read(length);require(len(raw)==length,'Incomplete request body')
                body=strict_json(raw.decode('utf-8'));validator(body)
            except (ValueError,TypeError,KeyError,UnicodeError,OSError):
                self.reply(400,{'error':{'code':'invalid_bounded_selection_request'}});return
            if not gate.acquire(blocking=False):self.reply(409,{'error':{'code':'inference_busy_no_retry'}});return
            try:
                result=engine.complete(body)
            except Exception:
                self.reply(500,{'error':{'code':'inference_failed_no_retry'}})
            else:
                self.reply(200,{'id':'chatcmpl-'+uuid.uuid4().hex,'object':'chat.completion','created':int(time.time()),'model':model_id,
                    'choices':[{'index':0,'message':{'role':'assistant','content':result['completion']['content']},'finish_reason':result['completion']['finish_reason']}],
                    'usage':{'prompt_tokens':result['prompt_tokens'],'completion_tokens':result['completion']['completion_tokens'],
                             'total_tokens':result['prompt_tokens']+result['completion']['completion_tokens']},
                    'chiller_development_audit':result})
            finally:gate.release()
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    return server
