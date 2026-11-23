"""Server-rendered numerical claims backed by immutable artifact pointers."""

import math
import re

from energy_agent.contracts.chat import AnswerSegment, ChatFact

TOKEN = re.compile(r"\{\{fact:(F\d+)\}\}")
IDENTIFIER = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z][A-Za-z0-9_-]*(?:…|\.{3})?(?![A-Za-z0-9_-])")
NUMBER = re.compile(r"\d|[零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟]+")
# These phrases describe workflow or physical sides, rather than measured quantities.
NON_NUMERIC = re.compile(r"(?:选择|绑定|提供|上传|指定)(?:一个|一份)(?:数据集|文件)|"
                         r"上一轮|下一轮|上一次|下一次|上一步|下一步|一致|一般|一样|一直|一旦|一些|同一|统一|进一步|两侧|一侧|一并|唯一|"
                         r"值得注意的一点|需要注意的一点|同一点|这一点|某一段|单一|之一|百分比|千瓦时|千瓦|千克|万一|"
                         r"(?:安排|进行|做)一次独立校核|这一(?:列|项|指标)|一段连续运行数据|"
                         r"(?:原因|理由)有[两二三]点|(?:^|[。；\n])其[一二三][，、]|这两类(?:性能)?证据|"
                         r"这两(?:项(?:判断|结果|指标)|类测量|个读数)|这一(?:规模|热量平衡|步)|某一时刻|"
                         r"一个(?:为正的|为正值的|正的)?实测输入功率|一段连续的稳态运行数据")
# These exact sentences explain the missing-value convention, not a measured zero.
# They require an explicitly cited zero valid_count; other zero claims keep the
# existing metric/value attribution checks. Do not exempt arbitrary 零/一/两.
MISSING_VALUE_EXPLANATION = re.compile(
    r"(?:^|[。；，,\n])\s*(?:缺测不代表测得零值|"
    r"表格中的破折号表示缺必要测量，并非数值为零|"
    r"这些项属于缺少必要输入，而非数值为零)(?=[。；\n]|$)")
# These clauses explicitly deny inferring a zero residual from missing data.
# They are exempt only when this answer cites a missing residual count, and no
# contradictory residual value exists for that run. Actual zero claims stay gated.
MISSING_BALANCE_DISCLAIMER = re.compile(
    r"(?:这不代表偏差为零|这并非表示偏差已被确认为零)(?=[，,。；\n]|$)")
ZERO_CLAIM = re.compile(
    r"(?P<metric>(?:实测|模型|模拟)?(?:能量平衡偏差|能量偏差|功率|制冷量|冷量|冷凝热|COP|曲线越界点数|无效模型点数))"
    r"\s*(?:在均值上|的均值|均值|的平均值|平均值)?\s*"
    r"(?P<comparison>不等于|不为|不是|等于|为|是)\s*(?:零|0)"
    r"(?![\d.eE零〇一二两三四五六七八九十百千万亿点])", re.I)
ORIGINS = {"measured": "实测", "measured_derived": "实测派生", "model": "模型", "comparison": "比较", 
           "sample_count": "样本统计", "model_validity": "模型适用性", "source_metadata": "数据集元信息"}
# A ratio's operands explain its definition; they do not relabel its fact as
# cooling capacity or power. Resolve this explicit COP definition as one kind.
COP_RATIO_LABEL = re.compile(r"(?:实测\s*)?(?:COP|能效比值)\s*[（(]\s*制冷量\s*(?:与|和)\s*实测(?:输入)?功率\s*之比\s*[）)]", re.I)
KINDS = (("COP", re.compile(r"COP", re.I)), ("功率", re.compile(r"功率|power", re.I)),
         ("制冷量", re.compile(r"制冷量|冷量|冷负荷|cooling.capacity", re.I)),
         ("温度", re.compile(r"温度|水温|temperature", re.I)), ("冷凝热", re.compile(r"冷凝热")))

