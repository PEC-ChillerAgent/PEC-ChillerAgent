"""Offline presentation prototype: selected answer and separate full tool evidence.

The model selection is never repaired here. A missing/extra topic remains a
model-selection error. No production routing or training prompts are changed.
"""
import json
from chiller_student.selection_contract import parse_selection
from chiller_student.structured_physics import NAMES,_escaped
from chiller_student.physics_evidence import FIELDS

VERSION='physics_selection_presentation_v1'
TITLES={'metrics':'性能指标','energy_balance':'能量平衡偏差','missing_inputs':'缺测与可得性',
        'units':'单位与转换','measurement_origin':'实测与派生','simulation_status':'计算与仿真状态',
        'data_update_workflow':'补充数据后重新分析'}

def _metrics(context,with_origin=False):
    lines=['|指标|本次结果|有效点数'+('|归属（定义）|' if with_origin else '|'),
           '|---|---|---'+('|---|' if with_origin else '|')];refs=[]
    for metric,item in context['metrics'].items():
        count=item['valid_count_fact_id'];refs.append(count)
        if item['value_fact_id']:
            fid=item['value_fact_id'];refs.append(fid)
            unit='无量纲' if item['unit']=='1' else item['unit']
            value=f"{item['value']:.6g} {unit} [{fid}]"
        else:value='本次无有效值（不是测得零值）'
        origin='实测输入' if metric=='power_kW' else '测量派生'
        lines.append(f"|{NAMES[metric]}|{value}|{item['valid_count']} 条 [{count}]"+(f'|{origin}|' if with_origin else '|'))
    return '\n'.join(lines),refs

def _balance(context):
    lines=['能量平衡偏差 = 冷凝热 − 制冷量 − 输入功率，单位 kW。'];refs=[]
    item=context['metrics']['energy_balance_error_kW'];value=item['value']
    if value is None:lines.append('本次残差不可得，不能判断其正负或能量是否闭合。')
    else:
        fid=item['value_fact_id'];refs.append(fid);lines.append(f'本次偏差为 {value:.6g} kW [{fid}]。')
        if value<0:lines.append('负号表示冷凝热小于制冷量与输入功率之和，不表示能量已闭合。')
        elif value>0:lines.append('正号表示冷凝热大于制冷量与输入功率之和。')
        else:lines.append('本条记录的代数残差为零，仍需核对测量边界与不确定度。')
    lines.append('残差不能直接解释为效率损失、故障类型或故障概率。')
    return '\n\n'.join(lines),refs

def _missing(context):
    lines=[];refs=[];fields=set()
    for metric,item in context['metrics'].items():
        if item['value'] is not None:continue
        absent=sorted(set(item['unmapped_fields']+item['missing_internal_fields']));fields.update(absent)
        cid=item['valid_count_fact_id'];refs.append(cid)
        reason='、'.join(_escaped(FIELDS[f][0])+'（'+f+'）' for f in absent)
        detail=('应核查 '+reason+' 的映射和有效测量。') if reason else '工具没有给出足够的缺测原因，需核对运行状态和源记录，不能自行认定传感器损坏。'
        lines.append(f'- {NAMES[metric]}：本次没有有效值，有效点数 {item["valid_count"]} 条 [{cid}]。'+detail)
    if not lines:lines.append('本次五项性能指标均有有效结果；工具警告不等同于测量字段缺失。')
    if 'TEO_K' in fields:lines.append('冷冻水出水设定值不能替代冷冻水出水实测温度。')
    if 'evap_flow_kg_s' in fields:lines.append('冷却侧流量不能直接替代冷冻侧流量，应补充冷冻侧的有效流量测量。')
    power=context['metrics']['power_kW']['value']
    if power is not None and power<=0 and context['metrics']['COP']['value'] is None:
        lines.append('功率测量存在，但COP计算需要有效正功率；零值或负值不能直接称为缺测。')
    return '\n\n'.join(lines),refs

