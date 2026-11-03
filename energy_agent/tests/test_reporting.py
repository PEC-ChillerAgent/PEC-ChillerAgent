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
