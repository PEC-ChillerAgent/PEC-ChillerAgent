"""Frozen focused1186 identity and its evaluated question/evidence contract."""
from chiller_student.native_sft_data import require
from chiller_student.planned_task_contract_v2 import from_task_request, validate_request

MODEL_ID = 'chiller-focused1186'
ADAPTER_SHA256 = '136eeeb15c1751b8a32628fc525ba680e783e3bf1cbbc546e54a64ab00eca8ab'
BASE_CONFIG_SHA256 = 'f7c4eadfbbf522470667b797a3c89be2524832d2d599797248dc304fff447c30'
IDENTITY = {'candidate_id': 'focused1186-20261120', 'model': MODEL_ID,
            'adapter_model_sha256': ADAPTER_SHA256, 'base_config_sha256': BASE_CONFIG_SHA256,
            'runtime_profile': 'strict_math', 'scope': 'single_row_physics_explanation'}


def make_body(request):
    validate_request(request)
    return {'model': MODEL_ID, 'messages': request['messages'], 'stream': False, 'max_tokens': 2048, 'temperature': 0}


def validate_api_body(body):
    require(isinstance(body, dict) and set(body) == {'model', 'messages', 'stream', 'max_tokens', 'temperature'}, 'Unexpected focused1186 fields')
    require(body['model'] == MODEL_ID and body['stream'] is False, 'Wrong focused1186 model or stream mode')
    require(type(body['max_tokens']) is int and body['max_tokens'] == 2048
            and type(body['temperature']) in (int, float) and body['temperature'] == 0, 'Frozen greedy budget required')
    require(isinstance(body['messages'], list) and len(body['messages']) == 2
            and all(isinstance(m, dict) and set(m) == {'role', 'content'}
                    and isinstance(m['content'], str) for m in body['messages'])
            and [m.get('role') for m in body['messages']] == ['system', 'user'], 'Only current question and evidence allowed')
    return validate_request({'messages': body['messages'], 'tools': None})


def make_server(engine, token, *, port=18081):
    from chiller_student.selection_http import make_server as server_factory
    import hmac
    server = server_factory(engine, token, port=port, validator=validate_api_body, model_id=MODEL_ID)
    original = server.RequestHandlerClass

    class Handler(original):
        def do_GET(self):
            authenticated = hmac.compare_digest(self.headers.get('Authorization', '').encode(), ('Bearer ' + token).encode())
            if self.path == '/health' and authenticated:
                self.reply(200, {'status': 'ok', 'model': MODEL_ID, 'backend': engine.backend_kind,
                                 'service_identity': engine.identity, 'training_run': False})
                return
            super().do_GET()

    server.RequestHandlerClass = Handler
    return server