LABELS = {"power_kW": "实测功率", "cooling_capacity_kW": "实测制冷量", "condenser_heat_kW": "实测冷凝热",
          "COP": "实测COP", "energy_balance_error_kW": "实测能量偏差", "simulated_TEO_C": "模拟冷冻出水温度",
          "simulated_TCO_C": "模拟冷却出水温度", "simulated_cooling_capacity_kW": "模型制冷量",
          "simulated_power_kW": "模型功率", "simulated_COP": "模型COP"}


def result_facts(result: dict, start: int) -> list[ChatFact]:
    facts = []
    def add(label, value, unit, pointer, origin, evidence_id=None):
        if value is not None:
            facts.append(ChatFact(fact_id=f"F{start + len(facts) + 1}", run_id=result["run_id"], label=label,
                                  value=value, unit=unit, pointer=pointer, origin=origin, evidence_id=evidence_id))
    for name, metric in result["metrics"].items():
        add(LABELS.get(name, name) + "（有效输出点均值）", metric["value"], metric["unit"], f"/result/metrics/{name}/value", metric["origin"], metric["evidence_id"])
        add(LABELS.get(name, name) + "有效点数", metric["valid_count"], "条", f"/result/metrics/{name}/valid_count", "sample_count", metric["evidence_id"])
    for name, comparison in result["comparisons"].items():
        for statistic in ("mae", "rmse", "bias", "n"):
            add(f"{LABELS.get(name, name)}比较{statistic}", comparison[statistic], "条" if statistic == "n" else comparison["unit"],
                f"/result/comparisons/{name}/{statistic}", "comparison", comparison["evidence_id"])
    for name, label in (("input_rows", "原始输入行数"), ("output_rows", "输出点数")):
        add(label, result[name], "条", f"/result/{name}", "sample_count")
    for name, label in (("curve_out_of_range_count", "曲线越界点数"), ("invalid_model_rows", "无效模型点数")):
        add(label, result["model_validity"][name], "条", f"/result/model_validity/{name}", "model_validity")
    return facts


def format_fact(fact: ChatFact) -> str:
    value = format(fact.value, ".8g")
    quantity = value if fact.unit == "1" else value + " " + fact.unit
    return f"【{fact.label} · {ORIGINS.get(fact.origin, fact.origin)}：{quantity}】"


def validate_attribution(prefix: str, suffix: str, fact: ChatFact) -> None:
    # Check only explicit nearby claims; the server label stays visible in all cases.
    separator = r"[。！？\n；，]|\{\{fact:F\d+\}\}"
    clause = re.split(separator, prefix)[-1] + " " + re.split(separator, suffix)[0]
    if fact.origin == "model" and re.search(r"实测|测得|测量值|实测派生", clause):
        raise ValueError("模型事实不能标注为实测")
    if fact.origin in {"measured", "measured_derived"} and re.search(r"模型|模拟|预测", clause):
        raise ValueError("实测事实不能标注为模型预测")
    if fact.unit != "条":
        kind_clause = COP_RATIO_LABEL.sub("COP", clause)
        described = {name for name, pattern in KINDS if pattern.search(kind_clause)}
        actual = {name for name, pattern in KINDS if pattern.search(fact.label)}
        if described and actual and not described.intersection(actual):
            raise ValueError("事实指标类别与表述不一致")


def normalize_reference_mentions(text: str, reference_names: dict[str, str]) -> str:
    """Replace only server-known identities; never exempt arbitrary numbers.

    Providers sometimes echo an abbreviated dataset/run ID in a heading even
    after correcting every numerical claim. Resolve an ellipsis only when its
    sufficiently long hexadecimal prefix identifies exactly one known reference.
    Fact placeholders remain untouched, including when an asset is named F1.
    """
    def replace(match: re.Match) -> str:
        value = match.group()
        if value in reference_names:
            return reference_names[value]
        prefix = value[:-1] if value.endswith("…") else value[:-3] if value.endswith("...") else None
        if prefix and re.fullmatch(r"(?:ds_|run_)[0-9a-f]{8,32}", prefix):
            matches = [key for key in reference_names if key.startswith(prefix)]
            if len(matches) == 1:
                return reference_names[matches[0]]
        if value.startswith(("ds_", "run_")):
            raise ValueError("回答引用了未知或不明确的数据集/运行编号")
        return value

    return "".join(part if TOKEN.fullmatch(part) else IDENTIFIER.sub(replace, part)
                   for part in re.split(r"(\{\{fact:F\d+\}\})", text))


