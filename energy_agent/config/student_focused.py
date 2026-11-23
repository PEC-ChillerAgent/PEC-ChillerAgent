"""Default application student; no external API or teacher fallback."""
from dataclasses import dataclass
import math
import os
from pathlib import Path
from urllib.parse import urlsplit

from chiller_student.focused_contract import IDENTITY, MODEL_ID
from energy_agent.config.student_shadow import ROOT


@dataclass(frozen=True)
class StudentFocusedSettings:
    enabled: bool = True
    base_url: str = 'http://127.0.0.1:28081'
    token_file: Path = ROOT / '.student_credentials/student-service.token'
    timeout_s: float = 60.0
    service_identity: dict | None = None
    number_gate_version: str = 'v3'
    quality_guard_enabled: bool = True

    @classmethod
    def from_environment(cls):
        from chiller_student.deployment import local_config
        local = local_config()
        prefix = 'ENERGY_AGENT_STUDENT_FOCUSED'
        enabled = os.environ.get(prefix + '_ENABLED', '1').strip().lower()
        if enabled not in ('1', 'true', 'yes', '0', 'false', 'no'):
            raise ValueError('Invalid focused1186 enabled flag')
        base = os.environ.get(prefix + '_URL', local.get('student_url', cls.base_url)).strip().rstrip('/')
        if base.endswith('/v1'):
            base = base[:-3]
        parsed = urlsplit(base)
        parsed.port
        if (not parsed.hostname or any((parsed.username, parsed.password, parsed.path, parsed.query, parsed.fragment))
                or not (parsed.scheme == 'https' or parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1'))):
            raise ValueError('Student service must use loopback HTTP or remote HTTPS')
        timeout = float(os.environ.get(prefix + '_TIMEOUT_S', '60'))
        if not math.isfinite(timeout) or not 1 <= timeout <= 60:
            raise ValueError('Student timeout must be 1..60 seconds')
        token = Path(os.environ.get(prefix + '_TOKEN_FILE', local.get('token_file', str(cls.token_file)))).expanduser()
        return cls(enabled=enabled in ('1', 'true', 'yes'), base_url=base, token_file=token,
                   timeout_s=timeout, service_identity=dict(IDENTITY))

    def public(self):
        return {'enabled': self.enabled, 'configured': self.enabled and self.token_file.is_file(),
                'model': MODEL_ID, 'candidate': 'focused1186', 'default_analysis_backend': 'student_explanation',
                'scope': 'single_row_physics_explanation', 'teacher_fallback': False,
                'service_reachability_checked': False, 'service_identity': self.service_identity,
                'validation_scope': 'Provisional offline review; not autonomous tool-planning certification.'}
