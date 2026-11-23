"""Public ownership and limits for the opt-in student physical analysis path."""
from typing import Literal

from pydantic import JsonValue

from .datasets import Contract


class StudentAnalysisDetails(Contract):
    integration_version: str = 'student-physics-20261116.1'
    state: Literal['not_called', 'reported', 'failed', 'out_of_scope'] = 'not_called'
    mode: Literal['student_physics_development_v1', 'student_explanation_development_v1'] = 'student_physics_development_v1'
    scope: str = '单条工况的性能、缺测、单位与计算状态解释；不覆盖自由诊断、知识检索和仿真分析。'
    teacher_calls: Literal[0] = 0
    teacher_fallback: Literal[False] = False
    narrative_owner: Literal['deterministic_code', 'student_model'] = 'deterministic_code'
    model_authored_factual_text: bool = False
    semantic_review: Literal['pending'] = 'pending'
    domain_accuracy: None = None
    selection: dict[str, JsonValue] | None = None
    request_sha256: str | None = None
    evidence_sha256: str | None = None
    upstream_service_identity: dict[str, str] | None = None
    elapsed_seconds: float | None = None
    evidence_markdown: str = ''
    consistency_check: dict[str, JsonValue] | None = None