def ground_zero_claims(text: str, facts: list[ChatFact]) -> str:
    """Render an observed zero/nonzero claim only when its cited fact proves it.

    This is not a blanket exemption for 零. The metric must identify exactly one
    fact already cited in the answer, and the comparison must match its value.
    Conditional examples and ambiguous or unsupported claims remain subject to
    the normal numeric validation.
    """
    cited = set(TOKEN.findall(text))

    def metric_name(label: str) -> str:
        label = re.split(r"[（(]", label)[0]
        label = re.sub(r"^(?:实测|模型|模拟)", "", label)
        return {"能量平衡偏差": "能量偏差", "冷量": "制冷量"}.get(label, label).casefold()

    def replace(match: re.Match) -> str:
        clause = re.split(r"[。！？\n；，]", text[:match.start()])[-1]
        if re.search(r"如果|假设|例如|比如|若|当(?!前)", clause):
            return match.group()
        metric = match.group("metric")
        candidates = [fact for fact in facts if fact.fact_id in cited
                      and metric_name(fact.label) == metric_name(metric)
                      and (not metric.startswith(("模型", "模拟")) or fact.origin == "model")
                      and (not metric.startswith("实测") or fact.origin in {"measured", "measured_derived"})]
        if len(candidates) != 1:
            return match.group()
        fact = candidates[0]
        nonzero = match.group("comparison").startswith("不")
        if not math.isfinite(fact.value) or (fact.value != 0) != nonzero:
            raise ValueError("零值判断与对应事实不一致，请直接引用该指标事实")
        return metric + "：{{fact:" + fact.fact_id + "}}"

    return ZERO_CLAIM.sub(replace, text)


def render_answer(text: str, facts: list[ChatFact], *, allow_general_numbers: bool = False,
                  reference_names: dict[str, str] | None = None) -> tuple[str, list[AnswerSegment]]:
    if reference_names:
        text = normalize_reference_mentions(text, reference_names)
    if not allow_general_numbers:
        text = ground_zero_claims(text, facts)
    by_id = {fact.fact_id: fact for fact in facts}
    remainder = TOKEN.sub("", text)
    if "{{" in remainder:
        raise ValueError("数值结论必须使用可核对的fact占位符")
    cited = set(TOKEN.findall(text))
    has_cited_missing_count = any(
        fact.fact_id in cited and fact.origin == "sample_count" and fact.value == 0
        and fact.pointer.startswith("/result/metrics/") and fact.pointer.endswith("/valid_count")
        for fact in facts)
    numeric_remainder = MISSING_VALUE_EXPLANATION.sub("", remainder) if has_cited_missing_count else remainder
    missing_balance = [fact for fact in facts if fact.fact_id in cited
                       and fact.origin == "sample_count" and fact.value == 0
                       and fact.pointer == "/result/metrics/energy_balance_error_kW/valid_count"]
    if len(missing_balance) == 1 and not any(
        fact.run_id == missing_balance[0].run_id
        and fact.pointer == "/result/metrics/energy_balance_error_kW/value" for fact in facts
    ):
        numeric_remainder = MISSING_BALANCE_DISCLAIMER.sub("", numeric_remainder)
    number = NUMBER.search(NON_NUMERIC.sub("", numeric_remainder)) if not allow_general_numbers else None
    if number:
        raise ValueError("数值结论必须使用可核对的fact占位符；发现未引用数字‘" + number.group() + "’")
    segments, position = [], 0
    for match in TOKEN.finditer(text):
        if match.group(1) not in by_id:
            raise ValueError("回答引用了不存在的事实")
        if match.start() > position:
            segments.append(AnswerSegment(text=text[position:match.start()]))
        fact = by_id[match.group(1)]
        validate_attribution(text[:match.start()], text[match.end():], fact)
        segments.append(AnswerSegment(text=format_fact(fact), fact_id=fact.fact_id))
        position = match.end()
    if position < len(text):
        segments.append(AnswerSegment(text=text[position:]))
    return "".join(segment.text for segment in segments), segments


