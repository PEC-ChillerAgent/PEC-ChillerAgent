"""Translate numeric checks into concise operator-facing conclusions."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def conclusions_from_report(report: Mapping[str, Any]) -> list[str]:
    conclusions = []
    diagnosis = report.get("diagnosis", {})
    conclusions.extend(diagnosis.get("warnings", []))
    conclusions.extend(diagnosis.get("recommendations", []))
    if not conclusions:
        conclusions.append("当前规则未发现明显异常；请结合趋势、报警和运行范围继续确认。")
    return conclusions
