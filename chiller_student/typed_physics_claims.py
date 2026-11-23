"""Finite fact-role and explicit-formula checks, never semantic certification."""
import re,json
from chiller_student.explanation_consistency_v3 import check_consistency as prior_check

VERSION='typed_physics_claims_v1'
ALIASES={'power_kW':r'输入功率|功率指标|机组功率|功率','cooling_capacity_kW':r'制冷量|冷量',
 'condenser_heat_kW':r'冷凝热','COP':r'COP','energy_balance_error_kW':r'能量平衡偏差|能量偏差|平衡残差|残差'}
TOKEN=re.compile(r'\{\{fact:(F\d+)\}\}')
SENSOR=re.compile(r'(?:TEI_K|TEO_K|TCI_K|TCO_K|TEI|TEO|TCI|TCO|evap_flow_kg_s|cond_flow_kg_s|evap_flow|cond_flow)\s*(?:=|为|是|：|:)\s*$')
COUNT=re.compile(r'(?:有效点数|有效点|样本数|条数|记录数|缺测点数|无法计算点数)[^。；;\n]{0,24}$')

def check_claims(raw,request):
    previous=prior_check(raw,request);text=json.loads(raw)['answer'];e=json.loads(request['messages'][1]['content'])['tool_evidence']
    facts={f['fact_id']:f for f in e['facts']};issues=list(previous['issues'])
    for token in TOKEN.finditer(text):
        fid=token.group(1);f=facts.get(fid)
        if f is None:issues.append('UNKNOWN_FACT:'+fid);continue
        before=text[:token.start()];phrase=re.split('[。；;\n，,]',before)[-1]
        if SENSOR.search(phrase) and not f['pointer'].startswith('/result/measurements/'):
            issues.append('SENSOR_VALUE_FACT_ROLE_MISMATCH:'+fid);continue
        iscount=bool(COUNT.search(phrase));labels=[key for key,p in ALIASES.items() if re.search(p,phrase,re.I)]
        generic_value=bool(re.search(r'(?:本次)?(?:有效值|不可用值|数值|结果)\s*(?:为|是|：|:)\s*$',phrase))
        if iscount:
            if f['origin']!='sample_count' or f['unit']!='条':issues.append('COUNT_FACT_ROLE_MISMATCH:'+fid)
            # Valid count and unavailable-condition count are different types.
            if '有效点' in phrase and not f['pointer'].endswith('/valid_count'):issues.append('VALID_COUNT_POINTER_MISMATCH:'+fid)
            if '缺测点数' in phrase and 'COP' in phrase.upper() and e.get('input_conditions',{}).get('fields',{}).get('P_W',{}).get('state')=='observed_zero':
                issues.append('OBSERVED_ZERO_POWER_IS_NOT_MISSING_MEASUREMENT')
        elif labels:
            allowed={'/result/metrics/'+k+'/value' for k in labels}
            # If a metric is named immediately before a citation, a count is
            # not a performance value even when both happen to be zero/one.
            if f['pointer'] not in allowed:issues.append('METRIC_VALUE_FACT_ROLE_MISMATCH:'+fid)
        elif generic_value and not f['pointer'].endswith('/value'):
            issues.append('VALUE_CITED_AS_COUNT:'+fid)
    for clause in re.split('[。；;\n，,]',text):
        if re.search(r'不能|不可把|不应|不是|并非|错误写法|假设|如果',clause):continue
        if re.search(r'COP.{0,15}(?:Qc\s*/\s*P|正功率条件\s*Qe\s*[>＞])',clause,re.I):issues.append('COP_NUMERATOR_OR_POSITIVE_CONDITION_WRONG')
        if re.search(r'(?:功率指标|输入功率)(?:本身)?(?:的|需要|是|为).{0,6}分母',clause) and not re.search(r'(?:是|为)COP(?:的)?分母',clause,re.I):
            issues.append('POWER_INDICATOR_IS_NOT_A_RATIO')
        if re.search(r'(?:残差|能量平衡偏差).{0,16}(?:分母|分子)',clause) and not re.search(r'没有|无分|不含|不需要',clause):issues.append('RESIDUAL_IS_NOT_A_RATIO')
        if re.search(r'冷冻进水设定(?:温度|值|目标)?\s*TSet_K|TSet_K\s*(?:是|为).{0,5}进水',clause):issues.append('OUTLET_SETPOINT_MISNAMED_AS_INLET')
        if re.search(r'COP\s*只(?:依赖|需要)[^。；;\n]{0,12}(?:正功率|输入功率|功率)',clause,re.I) and not re.search(r'制冷量|冷量|Qe',clause):issues.append('COP_COOLING_NUMERATOR_OMITTED_IN_ONLY_DEPENDENCY')
        if e.get('input_conditions',{}).get('COP_positive_power_condition_met') is False and not re.search(r'不满足|不成立|未满足|没有满足',clause):
            if re.search(r'(?:本次|当前).{0,10}(?:COP|分母|正功率).{0,8}(?:满足|成立)|(?:COP|分母|正功率).{0,10}(?:本次|当前).{0,8}(?:满足|成立)',clause):
                issues.append('ACTUAL_COP_POSITIVE_POWER_CONDITION_FALSE')
    issues=list(dict.fromkeys(issues))
    return {'check_version':VERSION,'passed_known_checks':not issues,'issues':issues,'legacy_v3_issues':previous['issues'],
        'model_text_repaired':False,'exhaustive_semantic_verification':False,'task_completeness':'pending_manual_review','domain_accuracy':None}
