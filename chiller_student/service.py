"""Serve the frozen focused1186 adapter on an authenticated loopback endpoint."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import threading
import uuid

from chiller_student.deployment import ROOT, read_manifest, resolve_paths, verify_weights
from chiller_student.focused_contract import IDENTITY, make_server, validate_api_body


def private_token(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 4096:
        raise ValueError('Student token file missing or invalid')
    value = path.read_text(encoding='utf-8').strip()
    if len(value) < 24 or not value.isascii() or any(c.isspace() for c in value):
        raise ValueError('Invalid student token')
    if os.name != 'nt' and path.stat().st_mode & 0o077:
        raise ValueError('Student token must have mode 600: chmod 600 <token-file>')
    return value


class LoggedEngine:
    backend_kind = 'real_qwen3_8b_bf16_lora_fp32'
    identity = IDENTITY

    def __init__(self, output):
        self.output = output
        self.engine = None
        self.accepting = True
        self.idle = threading.Event()
        self.idle.set()

    def complete(self, body):
        if not self.accepting or self.engine is None:
            raise ValueError('Student service is not ready')
        self.idle.clear()
        try:
            result = self.engine.complete(body)
            record = {'request': body, 'result': result, 'training_run': False}
            path = self.output / ('request_' + uuid.uuid4().hex + '.json')
            path.write_text(json.dumps(record, ensure_ascii=False) + '\n', encoding='utf-8')
            return result
        finally:
            self.idle.set()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir', type=Path)
    parser.add_argument('--adapter-dir', type=Path)
    parser.add_argument('--token-file', type=Path, default=ROOT / '.student_credentials/student-service.token')
    parser.add_argument('--port', type=int, default=18081)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    base, adapter = resolve_paths(args.model_dir, args.adapter_dir)
    if args.validate_only:
        result = verify_weights(base, adapter, progress=lambda s: print(s, flush=True))
        print(json.dumps(result, ensure_ascii=False))
        return
    if not 1024 <= args.port <= 65535:
        parser.error('Use an unprivileged loopback port')
    token = private_token(args.token_file)
    output = args.output or ROOT / 'outputs/student_service' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    output = output.resolve()
    if output.exists() or output.is_relative_to(base) or output.is_relative_to(adapter):
        parser.error('Use a new output directory outside model weights')
    output.mkdir(parents=True)
    proxy = LoggedEngine(output)
    server = make_server(proxy, token, port=args.port)
    try:
        # Keep this variable set before torch and CUDA are imported.
        os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
        from chiller_student.selection_inference import SelectionEngine
        from chiller_student.joint_physics_support import canonical_hash

        class FocusedEngine(SelectionEngine):
            validate_request = staticmethod(validate_api_body)
            adapter_name = 'focused1186'
            service_scope = 'Single-row Python-evidence explanation; no autonomous tool planning or teacher fallback.'

            def complete(self, body):
                result = super().complete(body)
                result['service_identity'] = dict(IDENTITY)
                result['request_sha256'] = canonical_hash({'messages': body['messages'], 'tools': None})
                return result

        proxy.engine = FocusedEngine(read_manifest(), base, adapter, output)
        ready = {'ready': True, 'bind': '127.0.0.1', 'port': args.port,
                 'service_identity': IDENTITY, 'training_run': False}
        (output / 'service_ready.json').write_text(json.dumps(ready, indent=2) + '\n', encoding='utf-8')
        print('FOCUSED1186_READY http://127.0.0.1:' + str(args.port), flush=True)
        print('Keep this terminal running; Ctrl+C stops only this service.', flush=True)
        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            pass
    finally:
        proxy.accepting = False
        server.server_close()
        if not proxy.idle.wait(60):
            raise RuntimeError('An inference request is still running; preserve logs')
        if proxy.engine is not None:
            (output / 'service_stopped.json').write_text(json.dumps(proxy.engine.finish()) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
