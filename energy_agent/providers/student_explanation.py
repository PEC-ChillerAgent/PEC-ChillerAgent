from energy_agent.providers.student_selection import StudentSelectionClient
from chiller_student.explanation_http import validate_api_body
from chiller_student.joint_physics_support import canonical_hash
from energy_agent.providers.student_selection import StudentSelectionError

class StudentExplanationClient(StudentSelectionClient):
    validate_request=staticmethod(validate_api_body)

    def __init__(self,settings,*,transport=None):
        if not settings.service_identity:raise ValueError('A reviewed candidate identity is required')
        super().__init__(settings,transport=transport)
        self.expected_identity=dict(settings.service_identity)
        from chiller_student.planned_explanation import MODEL_ID as planned_model,validate_api_body as planned_validator
        if self.expected_identity['model']==planned_model:self.validate_request=planned_validator
        from chiller_student.focused_contract import MODEL_ID as focused_model,validate_api_body as focused_validator
        if self.expected_identity['model']==focused_model:self.validate_request=focused_validator

    def complete(self,body):
        response=super().complete(body)
        audit=response['response']['chiller_development_audit']
        if audit.get('request_sha256')!=canonical_hash({'messages':body['messages'],'tools':None}):
            raise StudentSelectionError('STUDENT_REQUEST_BINDING_MISMATCH')
        return response
