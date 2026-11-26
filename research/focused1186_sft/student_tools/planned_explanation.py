"""Question-derived task checklist, code-owned physics rules; no judge access.

This is an experimental inference contract, not a trained/released checkpoint.
The compiler is finite and inspectable, not a universal intent classifier.
"""
import copy,json,re
from student_tools.task_explanation import SYSTEM as TASK_SYSTEM,validate_request as validate_task
from student_tools.native_sft_data import require

VERSION='planned_physics_explanation_v1'
MODEL_ID='chiller-physics-planned-v1'
SYSTEM=TASK_SYSTEM+'''
tool_evidence.answer_task_plan是程序根据原问题编译的待答清单，不是已经写好的答案。逐项完成清单，尤其不要漏实际缺项、被询问的指标、原因和更新流程。仍只输出answer字符串的JSON，不复述规则或清单。
physics_reference_rules来自本项目Python公式，优先于自行猜测。指标值与有效点数是不同类型；行数不是温度或流量测量。没有给原始测点数值时，不要拿任意F编号当温度、流量或功率。先完成所问内容，不补未问的长篇指标表。'''
RULES={
 'power':'P是机组输入功率，按有效输入字段读入；不是水侧热量反推，也不是冷冻/冷却水回路各自的功率。有限零功率观测有效。',
 'cooling':'Qe = m_evap * cp * (TEI_K - TEO_K)，冷冻侧进水减出水；不以P为分母。',
 'condenser':'Qc = m_cond * cp * (TCO_K - TCI_K)，冷却侧出水减进水。',
 'COP':'COP = Qe / P，仅当Qe可用且P有效并为正；正功率条件属于分母P，不是分子Qe。',
 'residual':'R = Qc - Qe - P，加减式无分子/分母；需要Qc、Qe和有限有效P，P为零仍能参与残差计算。R不能单独确诊故障或损失。',
 'parameters':'cp是本次计算配置的比热参数，不是工具报告的两侧传感器测量；不能无依据断言两侧cp不同。',
 'units':'源温标/流量/功率单位按source_units；规范温度K、质量流量kg/s、P_W单位W，展示功率/热量kW，COP无量纲。',
 'setpoint':'TSet_K是冷冻出水控制目标，不是进水目标或任何实测温度；不同回路、不同测点不能随意互代。',
 'execution':'仅执行本次证据列出的Python物理计算；没有执行动态仿真、测量对齐校验或故障诊断时，不得声称已执行。',
}
LABELS={'power_kW':'输入功率','cooling_capacity_kW':'制冷量','condenser_heat_kW':'冷凝热','COP':'COP','energy_balance_error_kW':'能量平衡偏差'}

