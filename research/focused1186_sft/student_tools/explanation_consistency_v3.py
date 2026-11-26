"""Opt-in finite evidence checks; never a semantic/completeness certificate.

The old v2 implementation and its historical scores remain unchanged. This
module is not enabled by the current application or existing frozen package.
"""
import re
from student_tools.explanation_protocol import strict_json
from student_tools.explanation_consistency_v2 import check_consistency as old_check,_asserted_tail,_SKIP,_MISSING
from student_tools.explanation_consistency import FIELD_PATTERNS

VERSION='physics_explanation_consistency_v3_explicit_claims_scope_r3'
SKIP_CLAIM=re.compile(r'不能|不可(?:把|将|视|说|判|随意)|不应|若|如果|假设|是否|核查|核对|没有.{0,5}缺')
TEMP_UNITS={
 'F':r'(?:华氏(?:度|温标)?(?:[（(]F[）)])?|°?F(?![A-Za-z0-9_]))',
 'C':r'(?:摄氏(?:度|温标)?(?:[（(]C[）)])?|°?C(?![A-Za-z0-9_]))',
 'K':r'(?:开尔文(?:[（(]K[）)])?|K(?![A-Za-z0-9_]))',
}
TEMP_HEAD=r'(?:源数据(?:的)?(?:温度单位|温度温标|温标)|源(?:温标|温度单位)|上传源温标)\s*(?:为|是|采用|使用)\s*'


def physical_missing(e):
    if 'input_conditions' in e:
        return {f for f,v in e['input_conditions']['fields'].items() if v['state']=='unavailable'}
    missing={f for m in e['readable_summary']['metrics'].values() for f in m['currently_missing_fields']}
    if e['metrics']['power_kW']['value_fact_id'] is not None:missing.discard('P_W')
    return missing


def missing_issues(text,missing,*,observed_zero_power=False):
    issues=[]
    zero_COP_condition=observed_zero_power and 'COP' in text.upper()
    for clause in re.split('[。；;\n]',text):
        if SKIP_CLAIM.search(clause):continue
        for marker in _MISSING.finditer(clause):
            tail=_asserted_tail(clause[marker.end():])
            # Only exclude the explicitly negated contrast, not an unrelated
            # later affirmative predicate (checked independently below).
            tail=re.split(r'[，,]?\s*(?:而不是|并非|而非|不是)',tail,maxsplit=1)[0]
            tail=re.split(r'不影响|不会影响|不妨碍|不阻断',tail,maxsplit=1)[0]
            tail=re.split(r'会(?:直接)?|导致|因此|所以|因而|因为|从而|使|则',tail,maxsplit=1)[0]
            for field,pattern in FIELD_PATTERNS.items():
                tested=re.sub(r'(?:有效)?正(?:的)?输入功率','正分母条件',tail) if field=='P_W' else tail
                if field=='P_W' and zero_COP_condition:tested=tested.replace('有效输入功率','正分母条件')
                if field not in missing and re.search(pattern,tested):issues.append('MISSING_FIELD_CONTRADICTION:'+field)
        for field,pattern in FIELD_PATTERNS.items():
            suffix=r'\s*(?:(?:当前|本次|实际|也|仍|均|都|则|确实|为|是)\s*){0,3}(?:缺少|缺失|缺测)'
            tested=re.sub(r'(?:有效)?正(?:的)?输入功率','正分母条件',clause) if field=='P_W' else clause
            if field=='P_W' and zero_COP_condition:tested=tested.replace('有效输入功率','正分母条件')
            if field not in missing and re.search(pattern+suffix,tested):issues.append('MISSING_FIELD_CONTRADICTION:'+field)
    return issues


