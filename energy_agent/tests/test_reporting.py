import pytest

from energy_agent.agents.reporting import render_answer
from energy_agent.contracts.chat import ChatFact


def metric(label="实测能量偏差（有效输出点均值）", value=-14.86, fact_id="F9", origin="measured_derived"):
    return ChatFact(fact_id=fact_id, label=label, value=value, unit="kW", pointer="/metric", origin=origin)


def test_actual_nonzero_balance_explanation_keeps_prose_and_evidence():
    fact = metric()
    text = ("能量平衡偏差：{{fact:F9}}。\n"
            "## 数据一致性问题\n能量平衡偏差在均值上不为零，且为负值，说明热量平衡未完全闭合。")
    answer, segments = render_answer(text, [fact])
    assert "热量平衡未完全闭合" in answer and "-14.86 kW" in answer
    assert "不为零" not in answer
    assert [segment.fact_id for segment in segments if segment.fact_id] == ["F9", "F9"]


@pytest.mark.parametrize("value,claim", [(0, "功率为零"), (0, "功率等于0"),
                                         (100, "功率不等于零"), (-10, "功率不是零")])
def test_zero_comparison_requires_a_matching_cited_value(value, claim):
    fact = metric(label="实测功率（有效输出点均值）", value=value, fact_id="F1")
    answer, segments = render_answer("计算结果：{{fact:F1}}。\n" + claim + "。", [fact])
    assert len([segment for segment in segments if segment.fact_id == "F1"]) == 2
    assert "实测功率" in answer


@pytest.mark.parametrize("value,claim", [(0, "功率不为零"), (100, "功率为零")])
def test_zero_claim_that_contradicts_the_tool_is_rejected(value, claim):
    fact = metric(label="实测功率", value=value, fact_id="F1")
    with pytest.raises(ValueError, match="零值判断与对应事实不一致"):
        render_answer("计算结果：{{fact:F1}}。\n" + claim + "。", [fact])


@pytest.mark.parametrize("text", [
    "能量平衡偏差不为零。",  # Available but never cited.
    "结果：{{fact:F9}}。功率不为零。",  # A different metric cannot prove it.
    "结果：{{fact:F9}}。故障概率为零。",  # No probability fact exists.
    "结果：{{fact:F9}}。功率为零点五。",  # Do not match the zero prefix of a decimal.
    "结果：{{fact:F9}}。能量平衡偏差为0.5。",
    "结果：{{fact:F9}}。如果能量平衡偏差不为零，应检查单位。",  # A condition is not an observation.
])
def test_unknown_quantities_and_hypothetical_zero_conditions_remain_rejected(text):
    with pytest.raises(ValueError):
        render_answer(text, [metric()])


def test_zero_claim_cannot_pick_between_measured_and_model_results():
    measured = metric(label="实测功率", value=0, fact_id="F1", origin="measured")
    modeled = metric(label="模型功率", value=100, fact_id="F2", origin="model")
    results = "实测结果：{{fact:F1}}。模型结果：{{fact:F2}}。\n"
    with pytest.raises(ValueError):
        render_answer(results + "功率不为零。", [measured, modeled])
    with pytest.raises(ValueError, match="零值判断与对应事实不一致"):
        render_answer(results + "实测功率不为零。", [measured, modeled])
    answer, _ = render_answer(results + "模型功率不为零。", [measured, modeled])
    assert "模型：100 kW" in answer


def test_common_qualitative_words_are_not_mistaken_for_measurements():
    text = "## 值得注意的一点\n数据来自单一工作表，百分比口径需要明确。这是候选原因之一。"
    assert render_answer(text, [])[0] == text


@pytest.mark.parametrize("text", ["功率百分比为五十", "单一工作表含五条数据", "概率百分之五", "功率为零"])
def test_qualitative_word_exemptions_do_not_allow_chinese_quantities(text):
    with pytest.raises(ValueError):
        render_answer(text, [])


def test_repair_feedback_identifies_the_rejected_digit():
    with pytest.raises(ValueError, match="发现未引用数字‘零’"):
        render_answer("功率为零。", [])


@pytest.mark.parametrize("label", ["能效比值（制冷量与实测功率之比）", "实测 COP（制冷量与实测功率之比）",
                                  "能效比值(制冷量和实测输入功率之比)"])
def test_explicit_cop_definition_does_not_relabel_its_operands_as_the_result(label):
    cop=metric(label="实测COP",value=3.57,fact_id="F6").model_copy(update={"unit":"1"})
    text=label+"：{{fact:F6}}。"
    assert "3.57" in render_answer(text,[cop])[0]
    for wrong in (metric(label="实测功率",value=82.4,fact_id="F6"),
                  metric(label="实测制冷量",value=294.5,fact_id="F6")):
        with pytest.raises(ValueError,match="指标类别"):
            render_answer(text,[wrong])