def compile_question(question):
    require(isinstance(question,str) and question.strip(),'Question required')
    q=question;tasks=[]
    def add(key,instruction):tasks.append({'task_id':key,'instruction':instruction})
    avoid=bool(re.search(r'(?:不需要|不重列|不列|不要(?:重列|重复|列)|不用|无需).{0,8}(?:性能|指标|数值|结果)(?:.{0,5}(?:表|值|数值))?',q))
    wanted=set()
    for name,pat in [('power_kW',r'功率'),('cooling_capacity_kW',r'冷量|制冷量'),('condenser_heat_kW',r'冷凝热'),('COP',r'COP|能效比|这个比值'),('energy_balance_error_kW',r'残差|能量.{0,4}(?:差|偏差)|热平衡差|热量差额|平衡差额|热量闭合')]:
        if re.search(pat,q,re.I):wanted.add(name)
    if re.search(r'两侧热量|水侧热量',q):wanted.update(('cooling_capacity_kW','condenser_heat_kW'))
    allmetrics=bool(re.search(r'五项|各指标|哪些指标|哪些性能|其他指标|其余指标|哪些结果|各自是否|哪些性能量',q))
    values=bool(re.search(r'(?:报告|给出|给我|报给|汇总|列出|各是多少|是多少|各能否|各项|逐一给出)|(?:残差|能量偏差|差额|热平衡差)(?:的)?数值',q))
    states=bool(re.search(r'可用|可得|不可得|失效|无效|能否使用|能否取得|仍有效|仍然成立|仍能计算|还能计算|能计算|计算哪些|哪些结果|影响哪些|影响范围|影响链|各指标状态|各能否|哪些.*取得|其他指标|还能看|能看|逐项区分|冷凝热和残差怎样',q))
    if re.search(r'所有结果|全部结果|性能量|性能结果',q) and states:allmetrics=True
    if allmetrics:wanted=set(LABELS)
    if (values or states) and wanted:
        names=[LABELS[k] for k in LABELS if k in wanted]
        mode='逐项说明可用/不可得状态' if avoid or (states and not values) else '逐项给出本次可用数值或不可得状态，并按指标对应引用'
        count='若问点数，分别引用有效点数和因输入条件不能计算的记录数；两种数量不同，零功率不等于缺测。' if re.search(r'点数|条数|样本数|计数',q) else ''
        add('requested_metrics',mode+'：'+'、'.join(names)+'。不要把点数当性能值。'+count)
    actual_question=re.sub(r'(?:若|如果)结果缺失','',q)
    if re.search(r'实际缺|真正.*缺|真正需补|真实缺|缺少|缺测|缺项|缺失|没有功率测量|补测|定位|不可用输入|必要输入|缺(?:的是|的|哪|什么)|缺.{0,6}(?:流量|功率|温度|测点)|少了.{0,8}(?:测量|实测|温度)|没提供',actual_question):
        add('actual_inputs','按input_conditions明确定位本次真实不可用测量、所属水侧和进/出位置；若无实际缺项要明确说明，不把公式依赖或正分母条件当成缺测。')
    if re.search(r'理论|依赖|影响|为什么|为何|水侧热量.{0,10}算|两侧流量|各派生',q):
        add('dependencies','解释所问指标的理论输入/公式与本次阻断链；逐项区分仍有效与受影响结果，功率观测、COP分母、残差加减条件分别处理。')
    if re.search(r'来源|实测输入|直接(?:输入|读取|读入|测量)|派生|公式结果|测量输入与计算|测量输入和计算|归属|哪些按实测|怎样用于水侧|各来自哪里',q):
        add('measurement_origin','分清机组功率直接读入、温度/流量测量、配置比热和公式派生的Qe/Qc/COP/R，明确被问的每项来源。')
    if re.search(r'零功率|有效零|零值功率',q):
        add('observed_zero_power','明确区分有效零功率观测和功率缺测，再解释COP正分母条件与水侧热量/残差是否仍可计算；不据此推断停机。')
    if re.search(r'COP|能效比|这个比值',q,re.I) and re.search(r'通俗|COP.{0,8}(?:含义|无量纲|没有单位|为什么没有单位|是什么)|(?:这个|该)比值.{0,5}含义',q,re.I):
        add('COP_meaning','用单位输入功率对应多少制冷量解释COP；若问无单位原因，说明分子和分母都是功率量，单位相除抵消。')
    if re.search(r'单位|温标|密度|比热|体积流量',q):
        add('units_and_parameters','按所问核对source_units与规范/展示单位；若问换算，区分体积流量结合密度变质量流量与cp参与热量公式；配置填写不等于测量校验。')
    if re.search(r'替代|顶替|互代|互换|代用|借用|设定|目标|跨侧|填作|补进去',q):
        add('substitution_boundary','明确回答能否替代并解释控制目标不是实测、不同水侧/测点不同，不能凭目标认定已达到；不要把出水目标说成进水目标。')
    if re.search(r'残差|能量.{0,4}(?:差|偏差)|热平衡差|差额|闭合',q) and not re.search(r'(?:不|不要|不用|无需)(?:再)?(?:讲|讨论|展开).{0,8}(?:残差|差额)',q):
        add('balance_and_limits','按所问说明R=Qc-Qe-P及当前正负关系/不可得状态；若问缺值能否补零或认为闭合，必须正面回答不能；残差不是已确诊故障、损失或概率。')
    if re.search(r'仿真|预测|模型适用|模型验证|模型求解|到底做了|执行了.*计算',q):
        add('execution_status','明确本次实际执行Python物理计算，动态仿真和模型适用性验证是否执行；不能以未执行任务充当已验证。')
    if re.search(r'上传(?:修改|更正|新|数据|文件)|重新上传|(?:怎样|如何).{0,12}上传|上传.{0,8}(?:数据|文件|后|操作|流程)|录入|新数据|新对话|重新提交|补录[^。；\n]{0,32}(?:后|以后)|补数据后|重算|重新分析|新报告|原报告|旧报告|历史.{0,6}报告|更新.{0,5}数据|(?:改|更改|修改)(?:数据|文件)',q):
        add('update_workflow','回答上传/录入更正数据、核对映射和单位、选择新数据并新建对话、重新计算生成新运行；明确旧数据集/原报告不会自动更新。')
    if re.search(r'故障|诊断|损失|概率|不能证明|能证明|校验|校准|对齐|停机|假设.{0,8}功率|补齐COP',q):
        add('evidence_limits','正面回答本次证据不能确诊故障/损失、证明测量已校验或控制达标；若问核查项，指出真实测量、映射/单位/时刻/不确定度与匹配参考；缺功率不能推断停机，也不能假设功率补齐COP。')
    return {'version':VERSION,'owner':'deterministic_question_compiler_no_judge_or_teacher',
        'tasks':tasks,'avoid_metric_table':avoid,'compiler_exhaustive':False}

