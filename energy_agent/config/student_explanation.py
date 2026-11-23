"""Inactive until a reviewed release identity and explicit setting exist."""
from dataclasses import dataclass,replace
import json,os,re
from pathlib import Path
from .student_shadow import StudentShadowSettings,ROOT
from chiller_student.explanation_http import MODEL_ID
from chiller_student.planned_explanation import MODEL_ID as PLANNED_MODEL_ID

def read_release(path):
    path=Path(path)
    if not path.is_file() or path.stat().st_size>16384:raise ValueError('Reviewed release file missing')
    from chiller_student.explanation_protocol import strict_json
    data=strict_json(path.read_bytes())
    if data.get('development_review_passed') is not True or data.get('scope')!='single_row_physics_explanation':
        raise ValueError('Candidate not reviewed for development')
    identity=data['service_identity']
    if (set(identity)!={'candidate_id','model','adapter_model_sha256','base_config_sha256','runtime_profile','scope'}
        or not all(isinstance(v,str) for v in identity.values()) or identity['model'] not in (MODEL_ID,PLANNED_MODEL_ID)
        or identity['runtime_profile']!='strict_math' or identity['scope']!=data['scope']
        or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,120}',identity['candidate_id'])
        or not all(re.fullmatch(r'[a-f0-9]{64}',identity[k]) for k in ('adapter_model_sha256','base_config_sha256'))):
        raise ValueError('Invalid frozen release identity')
    return data

@dataclass(frozen=True)
class StudentExplanationSettings(StudentShadowSettings):
    base_url: str='http://127.0.0.1:28081'
    release_file: Path=ROOT/'outputs/student_work_v1/07_release/student_explanation_active.json'
    service_identity: dict | None=None
    number_gate_version: str='v3'
    quality_guard_enabled: bool=False

    @classmethod
    def from_environment(cls):
        settings=super().from_environment('ENERGY_AGENT_STUDENT_EXPLANATION')
        if not settings.enabled:return settings
        path=Path(os.environ.get('ENERGY_AGENT_STUDENT_EXPLANATION_RELEASE_FILE',str(settings.release_file))).expanduser()
        gate=os.environ.get('ENERGY_AGENT_STUDENT_EXPLANATION_NUMBER_GATE','v3')
        if gate not in ('v3','v4'):raise ValueError('Unknown student explanation number gate')
        quality=os.environ.get('ENERGY_AGENT_STUDENT_EXPLANATION_QUALITY_GUARD','0')
        if quality not in ('0','1'):raise ValueError('Quality guard must be0 or1')
        return replace(settings,release_file=path,service_identity=read_release(path)['service_identity'],
            number_gate_version=gate,quality_guard_enabled=quality=='1')

    def public(self):
        return {'enabled':self.enabled,'configured':self.enabled and bool(self.service_identity) and self.token_file.is_file(),
                'model':self.service_identity['model'] if self.service_identity else MODEL_ID,
                'scope':'single_row_physics_explanation','teacher_fallback':False,'service_reachability_checked':False}