def fallback_text(facts: list[ChatFact], results: list[dict]) -> str:
    lines = ["以下是已完成工具计算的事实报告，未采用模型的未验证数值表述。"]
    for result in results:
        lines.append("分析状态：" + {"success": "完整", "partial": "部分有效，需查看缺测和警告", "needs_input": "需要补充输入", "failed": "数值求解失败"}[result["status"]])
        for fact in facts:
            if fact.run_id == result["run_id"] and fact.origin in {"measured", "measured_derived", "model", "comparison"} and fact.unit != "条":
                lines.append(f"- {{{{fact:{fact.fact_id}}}}}")
        if result["missing_inputs"]:
            lines.append("存在缺少或无效的必要输入，请补齐后重算。")
        if result["warnings"]:
            lines.append("存在数据或模型适用范围警告，请查看下方运行详情。")
    if not results:
        lines.append("请明确要分析的问题，并选择数据集；仿真还需选择匹配的机组参数。")
    lines.append("数值汇总是有效输出点均值；模型结果与实测分开，异常线索不能单独用于故障确诊。")
    return "\n".join(lines)


def markdown_report(turn) -> str:
    facts = {fact.fact_id: fact for fact in turn.facts}
    pieces = []
    for segment in turn.segments:
        if not segment.fact_id:
            pieces.append(segment.text)
        else:
            fact = facts[segment.fact_id]
            url = f"/agent/v1/runs/{fact.run_id}/artifact" if fact.run_id else f"/agent/v1/datasets/{fact.dataset_id}"
            pieces.append(f"[{segment.text}]({url})")
    mode = {"model": "模型解释与工具证据", "tool_facts": "工具事实报告", "message": "对话说明（非设备数值报告）",
            "student_selection": "学生选择重点 · 程序事实报告（受限开发模式）",
            "student_explanation": "学生撰写解释 · Python 数值证据（受限开发模式）"}[turn.report_mode]
    report = "# 冷水机组分析报告\n\n报告类型：" + mode + "\n\n" + "".join(pieces) + "\n\n" + "\n".join(turn.notices) + "\n\n## 证据\n\n" + "\n".join(
        f"- {fact.fact_id}：{fact.label}；引用 {fact.run_id or fact.dataset_id}，JSON Pointer `{fact.pointer}`。"
        for fact in turn.facts if any(s.fact_id == fact.fact_id for s in turn.segments)) + "\n"
    if turn.student_analysis:
        import json
        detail = turn.student_analysis
        ownership = '学生撰写解释，数值由 Python 计算事实提供。' if detail.model_authored_factual_text else '当前显示正文由程序提供。'
        report += ('\n## 学生分析状态\n\n状态：' + detail.state + '\n\n语义审核：待审核；教师调用：0；未自动回退教师。'
                   '\n\n本模式只使用当前问题与本次计算。' + ownership + '\n\n')
        if detail.selection is not None:
            report += '学生原始选择（未修复）：\n```json\n' + json.dumps(detail.selection, ensure_ascii=False, indent=2) + '\n```\n'
        if detail.evidence_markdown:
            report += '\n## 完整工具事实（程序提供，与学生所选重点分开）\n\n' + detail.evidence_markdown
            report += '\n' + '\n'.join(f'- {f.fact_id}：{f.label}；运行 {f.run_id}，JSON Pointer `{f.pointer}`。' for f in turn.facts) + '\n'
    return report
