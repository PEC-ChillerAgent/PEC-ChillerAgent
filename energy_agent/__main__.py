"""Command-line entry point for deterministic equipment analysis."""

import argparse
import json
from pathlib import Path
import sys

from energy_agent.runtime import AgentRuntime


def main() -> int:
    parser = argparse.ArgumentParser(description="暖通设备分析工具")
    parser.add_argument("--data-dir", type=Path, help="SQLite 数据目录")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="运行真实水侧计算示例")
    create = sub.add_parser("dataset-create", help="登记包含 records 和 schema 的 JSON 请求")
    create.add_argument("--request", type=Path, required=True)
    analyze = sub.add_parser("analyze", help="按 dataset_id 调用冷水机组工具")
    analyze.add_argument("--request", type=Path, required=True)
    show = sub.add_parser("dataset-show", help="查看数据集元数据")
    show.add_argument("--id", required=True)
    export = sub.add_parser("run-export", help="导出统一结果及完整模型输出")
    export.add_argument("--id", required=True)
    discover = sub.add_parser("tools", help="列出工具及 JSON 契约")
    for command in (demo, create, analyze, show, export, discover):
        command.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        runtime = AgentRuntime(args.data_dir)
        status = "success"
        if args.command == "demo":
            source = Path(__file__).resolve().parents[1] / "examples/agent_physics_request.json"
            source = json.loads(source.read_text(encoding="utf-8"))
            dataset = runtime.register_dataset({"asset_id": "demo_chiller", "records": source["records"],
                                                "schema": source["schema"], "source": {"name": "agent_physics_request.json"}})
            result = runtime.analyze({"asset_id": dataset.asset_id, "dataset_id": dataset.dataset_id})
            payload, status = runtime.repository.get_run(result.run_id), result.status
        elif args.command == "dataset-create":
            payload = runtime.register_dataset(json.loads(args.request.read_text(encoding="utf-8-sig"))).model_dump(mode="json")
        elif args.command == "analyze":
            result = runtime.analyze(json.loads(args.request.read_text(encoding="utf-8-sig")))
            payload, status = result.model_dump(mode="json"), result.status
        elif args.command == "dataset-show":
            payload = runtime.repository.get_dataset(args.id).info.model_dump(mode="json")
        elif args.command == "run-export":
            payload = runtime.repository.get_run(args.id)
        else:
            payload = {"tools": runtime.registry.definitions()}
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8")
            print(json.dumps({"status": status, "output": str(args.output.resolve())}, ensure_ascii=False))
        else:
            print(encoded)
        return 2 if status == "needs_input" else 1 if status == "failed" else 0
    except (LookupError, ValueError, TypeError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
