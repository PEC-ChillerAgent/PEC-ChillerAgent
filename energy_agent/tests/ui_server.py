"""Local-only browser protocol fixture. Never a production model provider.

Run from the project root with python -m energy_agent.tests.ui_server.
All state lives in outputs/stage2_ui_fixture, separate from normal user data.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

import uvicorn

from chiller_app.api.fastapi_app import app
from energy_agent.runtime import AgentRuntime


class ProtocolFixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        messages = body["messages"]
        if not body.get("tools"):
            message = {"role": "assistant", "content": "本地协议测试连接成功；这不是真实厂商连接。"}
        elif messages[-1]["role"] == "tool":
            payload = json.loads(messages[-1]["content"])
            fact = next((f for f in payload.get("facts", []) if f["label"].startswith("实测COP（")), None)
            text = "当前实测COP的有效输出点均值为 {{fact:" + fact["fact_id"] + "}}。本次计算复用原工作台的水侧方程。点击数值可以核对完整结果。" if fact else "当前缺少必要输入，请查看工具提示并补齐数据。"
            message = {"role": "assistant", "content": text, "reasoning_content": "private fixture state"}
        else:
            message = {"role": "assistant", "content": None, "reasoning_content": "private fixture state", "tool_calls": [
                {"id": "fixture_call", "type": "function", "function": {"name": "chiller_analyze", "arguments": '{"task":"physics"}'}}]}
        encoded = json.dumps({"choices": [{"message": message}]}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    directory = root / "outputs" / "stage2_ui_fixture"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "PROVENANCE.json").write_text(json.dumps({"protocol_fixture": True, "live_vendor_test": False}), encoding="utf-8")
    runtime = AgentRuntime(directory)
    runtime.register_dataset(json.loads((root / "examples" / "agent_dataset.json").read_text(encoding="utf-8")))
    app.state.energy_runtime = runtime
    upstream = ThreadingHTTPServer(("127.0.0.1", 8770), ProtocolFixtureHandler)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    print("PROTOCOL FIXTURE ONLY: UI http://127.0.0.1:8769/chat; compatible base http://127.0.0.1:8770/v1; model protocol-fixture; no API key required", flush=True)
    try:
        uvicorn.run(app, host="127.0.0.1", port=8769, log_level="warning")
    finally:
        upstream.shutdown()
