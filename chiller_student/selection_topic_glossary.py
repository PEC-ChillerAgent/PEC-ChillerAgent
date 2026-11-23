"""Shared topic meanings, identical for every diagnostic question. No labels."""
import copy,json
from chiller_student.selection_contract import TOPICS,require

TOPIC_DEFINITIONS={
 'metrics':'报告当前性能指标的有效数值、单位、有效点数和不可得性；单有指标名称不等于解释其公式。用户明确不要性能结果表时，不因工具有结果就自动选择。',
 'energy_balance':'解释能量平衡残差的计算定义、正负含义与判断边界；只有报告残差数值或说明缺测时，不一定需要公式主题。',
 'missing_inputs':'依据工具状态定位真实缺列、空值、无效测量及其水侧，并说明补测；缺少诊断结论的证据或基准不等于缺少性能测量输入。',
 'units':'解释文件源单位、内部计算单位、展示单位以及温度/流量转换、密度和比热用途；单位或源列映射与实测/派生类别是不同问题。',
 'measurement_origin':'区分传感器/输入功率的实测输入与冷量、热量、COP、残差等测量派生指标；不是指单位来源，也不专指冷冻/冷却水侧。',
 'simulation_status':'说明本次执行了物理计算还是动态仿真、是否实际运行，以及模型适用性证据边界；未被询问时不要作为通用附加主题。',
 'data_update_workflow':'说明补充或更改文件后重新上传、选择新数据集、新建对话并重分析的操作；不表示原报告已自动包含修改后的数据。',
}

def add_topic_definitions(request):
    require(set(TOPIC_DEFINITIONS)==set(TOPICS),'Glossary topic set drift')
    request=copy.deepcopy(request)
    users=[m for m in request['messages'] if m['role']=='user'];require(len(users)==1,'Expected one user payload')
    payload=json.loads(users[0]['content']);require('topic_definitions' not in payload,'Glossary already present')
    payload['topic_definitions']=copy.deepcopy(TOPIC_DEFINITIONS)
    users[0]['content']=json.dumps(payload,ensure_ascii=False,allow_nan=False)
    return request
