"""Shared strict transport for the frozen 80-step selection service.

Its upstream shadow-only identity is preserved. Application use is separately
versioned; this client never changes the prompt, repairs a choice or retries.
"""
import time

import httpx

from energy_agent.config.student_shadow import EXPECTED_IDENTITY
from energy_agent.providers.audit import clean_trace
from chiller_student.native_sft_data import token_digest
from chiller_student.selection_http import strict_json, validate_api_body


class StudentSelectionError(RuntimeError):
    def __init__(self, code, raw_model_response=None):
        super().__init__(code)
        self.code = code
        self.raw_model_response = raw_model_response


class StudentSelectionClient:
    validate_request = staticmethod(validate_api_body)
    expected_identity = EXPECTED_IDENTITY

    def __init__(self, settings, *, transport=None):
        self.settings, self.transport = settings, transport

    def complete(self, body):
        self.validate_request(body)
        path = self.settings.token_file
        try:
            if not path.is_file() or path.stat().st_size > 4096:
                raise StudentSelectionError('STUDENT_TOKEN_FILE_UNAVAILABLE')
            token = path.read_text(encoding='utf-8').strip()
        except (OSError, UnicodeError):
            raise StudentSelectionError('STUDENT_TOKEN_FILE_UNAVAILABLE') from None
        if len(token) < 24 or not token.isascii() or any(c.isspace() for c in token):
            raise StudentSelectionError('STUDENT_TOKEN_FILE_INVALID')

        def read_json(client, method, endpoint, payload=None):
            with client.stream(method, self.settings.base_url + endpoint,
                               headers={'Authorization': 'Bearer ' + token}, json=payload) as response:
                if response.status_code != 200:
                    raise StudentSelectionError('STUDENT_HTTP_' + str(response.status_code))
                wire = bytearray()
                for chunk in response.iter_bytes():
                    wire.extend(chunk)
                    if len(wire) > 2 * 1024 * 1024:
                        raise StudentSelectionError('STUDENT_RESPONSE_TOO_LARGE')
            try:
                value = strict_json(wire)
                if not isinstance(value, dict):
                    raise ValueError('Object required')
                return value
            except (ValueError, UnicodeError):
                raise StudentSelectionError('STUDENT_INVALID_JSON') from None

        started = time.perf_counter()
        try:
            with httpx.Client(timeout=self.settings.timeout_s, follow_redirects=False,
                              trust_env=False, transport=self.transport) as client:
                health = read_json(client, 'GET', '/health')
                if (health.get('status') != 'ok' or health.get('service_identity') != self.expected_identity
                        or health.get('backend') != 'real_qwen3_8b_bf16_lora_fp32'):
                    raise StudentSelectionError('STUDENT_IDENTITY_MISMATCH')
                response = read_json(client, 'POST', '/v1/chat/completions', body)
        except httpx.TimeoutException:
            raise StudentSelectionError('STUDENT_TIMEOUT_NO_RETRY') from None
        except httpx.HTTPError:
            raise StudentSelectionError('STUDENT_CONNECTION_FAILED_NO_RETRY') from None
        safe_raw = None
        try:
            raw = response['choices'][0]['message']['content']
            safe_raw = raw.replace(token, '[REDACTED]') if isinstance(raw, str) else None
            audit = response['chiller_development_audit']
            if audit['service_identity'] != self.expected_identity or not audit['actual_generation_config']['passed']:
                raise StudentSelectionError('STUDENT_IDENTITY_OR_MODE_MISMATCH', safe_raw)
            actual = audit['actual_generation_config']['actual_prepared_generation_config']
            completion = audit['completion']
            ids, steps = completion['completion_token_ids'], audit['score_trace']
            if (completion['content'] != raw or completion['finish_reason'] != response['choices'][0]['finish_reason']
                    or len(ids) != completion['completion_tokens'] or token_digest(ids) != completion['completion_token_ids_sha256']
                    or ids != [s['argmax_token_id'] for s in steps]
                    or actual['do_sample'] is not False or actual['max_new_tokens'] != 2048):
                raise StudentSelectionError('STUDENT_COMPLETION_OR_GENERATION_MISMATCH', safe_raw)
            if audit['rng_before'] != audit['rng_after'] or audit['state_before'] != audit['state_after']:
                raise StudentSelectionError('STUDENT_RUNTIME_STATE_CHANGED', safe_raw)
        except (KeyError, ValueError, TypeError, IndexError, AttributeError):
            raise StudentSelectionError('STUDENT_INVALID_SELECTION_RESPONSE', safe_raw) from None
        return clean_trace({'response': response, 'reported_service_identity': health['service_identity'],
                            'elapsed_seconds': time.perf_counter() - started}, token)
