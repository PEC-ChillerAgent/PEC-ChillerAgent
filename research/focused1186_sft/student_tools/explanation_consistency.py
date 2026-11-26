"""Conservative checks for known contradiction patterns, not semantic proof.

No text repair, hidden model call or claim of exhaustive factual verification.
Both raw output and issues must remain in the application audit.
"""
import re
from student_tools.explanation_protocol import strict_json

FIELD_PATTERNS={
 'cond_flow_kg_s':r'冷却(?:水|侧)?(?:实际)?(?:质量)?流量',
 'evap_flow_kg_s':r'冷冻(?:水|侧)?(?:实际)?(?:质量)?流量',
 'TCI_K':r'冷却(?:水|侧)?进水温(?:度)?',
 'TCO_K':r'冷却(?:水|侧)?出水温(?:度)?',
 'TEI_K':r'冷冻(?:水|侧)?进水温(?:度)?',
 'TEO_K':r'冷冻(?:水|侧)?出水温(?:度)?',
 'P_W':r'输入功率',
}

def check_consistency(raw,request):
    answer=strict_json(raw)['answer'];p=strict_json(request['messages'][1]['content'])
    e=p['tool_evidence'];summary=e['readable_summary'];question=p['question'];issues=[]
    missing={f for m in summary['metrics'].values() for f in m['currently_missing_fields']}
    # Check affirmative missing-input statements, not questions, hypotheticals,
    # or instructions such as "不能把温度说成缺失".
    for clause in re.split('[。；;\n]',answer):
        if re.search(r'不能|不可|不应|若|如果|假设|是否|核查|核对|没有.{0,5}缺',clause):continue
        part=re.search(r'(?:缺少|缺失|缺测)([^。；;]+)',clause)
        if part:
            asserted=part.group(1)
            for field,pattern in FIELD_PATTERNS.items():
                if field not in missing and re.search(pattern,asserted):issues.append('MISSING_FIELD_CONTRADICTION:'+field)
    if re.search(r'(?:功率和COP|COP和功率|COP)(?:按|是|为|属于)(?:有效|直接|本次|的|均|实际){0,4}实测输入',answer,re.I):
        issues.append('COP_MISCLASSIFIED_AS_MEASUREMENT_INPUT')
    if re.search(r'全部指标.{0,8}点数.{0,8}\{\{fact:',answer):issues.append('COUNT_CITATION_SCOPE_AMBIGUOUS')
    for clause in re.split('[。；;\n]',answer):
        if re.search(r'未|没有|不能|尚未|无法|不等于|不代表|并非|不是',clause):continue
        if re.search(r'(?:已|已经)(?:经)?(?:运行|执行|完成).{0,6}动态(?:仿真|模拟)',clause):issues.append('UNEXECUTED_SIMULATION_CLAIM')
        if re.search(r'(?:已|已经)(?:确认|确诊).{0,10}故障',clause):issues.append('UNSUPPORTED_FAULT_DIAGNOSIS')
    relation=summary['energy_balance']
    if relation['sign']=='negative' and re.search(r'冷凝热大于制冷量与输入功率之和',answer):issues.append('RESIDUAL_SIGN_CONTRADICTION')
    if relation['sign']=='positive' and re.search(r'冷凝热小于制冷量与输入功率之和',answer):issues.append('RESIDUAL_SIGN_CONTRADICTION')
    if re.search(r'为何为负|为什么.{0,8}负|正负|符号|算式',question) and relation['sign']!='unavailable':
        if not re.search(r'冷凝热.{0,16}(?:小于|大于|等于|减|低于|高于).{0,20}(?:输入功率|功率)|Qc\s*[<>=].*Qe.*P',answer,re.I):
            issues.append('REQUESTED_RESIDUAL_RELATION_OMITTED')
    return {'passed_known_checks':not issues,'issues':list(dict.fromkeys(issues)),
            'semantic_review':'pending','exhaustive_semantic_verification':False,'model_text_repaired':False}