def extend_missing_facts(facts,missing):
    """Expose already saved ToolResult.missing_inputs[i].count; never infer it.

    A zero-power COP has an unmet computation condition, not a missing power
    observation. The label deliberately says unavailable-condition records.
    """
    result=copy.deepcopy(facts);next_id=max(int(f['fact_id'][1:]) for f in facts)+1
    for i,item in enumerate(missing):
        require(item['target'] in LABELS and type(item['count']) is int and item['count']>0,'Invalid physics missing-input count')
        first=facts[0]
        result.append({'fact_id':'F'+str(next_id),'run_id':first['run_id'],'dataset_id':first.get('dataset_id'),
            'label':LABELS[item['target']]+'因输入条件不可计算的记录数','value':float(item['count']),'unit':'条',
            'pointer':'/result/missing_inputs/'+str(i)+'/count','evidence_id':None,'origin':'sample_count'})
        next_id+=1
    return result

def type_index(facts,metrics):
    used={v for m in metrics.values() for v in (m['value_fact_id'],m['valid_count_fact_id']) if v}
    return {'version':'fact_roles_v1','metric_roles':{k:{'value':v['value_fact_id'],'valid_count':v['valid_count_fact_id']} for k,v in metrics.items()},
        'unavailable_condition_counts':[f['fact_id'] for f in facts if f['pointer'].startswith('/result/missing_inputs/')],
        'global_row_counts':[f['fact_id'] for f in facts if f['pointer'] in ('/result/input_rows','/result/output_rows')],
        'raw_temperature_or_flow_value_facts':[],
        'note':'全局行数、有效点数、条件不可计算记录数均非温度/流量/性能值；不可互代。实际测点数值未列为事实时不可用行数冒充。'}

def from_task_request(request):
    validate_task(request);result=copy.deepcopy(request);p=json.loads(result['messages'][1]['content']);e=p['tool_evidence']
    plan=compile_question(p['question']);require(bool(plan['tasks']),'Question task plan empty; retain as unsupported, not success')
    e['answer_task_plan']=plan;e['physics_reference_rules']=copy.deepcopy(RULES)
    # Preserve all original facts and add only counts already stored by Python.
    e['facts']=extend_missing_facts(e['facts'],e['missing_inputs'])
    e['fact_type_index']=type_index(e['facts'],e['metrics'])
    result['messages'][0]['content']=SYSTEM;result['messages'][1]['content']=json.dumps(p,ensure_ascii=False,allow_nan=False)
    validate_request(result);return result

def validate_request(request):
    require(set(request)=={'messages','tools'} and request['tools'] is None,'No tools/history permitted')
    require(request['messages'][0]=={'role':'system','content':SYSTEM},'Wrong planned system')
    p=json.loads(request['messages'][1]['content']);e=p['tool_evidence']
    require(e['answer_task_plan']==compile_question(p['question']) and bool(e['answer_task_plan']['tasks']),'Question checklist drift')
    require(e['physics_reference_rules']==RULES,'Physics rule-card drift')
    original_facts=[f for f in e['facts'] if not f['pointer'].startswith('/result/missing_inputs/')]
    require(e['facts']==extend_missing_facts(original_facts,e['missing_inputs']),'Saved missing-input fact drift')
    require(e['fact_type_index']==type_index(e['facts'],e['metrics']),'Fact role index drift')
    original=copy.deepcopy(request);original['messages'][0]['content']=TASK_SYSTEM
    pp=json.loads(original['messages'][1]['content']);del pp['tool_evidence']['answer_task_plan'];del pp['tool_evidence']['physics_reference_rules'];del pp['tool_evidence']['fact_type_index']
    original['messages'][1]['content']=json.dumps(pp,ensure_ascii=False,allow_nan=False);validate_task(original)
    return p

def make_body(request):
    validate_request(request);return {'model':MODEL_ID,'messages':request['messages'],'stream':False,'max_tokens':2048,'temperature':0}

def validate_api_body(body):
    require(set(body)=={'model','messages','stream','max_tokens','temperature'} and body['model']==MODEL_ID and body['stream'] is False
        and type(body['max_tokens']) is int and body['max_tokens']==2048 and type(body['temperature']) in (int,float) and body['temperature']==0,'Wrong planned HTTP fields')
    return validate_request({'messages':body['messages'],'tools':None})

def make_server(engine,token,*,port=0):
    """Same authenticated loopback transport, explicit planned model identity."""
    from student_tools.selection_http import make_server as base
    server=base(engine,token,port=port,validator=validate_api_body,model_id=MODEL_ID)
    parent=server.RequestHandlerClass
    class Handler(parent):
        def auth(self):
            import hmac
            return hmac.compare_digest(self.headers.get('Authorization','').encode('utf8'),('Bearer '+token).encode('utf8'))
        def do_GET(self):
            if self.path=='/health' and self.auth():
                self.reply(200,{'status':'ok','model':MODEL_ID,'backend':engine.backend_kind,'service_identity':engine.identity,'training_run':False});return
            super().do_GET()
    server.RequestHandlerClass=Handler
    return server