def check_consistency(raw,request):
    previous=old_check(raw,request);text=strict_json(raw)['answer'];p=strict_json(request['messages'][1]['content']);e=p['tool_evidence']
    issues=[x for x in previous['issues'] if not x.startswith(('MISSING_FIELD_CONTRADICTION:','RESIDUAL_SIGN_CONTRADICTION'))]
    missing=physical_missing(e)
    zero=any(f['pointer']=='/result/metrics/power_kW/value' and f['value']==0 for f in e['facts'])
    issues+=missing_issues(text,missing,observed_zero_power=zero)
    for unit,pattern in TEMP_UNITS.items():
        if unit==e['source_units']['temperature_unit']:continue
        for match in re.finditer(TEMP_HEAD+pattern,text):
            prefix=re.split('[。；;\n，,]',text[:match.start()])[-1]
            if re.search(r'不能|不应|不可|假设|如果|若|推断',prefix):continue
            if re.match(r'\s*[吗?？]',text[match.end():]):continue
            issues.append('SOURCE_TEMPERATURE_UNIT_CONTRADICTION:'+unit)
    for sentence in re.split('[。；;\n]',text):
        contrast=re.search(r'源温标(?:和列映射)?也?不同',sentence)
        if '冷冻' in sentence and '冷却' in sentence and contrast:
            prefix=re.split('[，,]',sentence[:contrast.start()])[-1]
            if not re.search(r'不能|不应|并非|不是',prefix):issues.append('CROSS_SIDE_SOURCE_TEMPERATURE_UNIT_CONTRADICTION')
        if 'P_W' in missing and (re.search(r'(?:不缺|未缺少|并非缺少)(?:输入)?功率',sentence)
                or re.search(r'(?:缺少的是|缺的是)[^。；;\n]{0,35}不是(?:输入)?功率',sentence)):
            issues.append('ACTUAL_MISSING_POWER_DENIED')
        for formula in re.finditer(r'Q[ce]\s*[-−]\s*Q[ce]\s*[-−]\s*P',sentence,re.I):
            prefix=re.split('[，,]',sentence[:formula.start()])[-1]
            if re.search(r'不能|不可|不应|不要|错误写法|不是',prefix[-30:]):continue
            if re.match(r'\s*(?:不是|并非|是错误)',sentence[formula.end():]):continue
            value=re.sub(r'\s+','',formula.group()).replace('−','-').lower()
            if value!='qc-qe-p':issues.append('EXPLICIT_RESIDUAL_FORMULA_CONTRADICTION')
        if re.search(r'COP\s*(?:为|是)正(?:值)?[，,]?\s*(?:表示|说明|意味着)[^。；;\n]{0,12}(?:制冷量|冷量)(?:\s*)(?:大于|超过|高于)(?:\s*)(?:输入)?功率',sentence,re.I):
            if not re.search(r'不能|不意味着|不代表',sentence):issues.append('POSITIVE_COP_NOT_GREATER_THAN_ONE')
        bad=re.search(r'冷凝热(?:不可得|不可用|缺失)(?:不影响|不会影响)([^。；;\n]{1,80})(?:的可用性|可用性)',sentence)
        if bad and not re.search(r'但|而',bad.group(1)) and re.search(r'残差|能量平衡偏差',bad.group(1)):
            issues.append('RESIDUAL_DEPENDENCY_ON_CONDENSER_HEAT_DENIED')
        # Temperature difference cannot be available when either measurement is
        # unavailable; an unavailable flow alone does not trigger this check.
        if {'TCI_K','TCO_K'}&missing and re.search(r'冷却(?:水|侧)?(?:进[、/]?出水|出[、/]?进水)?温差\s*(?:仍|也)?(?:可得|可用|可计算)',sentence):
            if not re.search(r'不能|不可|无法|并非|不是',sentence):issues.append('CONDENSER_TEMPERATURE_DIFFERENCE_UNAVAILABLE')
        if re.search(r'(?:冷冻出水)?设定(?:温度|值|目标).{0,5}(?:属于|是)(?:实际|实测|测量)输入',sentence):
            if not re.search(r'不是|并非|不能|不应',sentence):issues.append('SETPOINT_MISCLASSIFIED_AS_MEASUREMENT')
    sign=e['readable_summary']['energy_balance']['sign']
    opposite='小于' if sign=='positive' else '大于' if sign=='negative' else None
    if opposite:
        for clause in re.split('[。；;\n，,]',text):
            if not re.search('冷凝热'+opposite+'制冷量与输入功率之和',clause):continue
            current=bool(re.search(r'本次|当前|这次',clause))
            general=bool(re.search(r'(?:正|负)(?:号|偏差|残差|值)(?:则|表示|说明|时)|如果|假设|若',clause))
            if current or not general:issues.append('RESIDUAL_SIGN_CONTRADICTION')
    issues=list(dict.fromkeys(issues))
    return {'check_version':VERSION,'passed_known_checks':not issues,'issues':issues,'legacy_v2_issues':previous['issues'],
        'semantic_review':'pending','exhaustive_semantic_verification':False,'model_text_repaired':False,'domain_accuracy':None}
