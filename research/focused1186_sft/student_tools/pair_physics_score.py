"""Run explicit local student explanation tests; no teacher calls or retries.

Only loopback endpoints are accepted. Use an SSH tunnel for a remote server.
Raw first responses and HTTP failures are saved. Domain accuracy needs review.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import platform
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


def load_rows(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8-sig").splitlines() if x.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)


def renderer():
    try:
        from student_tools.pair_project_reporting import render_answer, TOKEN
    except ModuleNotFoundError:
        from energy_agent.agents.reporting import render_answer, TOKEN
    return render_answer, TOKEN


def score_response(response, judge, request=None):
    render, token = renderer()
    result = {"protocol_passed": False, "finish_reason": None, "has_unexpected_tool_calls": False,
              "required_value_fact_coverage_passed": False, "domain_review": "pending", "error": None}
    try:
        choices = response["choices"]
        if len(choices) != 1:
            raise ValueError("Expected exactly one completion")
        choice = choices[0]
        message = choice["message"]
        text = message.get("content")
        result["finish_reason"] = choice.get("finish_reason")
        result["has_unexpected_tool_calls"] = bool(message.get("tool_calls"))
        if result["has_unexpected_tool_calls"]:
            raise ValueError("Explanation-only test unexpectedly returned tool calls")
        if choice.get("finish_reason") != "stop":
            raise ValueError("Incomplete/non-stop completion; preserve as failure")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Empty or non-text answer")
        if "<think>" in text or "</think>" in text:
            raise ValueError("Thinking tags leaked in non-thinking answer")
        facts = [SimpleNamespace(**f) for f in judge["facts"]]
        refs = {f.run_id: "该分析运行" for f in facts if f.run_id}
        refs.update({f.dataset_id: "当前数据集" for f in facts if f.dataset_id})
        binding = json.loads(request["messages"][0]["content"].rsplit("\n", 1)[-1]) if request else {}
        asset_id = binding.get("asset_id") or judge.get("asset_id")
        if asset_id:
            refs[asset_id] = "当前机组"
        rendered, _ = render(text, facts, reference_names=refs)
        result["protocol_passed"] = bool(rendered.strip())
        required = judge["required_value_metrics"]
        cited = set(token.findall(text))
        missing = [m for m in required if not any(f.fact_id in cited and f.pointer == f"/result/metrics/{m}/value" for f in facts)]
        result["missing_required_value_facts"] = missing
        result["required_value_fact_coverage_passed"] = not missing
        missing_counts = [m for m in judge["required_missing_count_metrics"] if not any(
            f.fact_id in cited and f.pointer == f"/result/metrics/{m}/valid_count" and f.value == 0 for f in facts)]
        result["missing_required_count_facts"] = missing_counts
        result["required_missing_count_coverage_passed"] = not missing_counts
        result["rendered_answer"] = rendered
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        result["error"] = str(exc)
    return result


def endpoint_url(value):
    p = urllib.parse.urlsplit(value)
    if p.scheme != "http" or p.hostname not in {"127.0.0.1", "localhost", "::1"} or p.username or p.password or p.query or p.fragment:
        raise ValueError("Use a local http loopback endpoint or SSH tunnel, without credentials/query parameters")
    if p.path.rstrip("/") != "/v1":
        raise ValueError("Base URL must end in /v1")
    return value.rstrip("/")


def request_json(url, api_key, body=None, timeout=180):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=headers)
    # Do not route local development requests through system proxy settings.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        return json.load(r)


def build_request(row, model, max_tokens):
    # Explicit allowlist: never merge judge data, targets or provenance into requests.
    r = row["request"]
    return {"model": model, "messages": r["messages"], "tools": r["tools"],
            "tool_choice": "none", "stream": False, "max_tokens": max_tokens,
            "temperature": 0, "top_p": 1, "seed": 42,
            "chat_template_kwargs": {"enable_thinking": False}}


def validate_files(inputs, judges):
    rows, gold = load_rows(inputs), load_rows(judges)
    ids = [r["case_id"] for r in rows]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("Empty inputs or duplicate case ID")
    if len(gold) != len(rows) or {g["case_id"] for g in gold} != set(ids):
        raise ValueError("Judge/input IDs do not match uniquely")
    for row in rows:
        req = row["request"]
        if req["messages"][-1]["role"] != "tool":
            raise ValueError("Replay input must end with tool evidence, not a target answer")
        if "judge_only" in req or "expected_metrics" in req:
            raise ValueError("Scoring data in model request")
    return rows, {g["case_id"]: g for g in gold}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inputs", required=True, type=Path)
    ap.add_argument("--judges", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--model", default="chiller-student-base")
    ap.add_argument("--checkpoint", required=True, help="Actual model path/revision; label is recorded, not auto-verified")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--stage", choices=["baseline", "post_sft"], default="baseline")
    ap.add_argument("--run", action="store_true", help="Without this flag, validate only; no HTTP requests")
    args = ap.parse_args()
    url = endpoint_url(args.base_url)
    rows, judges = validate_files(args.inputs, args.judges)
    if args.max_tokens < 1 or args.max_tokens > 2048 or args.limit is not None and args.limit < 1:
        raise ValueError("Use 1..2048 output tokens and a positive limit")
    if args.limit:
        rows = rows[:args.limit]
    if args.output.exists():
        raise ValueError("Use a new output directory; old attempts must be kept")
    args.output.mkdir(parents=True)
    metadata = {"stage": args.stage, "test_scope": "fixed_tool_evidence_explanation_only_development_not_heldout",
                "execution_requested": args.run, "started_utc": datetime.now(timezone.utc).isoformat(),
                "model_alias": args.model, "checkpoint_declared": args.checkpoint, "checkpoint_weights_auto_verified": False,
                "python": platform.python_version(), "platform": platform.platform(), "endpoint": url,
                "inputs_sha256": sha(args.inputs), "judges_sha256": sha(args.judges), "case_count": len(rows),
                "max_output_tokens": args.max_tokens, "temperature": 0, "top_p": 1, "seed": 42,
                "thinking": False, "automatic_retries": 0, "fallback": False, "concurrency": 1}
    save(args.output / "run_manifest.json", metadata)
    if not args.run:
        save(args.output / "dry_run.json", {"passed": True, "requests_prepared": len(rows), "model_calls": 0})
        print(f"Dry-run passed: {len(rows)} inputs; no model called.")
        return
    api_key = os.environ.get("STUDENT_API_KEY", "")
    try:
        models = request_json(url + "/models", api_key)
        if args.model not in {m["id"] for m in models.get("data", [])}:
            raise ValueError("Requested model alias not listed by local server")
        save(args.output / "server_models.json", models)
    except Exception as exc:
        save(args.output / "startup_error.json", {"error": str(exc), "model_calls": 0})
        raise
    results = []
    for row in rows:
        case = row["case_id"]
        body = build_request(row, args.model, args.max_tokens)
        start = time.perf_counter()
        record = {"case_id": case, "request": body, "http_success": False}
        try:
            response = request_json(url + "/chat/completions", api_key, body)
            record.update(http_success=True, response=response, score=score_response(response, judges[case], body))
        except urllib.error.HTTPError as exc:
            record.update(error_type="http", http_status=exc.code, error_body=exc.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            record.update(error_type=type(exc).__name__, error=str(exc))
        record["latency_seconds"] = time.perf_counter() - start
        save(args.output / (case + ".json"), record)
        results.append(record)
        print(f"{case}: HTTP={record['http_success']}, protocol={record.get('score', {}).get('protocol_passed', False)}", flush=True)
    ok = [r for r in results if r["http_success"]]
    latency = sorted(r["latency_seconds"] for r in ok)
    summary = {"attempted": len(results), "http_successes": len(ok),
               "protocol_passes": sum(r.get("score", {}).get("protocol_passed", False) for r in results),
               "required_value_fact_coverage_passes": sum(r.get("score", {}).get("required_value_fact_coverage_passed", False) for r in results),
               "required_missing_count_coverage_passes": sum(r.get("score", {}).get("required_missing_count_coverage_passed", False) for r in results),
               "protocol_and_both_coverage_passes": sum(r.get("score", {}).get("protocol_passed", False) and r.get("score", {}).get("required_value_fact_coverage_passed", False) and r.get("score", {}).get("required_missing_count_coverage_passed", False) for r in results),
               "truncated_completions": sum(r.get("score", {}).get("finish_reason") == "length" for r in results),
               "mean_latency_seconds": statistics.mean(latency) if latency else None,
               "p95_latency_seconds_nearest_rank": latency[math.ceil(.95 * len(latency)) - 1] if latency else None,
               "domain_accuracy": None, "domain_review": "pending; protocol/coverage is not factual accuracy",
               "tool_selection_tested": False, "live_physics_execution_tested": False,
               "student_responses_received": bool(ok), "independent_test": False, "retries": 0, "fallback": False}
    save(args.output / "summary.json", summary)
    with (args.output / "人工内容审核.csv").open("x", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["case_id", "task", "protocol_passed", "测量与派生区分", "缺测处理", "诊断边界", "建议可执行", "整体是否通过", "备注"])
        for r in results:
            writer.writerow([r["case_id"], judges[r["case_id"]]["task"], r.get("score", {}).get("protocol_passed", False), "", "", "", "", "", ""])
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