def test_cop_definition_resolution_preserves_other_attribution_and_number_guards():
    cop=metric(label="实测COP",value=3.57,fact_id="F6").model_copy(update={"unit":"1"})
    for text in ("功率：{{fact:F6}}。", "能效比值（输入功率）：{{fact:F6}}。",
                 "功率（制冷量与实测功率之比）：{{fact:F6}}。", "COP=3.57。",
                 "模型能效比值（制冷量与实测功率之比）：{{fact:F6}}。"):
        with pytest.raises(ValueError):render_answer(text,[cop])


def test_user_question_discourse_phrases_are_not_measurement_values():
    text = ("这两项结果与这两类测量需要核对，这两个读数应按源单位理解。"
            "COP需要一个为正的实测输入功率。根据这一规模，不能判断某一时刻是否稳定。"
            "需要一段连续的稳态运行数据，当前只能停在这一步。")
    assert render_answer(text, [])[0] == text
    for claim in ("COP为两点五。", "发现两处故障。", "这两项故障已经确诊。", "只有一条记录。", "这两项结果均为零。",
                  "功率为一个千瓦。", "温度差为一度。", "这两个读数均为44。"):
        with pytest.raises(ValueError):render_answer(text + claim, [])


@pytest.mark.parametrize("disclaimer", ["这不代表偏差为零。", "这并非表示偏差已被确认为零，也非表示已确认存在偏差。"])
def test_unavailable_residual_disclaimer_needs_its_own_cited_missing_count(disclaimer):
    missing = ChatFact(fact_id="F8", run_id="run_fixture", label="实测能量偏差有效点数", value=0,
                       unit="条", pointer="/result/metrics/energy_balance_error_kW/valid_count", origin="sample_count")
    text = "残差有效点数：{{fact:F8}}。" + disclaimer
    assert render_answer(text, [missing])[0].endswith(disclaimer)
    for altered in ([], [missing.model_copy(update={"value":1})],
                    [missing.model_copy(update={"pointer":"/result/metrics/COP/valid_count"})],
                    [missing, metric(value=0).model_copy(update={"run_id":"run_fixture", "pointer":"/result/metrics/energy_balance_error_kW/value"})]):
        with pytest.raises(ValueError):render_answer(text, altered)
    with pytest.raises(ValueError):render_answer(disclaimer, [missing])
    for extra in ("能量偏差为零。", "功率为零。", "故障概率为零。", "能量偏差为0.0。", "这不代表偏差为零点五。"):
        with pytest.raises(ValueError):render_answer(text + extra, [missing])


def test_explanatory_chinese_phrases_do_not_disable_measurement_validation():
    text = "原因有两点。其一，检查来源。其二，安排一次独立校核。缺少这一列，请补一段连续运行数据。"
    assert render_answer(text, [])[0] == text
    for claim in ("COP为99。", "功率为零。", "只有一条运行记录。", "发现两处故障。"):
        with pytest.raises(ValueError):
            render_answer(text + claim, [])


@pytest.mark.parametrize("explanation", ["缺测不代表测得零值。",
    "表格中的破折号表示缺必要测量，并非数值为零。", "这些项属于缺少必要输入，而非数值为零。"])
def test_missing_value_explanation_requires_cited_missing_metric_evidence(explanation):
    missing = ChatFact(fact_id="F1", label="实测COP有效点数", value=0, unit="条",
                       pointer="/result/metrics/COP/valid_count", origin="sample_count")
    assert explanation in render_answer("有效点数：{{fact:F1}}。" + explanation, [missing])[0]
    with pytest.raises(ValueError):
        render_answer(explanation, [missing])
    with pytest.raises(ValueError):
        render_answer("有效点数：{{fact:F1}}。" + explanation, [missing.model_copy(update={"value": 1})])
    with pytest.raises(ValueError):
        render_answer("有效点数：{{fact:F1}}。" + explanation + "实测COP为零。", [missing])


@pytest.mark.parametrize("separator", ["，", ", ", "；", "。\n"])
def test_missing_explanation_after_prose_and_next_step_heading(separator):
    missing = ChatFact(fact_id="F1", label="实测COP有效点数", value=0, unit="条",
                       pointer="/result/metrics/COP/valid_count", origin="sample_count")
    text = ("有效点数为 {{fact:F1}}；缺少必要输入，无法计算" + separator
            + "缺测不代表测得零值。\n**下一步建议**\n补充输入后新建对话。")
    assert "缺测不代表测得零值" in render_answer(text, [missing])[0]
    with pytest.raises(ValueError):
        render_answer(text + "制冷量为零。", [missing])
    with pytest.raises(ValueError):
        render_answer(text.replace("{{fact:F1}}", "缺失"), [missing])
