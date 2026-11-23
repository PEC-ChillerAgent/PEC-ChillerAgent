"""Training-side finite compiler extension; existing104 dev requests unchanged.

No activation in the app. Packaged source and hashes identify this extension;
the existing v3 package and its scored requests are immutable.
"""
import copy,json,re
from chiller_student.planned_explanation import SYSTEM,RULES,VERSION,extend_missing_facts,type_index,compile_question as old_compile
from chiller_student.task_explanation import validate_request as validate_task,SYSTEM as TASK_SYSTEM
from chiller_student.native_sft_data import require

def compile_question(question):
    plan=old_compile(question)
    if not plan['tasks'] and re.search(r'还能用|没有结果',question):
        plan['tasks'].append({'task_id':'requested_metrics','instruction':'逐项说明问题所问性能量本次是否可用，解释各自所需输入与实际阻断；按需要引用，不把一个指标不可用扩大成所有结果无效。'})
    return plan

def from_task_request(request):
    validate_task(request);result=copy.deepcopy(request);p=json.loads(result['messages'][1]['content']);e=p['tool_evidence']
    plan=compile_question(p['question']);require(bool(plan['tasks']),'Question task plan empty')
    e['answer_task_plan']=plan;e['physics_reference_rules']=copy.deepcopy(RULES)
    e['facts']=extend_missing_facts(e['facts'],e['missing_inputs']);e['fact_type_index']=type_index(e['facts'],e['metrics'])
    result['messages'][0]['content']=SYSTEM;result['messages'][1]['content']=json.dumps(p,ensure_ascii=False,allow_nan=False)
    validate_request(result);return result

def validate_request(request):
    require(set(request)=={'messages','tools'} and request['tools'] is None,'No tools/history')
    require(request['messages'][0]=={'role':'system','content':SYSTEM},'Wrong planned system')
    p=json.loads(request['messages'][1]['content']);e=p['tool_evidence']
    require(e['answer_task_plan']==compile_question(p['question']) and e['answer_task_plan']['tasks'],'Plan drift')
    require(e['physics_reference_rules']==RULES,'Rule drift')
    original=[f for f in e['facts'] if not f['pointer'].startswith('/result/missing_inputs/')]
    require(e['facts']==extend_missing_facts(original,e['missing_inputs']) and e['fact_type_index']==type_index(e['facts'],e['metrics']),'Facts/roles drift')
    old=copy.deepcopy(request);old['messages'][0]['content']=TASK_SYSTEM
    pp=json.loads(old['messages'][1]['content'])
    for key in ('answer_task_plan','physics_reference_rules','fact_type_index'):del pp['tool_evidence'][key]
    old['messages'][1]['content']=json.dumps(pp,ensure_ascii=False,allow_nan=False);validate_task(old)
    return p
