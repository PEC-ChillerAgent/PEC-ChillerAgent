"""Opt-in shadow preparation from one completed real physics turn.

No hook into ChatService, no network, no database writes, no teacher labels.
The primary model's answer and private reasoning are never sent to the student.
"""
from copy import deepcopy
import json
from chiller_student.native_sft_data import require
from chiller_student.selection_contract import build_context,selection_request,parse_selection,canonical_hash
from chiller_student.selection_topic_glossary import add_topic_definitions
from chiller_student.selection_http import MODEL_ID,validate_api_body
from chiller_student.selection_presentation_v2 import present_selection_v2


def prepare_shadow_from_events(public_turn,events):
    question=public_turn.get('user_message')
    require(isinstance(question,str) and 0<len(question.strip())<=12000,'Shadow needs original user question')
    contexts=[e['payload'] for e in events if e['kind']=='context']
    require(len(contexts)==1,'Shadow needs exactly one current-turn context')
    info=deepcopy(contexts[0].get('dataset_info'))
    require(isinstance(info,dict) and info.get('row_count')==1,'Shadow prototype supports one-row bound datasets only')
    binding=contexts[0].get('binding',{})
    require(binding.get('dataset_id')==info.get('dataset_id') and binding.get('asset_id')==info.get('asset_id'),'Context binding differs from inspected dataset')
    require(not binding.get('simulation_configured'),'Simulation/compare sessions outside current shadow scope')
    tools=[e['payload'] for e in events if e['kind']=='tool_result']
    analyses=[e for e in tools if e.get('call',{}).get('function',{}).get('name')=='chiller_analyze']
    require(len(analyses)==1,'Shadow needs one completed physics run, no result picking')
    tool=analyses[0]
    require(json.loads(tool['call']['function']['arguments'])=={'task':'physics'},'Shadow supports physics task only')
    payload=deepcopy(tool['result'])
    require(payload.get('status') in ('success','partial') and not payload.get('errors'),'Unsupported failed tool result')
    require(isinstance(info.get('dataset_id'),str) and bool(info['dataset_id']),'Dataset identity missing')
    require(public_turn.get('tool_run_ids')==[payload.get('run_id')],'Physics run not bound to this completed turn')
    # Current result_facts leaves dataset_id=None on run-derived facts. Preserve
    # that representation and bind via the audited context and public run ID;
    # any explicit conflicting dataset or run remains rejected.
    require(payload.get('facts') and all(f.get('dataset_id') in (None,info['dataset_id']) and f.get('run_id')==payload.get('run_id') for f in payload['facts']),'Cross-dataset/run tool facts')
    # The inspect metadata is captured before the real tool call by ChatService.
    # Repack its evidence with the completed physics payload; do not execute a
    # new calculation or import a workbench's potentially stale displayed row.
    calls=[{'id':'shadow_inspect','type':'function','function':{'name':'inspect_dataset','arguments':'{}'}},
           {'id':'shadow_physics','type':'function','function':{'name':'chiller_analyze','arguments':'{"task":"physics"}'}}]
    original={'messages':[{'role':'system','content':'Shadow evidence container; only the deterministic compressed request is sent.'},
        {'role':'user','content':question},{'role':'assistant','content':'','tool_calls':calls},
        {'role':'tool','tool_call_id':'shadow_inspect','content':json.dumps({'status':'success','dataset':info},ensure_ascii=False,allow_nan=False)},
        {'role':'tool','tool_call_id':'shadow_physics','content':json.dumps(payload,ensure_ascii=False,allow_nan=False)}],'tools':None}
    context=build_context(original)
    compressed=add_topic_definitions(selection_request(original))
    body={'model':MODEL_ID,'messages':compressed['messages'],'stream':False,'max_tokens':2048,'temperature':0}
    validate_api_body(body)
    return {'context':context,'body':body,'request_sha256':canonical_hash(compressed),
            'evidence_sha256':context['source_sha256'],'physics_run_id':payload['run_id'],
            'source_turn_id':public_turn.get('turn_id'),'student_received_primary_answer':False,
            'new_physics_execution':False,'production_integrated':False}


def present_shadow_response(prepared,response):
    require(isinstance(response,dict) and response.get('model')==MODEL_ID,'Unexpected student service identity')
    choices=response.get('choices');require(isinstance(choices,list) and len(choices)==1,'One student choice required')
    choice=choices[0];message=choice.get('message',{})
    require(choice.get('finish_reason')=='stop' and message.get('role')=='assistant' and isinstance(message.get('content'),str),'Student response incomplete')
    raw=message['content'];candidate=parse_selection(raw,prepared['context'])
    return {'raw_model_response':raw,'candidate':candidate,'presentation':present_selection_v2(prepared['context'],candidate),
        'request_sha256':prepared['request_sha256'],'evidence_sha256':prepared['evidence_sha256'],
        'physics_run_id':prepared['physics_run_id'],'source_turn_id':prepared['source_turn_id'],
        'protocol_passed':True,'semantic_review':'pending','domain_accuracy':None,
        'model_selection_repaired':False,'primary_answer_changed':False,'production_integrated':False}
