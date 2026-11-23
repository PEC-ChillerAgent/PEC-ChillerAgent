"""Opt-in student shadow settings, independent of the primary LLM config."""
from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_IDENTITY = {
    'candidate_id':'selection80-shadow-v1', 'model':'chiller-selection-80',
    'adapter_model_sha256':'e7867cfc641c470ce347e4f198ae6c75f4c6977bbdf1ecfe38a8a7410c9cada5',
    'base_config_sha256':'f7c4eadfbbf522470667b797a3c89be2524832d2d599797248dc304fff447c30',
    'runtime_profile':'strict_math', 'scope':'bounded_selection_shadow_only',
}


@dataclass(frozen=True)
class StudentShadowSettings:
    enabled: bool = False
    base_url: str = 'http://127.0.0.1:28080'
    token_file: Path = ROOT / '.student_credentials/student-service.token'
    timeout_s: float = 30.

    @classmethod
    def from_environment(cls, prefix='ENERGY_AGENT_STUDENT_SHADOW'):
        flag = os.environ.get(prefix+'_ENABLED','0').strip().lower()
        if flag in ('','0','false','no'): return cls()
        if flag not in ('1','true','yes'): raise ValueError('Invalid shadow enabled flag')
        base = os.environ.get(prefix+'_URL',cls.base_url).strip().rstrip('/')
        if base.endswith('/v1'):base=base[:-3]
        p=urlsplit(base);p.port
        if not p.hostname or any((p.username,p.password,p.query,p.fragment,p.path)):
            raise ValueError('Invalid student root URL')
        if p.scheme!='https' and not (p.scheme=='http' and p.hostname in ('127.0.0.1','localhost','::1')):
            raise ValueError('Use HTTPS or loopback HTTP for shadow')
        timeout=float(os.environ.get(prefix+'_TIMEOUT_S','30'))
        if not 1<=timeout<=60:raise ValueError('Shadow timeout must be1..60 seconds')
        path=Path(os.environ.get(prefix+'_TOKEN_FILE',str(cls.token_file))).expanduser()
        return cls(True,base,path,timeout)

    def public(self):
        return {'enabled':self.enabled, 'base_url':self.base_url, 'model':EXPECTED_IDENTITY['model'],
                'app_integration_version':'page-shadow-20261116.2',
                'token_file_exists':self.enabled and self.token_file.is_file(),
                'scope':'single-row physics shadow; primary answer remains unchanged',
                'primary_model_changed':False}
