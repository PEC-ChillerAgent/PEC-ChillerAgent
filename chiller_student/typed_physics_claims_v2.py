"""Versioned role-scope correction; old v1 results remain reproducible.

Finite checks only. Parentheses or a prior citation must not make a later
performance value inherit an earlier valid-count label.
"""
import re,json
from chiller_student.explanation_consistency_v3 import check_consistency as prior_check
from chiller_student.typed_physics_claims import ALIASES,TOKEN,SENSOR

VERSION='typed_physics_claims_v2_local_citation_scope'
COUNT=re.compile(r'(?:有效(?:功率|制冷量|冷凝热|COP|残差|输出)?点(?:数)?|样本数|条数|记录数|缺测点数|无法计算点数)[^。；;\n]{0,24}$',re.I)

def check_claims(raw,request):
    previous=prior_check(raw,request);text=json.loads(raw)['answer']
    e=json.loads(request['messages'][1]['content'])['tool_evidence'];facts={f['fact_id']:f for f in e['facts']}
    issues=list(previous['issues']);last_end=0
    for token in TOKEN.finditer(text):
        fid=token.group(1);f=facts.get(fid);window=text[last_end:token.start()];last_end=token.end()
        if f is None:issues.append('UNKNOWN_FACT:'+fid);continue
        before=window.rstrip(' （(');phrase=re.split('[。；;\n，,（）()]',before)[-1]
        if SENSOR.search(phrase) and not f['pointer'].startswith('/result/measurements/'):
            issues.append('SENSOR_VALUE_FACT_ROLE_MISMATCH:'+fid);continue
        iscount=bool(COUNT.search(phrase)) and not bool(re.search(r'有效(?:输出)?点均值|(?:均值|数值|有效值|结果|值为)\s*(?:为|是|：|:)?\s*$',phrase))
        labels=[key for key,p in ALIASES.items() if re.search(p,phrase,re.I)]
        generic_value=bool(re.search(r'(?:本次)?(?:有效值|不可用值|数值|结果|均值|值)\s*(?:为|是|：|:)?\s*$',phrase))
        if not labels and not iscount and re.fullmatch(r'\s*(?:本次|当前)?(?:仍)?(?:为|是)\s*',phrase):
            earlier=re.split('[。；;\n]',before)[-1]
            named=[(m.start(),key) for key,p in ALIASES.items() for m in re.finditer(p,earlier,re.I)]
            if named:labels=[min(named)[1]]
        if iscount:
            if f['origin']!='sample_count' or f['unit']!='条':issues.append('COUNT_FACT_ROLE_MISMATCH:'+fid)
            if '有效' in phrase and not f['pointer'].endswith('/valid_count'):issues.append('VALID_COUNT_POINTER_MISMATCH:'+fid)
            if '缺测点数' in phrase and 'COP' in phrase.upper() and e.get('input_conditions',{}).get('fields',{}).get('P_W',{}).get('state')=='observed_zero':
                issues.append('OBSERVED_ZERO_POWER_IS_NOT_MISSING_MEASUREMENT')
        elif labels:
            if f['pointer'] not in {'/result/metrics/'+k+'/value' for k in labels}:issues.append('METRIC_VALUE_FACT_ROLE_MISMATCH:'+fid)
        elif generic_value and not f['pointer'].endswith('/value'):issues.append('VALUE_CITED_AS_COUNT:'+fid)
    for clause in re.split('[。；;\n，,]',text):
        hypothetical=bool(re.search(r'不能|不可把|不应|不是|并非|错误写法|假设|如果',clause))
        if not hypothetical:
            if re.search(r'COP.{0,15}(?:Qc\s*/\s*P|正功率条件\s*Qe\s*[>＞])',clause,re.I):issues.append('COP_NUMERATOR_OR_POSITIVE_CONDITION_WRONG')
            if re.search(r'(?:功率指标|输入功率)(?:本身)?(?:的|需要|是|为).{0,6}分母',clause) and not re.search(r'(?:是|为)COP(?:的)?分母',clause,re.I):
                issues.append('POWER_INDICATOR_IS_NOT_A_RATIO')
            # A sentence saying a residual is not blocked by a denominator
            # condition does not claim that the residual is a ratio.
            if re.search(r'(?:残差|能量平衡偏差).{0,25}(?:以\s*P\s*为分母|除以|分母(?:为|是))',clause,re.I) and not re.search(r'没有|无分|不含|不需要|不以|不因',clause):
                issues.append('RESIDUAL_IS_NOT_A_RATIO')
            if re.search(r'冷冻进水设定(?:温度|值|目标)?\s*TSet_K|TSet_K\s*(?:是|为).{0,5}进水',clause):issues.append('OUTLET_SETPOINT_MISNAMED_AS_INLET')
            if re.search(r'COP\s*只(?:依赖|需要)[^。；;\n]{0,12}(?:正功率|输入功率|功率)',clause,re.I) and not re.search(r'制冷量|冷量|Qe',clause):issues.append('COP_COOLING_NUMERATOR_OMITTED_IN_ONLY_DEPENDENCY')
        if re.search(r'COP.{0,22}不以\s*P\s*为分母',clause,re.I) and not re.search(r'不能说|错误写法|假设|如果',clause):issues.append('COP_POWER_DENOMINATOR_DENIED')
        if e.get('input_conditions',{}).get('COP_positive_power_condition_met') is False and not re.search(r'不满足|不成立|未满足|没有满足',clause):
            if re.search(r'(?:本次|当前).{0,10}(?:COP|分母|正功率).{0,8}(?:满足|成立)|(?:COP|分母|正功率).{0,10}(?:本次|当前).{0,8}(?:满足|成立)',clause):issues.append('ACTUAL_COP_POSITIVE_POWER_CONDITION_FALSE')
    for sentence in re.split('[。；;\n]',text):
        for match in re.finditer(r'COP[^。；;\n]{0,32}不以\s*P\s*为分母',sentence,re.I):
            prefix=sentence[:match.start()]
            if not re.search(r'不能|不应|错误写法|假设|如果',prefix):issues.append('COP_POWER_DENOMINATOR_DENIED')
    issues=list(dict.fromkeys(issues))
    return {'check_version':VERSION,'passed_known_checks':not issues,'issues':issues,'legacy_v3_issues':previous['issues'],
        'model_text_repaired':False,'exhaustive_semantic_verification':False,'task_completeness':'pending_manual_review','domain_accuracy':None}