def _units(context):
    evidence=context['evidence']
    lines=['|字段含义|源列|源单位配置|内部字段|内部单位|','|---|---|---|---|---|']
    for field,meta in evidence['fields'].items():
        key='power_unit' if field=='P_W' else ('flow_unit' if 'flow' in field else 'temperature_unit')
        source=meta['source_column'] if meta['source_column'] is not None else '未映射到现有列'
        lines.append('|'+ '|'.join(_escaped(v) for v in (meta['meaning'],source,evidence['source_units'][key],field,meta['internal_unit']))+'|')
    lines+=['',evidence['unit_rules']]
    return '\n'.join(lines),[]

def _origin(context):
    # These are definitions of the computation inputs/outputs, not claims that
    # every measurement was actually provided or independently verified.
    lines=['输入功率按实测输入字段处理；制冷量、冷凝热、COP和能量平衡偏差属于由测量得到的派生指标。',
           '派生指标不是独立传感器直接读数。该归属说明不代表缺失输入已被补齐，也不代表测量已人工核实。']
    return '\n\n'.join(lines),[]

def _simulation(context):
    return '本次工具执行的是物理计算，未执行动态仿真。默认模型计数不能证明模型适用性。',[]

def _workflow(context):
    return ('1. 在源文件补充或更正有效测量，并核对列和单位。\n'
            '2. 重新上传文件并选择新数据集。\n'
            '3. 新建对话，绑定新数据集后重新执行物理分析。\n'
            '4. 核对新结果的工况和计算记录；不能声称当前旧结果已包含后来修改的测量。'),[]

BUILDERS={'metrics':_metrics,'energy_balance':_balance,'missing_inputs':_missing,'units':_units,
          'measurement_origin':_origin,'simulation_status':_simulation,'data_update_workflow':_workflow}

def present_selection(context,candidate):
    candidate=parse_selection(json.dumps(candidate,ensure_ascii=False,allow_nan=False),context)
    sections=[];answer_refs=[]
    for topic in candidate['answer_topics']:
        body,refs=BUILDERS[topic](context)
        sections.append({'topic':topic,'title':TITLES[topic],'markdown':body,'fact_ids':refs});answer_refs.extend(refs)
    checks=[{'check_id':cid,'text':context['allowed_checks'][cid]} for cid in candidate['followup_check_ids']]
    answer='\n\n'.join('### '+s['title']+'\n\n'+s['markdown'] for s in sections)
    if checks:answer+='\n\n### 建议核查\n\n'+'\n'.join('- '+_escaped(c['text']) for c in checks)
    # The full fact pane is available for inspection but is not inserted into
    # the topic-focused answer and is never used to repair the model's choice.
    evidence_parts=[];evidence_refs=[]
    table,refs=_metrics(context,with_origin=True);evidence_parts.append(table);evidence_refs.extend(refs)
    for builder in (_balance,_missing,_units,_simulation):
        body,refs=builder(context);evidence_parts.append(body);evidence_refs.extend(refs)
    if context['warnings']:
        evidence_parts.append('工具警告：'+'、'.join(_escaped(w['code']) for w in context['warnings'])+'。警告不直接证明设备故障。')
    evidence_parts.append('工具状态：'+_escaped(context['analysis_status'])+'。需分别核查警告和实际缺测。')
    return {'presentation_version':VERSION,'candidate':candidate,'selected_topics':candidate['answer_topics'].copy(),
        'sections':sections,'followup_checks':checks,'answer_markdown':answer+'\n',
        'evidence_markdown':'\n\n'.join(evidence_parts)+'\n','answer_fact_ids':list(dict.fromkeys(answer_refs)),
        'evidence_fact_ids':list(dict.fromkeys(evidence_refs)),'context_sha256':context['source_sha256'],
        'model_selection_repaired':False,'model_authored_factual_text':False,'domain_accuracy':None,
        'production_integrated':False,'limits':'Offline single-row presentation prototype. A missing/extra selection remains a model error; evidence visibility is separate from answer scope. No new computation, retrieval or live tool selection.'}
