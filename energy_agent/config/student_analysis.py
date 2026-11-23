"""Explicit opt-in to student primary reports; no primary provider dependency."""
from dataclasses import dataclass

from .student_shadow import StudentShadowSettings, EXPECTED_IDENTITY

APP_VERSION = 'student-physics-20261116.1'


@dataclass(frozen=True)
class StudentAnalysisSettings(StudentShadowSettings):
    @classmethod
    def from_environment(cls):
        return super().from_environment('ENERGY_AGENT_STUDENT_ANALYSIS')

    def public(self):
        return {
            'enabled': self.enabled,
            'configured': self.enabled and self.token_file.is_file(),
            'service_reachability_checked': False,
            'app_integration_version': APP_VERSION,
            'model': EXPECTED_IDENTITY['model'],
            'mode': 'student_physics_development_v1',
            'scope': 'single-row physics; student selects topics, code writes report',
            'upstream_service_scope': EXPECTED_IDENTITY['scope'],
            'teacher_fallback': False,
        }
