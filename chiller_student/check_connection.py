"""Read-only identity probe; no model generation and no external provider calls."""
import argparse
import json
from pathlib import Path
from urllib.request import Request, ProxyHandler, build_opener
from urllib.error import HTTPError, URLError

from chiller_student.deployment import ROOT, local_config
from chiller_student.focused_contract import IDENTITY
from chiller_student.service import private_token


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url')
    parser.add_argument('--token-file', type=Path)
    args = parser.parse_args()
    config = local_config()
    url = (args.url or config.get('student_url') or 'http://127.0.0.1:28081').rstrip('/')
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    parsed.port
    if (parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path
            or not (parsed.scheme == 'https' and parsed.hostname
                    or parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1'))):
        parser.error('Use loopback HTTP or remote HTTPS without a URL path or credentials')
    token = private_token(args.token_file or config.get('token_file') or ROOT / '.student_credentials/student-service.token')
    try:
        request = Request(url + '/health', headers={'Authorization': 'Bearer ' + token})
        with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
            wire = response.read(65537)
            if len(wire) > 65536:
                raise ValueError('Health response too large')
        from chiller_student.explanation_protocol import strict_json
        health = strict_json(wire)
        valid = (health.get('status') == 'ok' and health.get('service_identity') == IDENTITY
                 and health.get('backend') == 'real_qwen3_8b_bf16_lora_fp32')
        print(json.dumps({'connected': valid, 'model': health.get('model'),
                          'identity_verified': valid, 'generation_calls': 0}, ensure_ascii=False))
        if not valid:
            raise SystemExit(1)
    except (HTTPError, URLError, OSError, ValueError) as exc:
        print(json.dumps({'connected': False, 'error_type': type(exc).__name__,
                          'next_step': 'Start the GPU service and SSH tunnel, then retry this read-only probe.',
                          'generation_calls': 0}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
