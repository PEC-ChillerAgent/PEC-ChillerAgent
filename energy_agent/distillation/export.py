"""Export selected stored turns for review, never automatically as SFT labels.

python -m energy_agent.distillation.export --db outputs/energy_agent/agent.sqlite3 \
    --turn TURN_ID --source-group GROUP_ID --output outputs/candidates/turn.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from energy_agent.providers.audit import clean_trace


def export_candidate(db_path: str | Path, turn_id: str, source_group_id: str) -> dict:
    if not source_group_id.strip():
        raise ValueError("A provenance group is required; do not split related turns independently")
    path = Path(db_path).resolve()
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        db.execute("BEGIN")
        row = db.execute("SELECT rowid, session_id, public, wire FROM chat_turns WHERE id=?", (turn_id,)).fetchone()
        if row is None:
            raise ValueError("Turn not found")
        ordinal, session_id, public_json, wire_json = row
        has_audit = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_audit_events'").fetchone() is not None

        def events_for(identifier):
            if not has_audit:
                return []
            return [{"kind": kind, "payload": json.loads(payload)} for kind, payload in db.execute(
                "SELECT kind,payload FROM chat_audit_events WHERE turn_id=? ORDER BY id", (identifier,))]

        def stored_turn(identifier, public_text, wire_text):
            events = events_for(identifier)
            final = next((e["payload"] for e in reversed(events) if e["kind"] == "final"), {})
            # New records already mask the configured API key and private fields.
            return {"public": final.get("public_turn", json.loads(public_text)),
                    "wire": final.get("wire", json.loads(wire_text))}, events

        target, events = stored_turn(turn_id, public_json, wire_json)
        public = target["public"]
        session = json.loads(db.execute("SELECT payload FROM chat_sessions WHERE id=?", (session_id,)).fetchone()[0])
        context = session["context"]
        context_event = next((e["payload"] for e in events if e["kind"] == "context"), None)
        prior = []
        if context_event is not None:
            for identifier in context_event["prior_turn_ids"]:
                r = db.execute("SELECT public,wire FROM chat_turns WHERE id=? AND session_id=?", (identifier, session_id)).fetchone()
                if r is None:
                    raise ValueError("Recorded context turn is missing")
                prior.append(stored_turn(identifier, *r)[0])
        else:
            rows = db.execute("SELECT id,public,wire FROM chat_turns WHERE session_id=? AND rowid<? ORDER BY rowid DESC LIMIT 10",
                              (session_id, ordinal)).fetchall()
            prior = [stored_turn(identifier, p, w)[0] for identifier, p, w in reversed(rows)]
        dataset = None
        if context.get("dataset_id"):
            r = db.execute("SELECT info,records FROM datasets WHERE id=?", (context["dataset_id"],)).fetchone()
            if r is None:
                raise ValueError("Bound dataset is missing")
            dataset = {"info": json.loads(r[0]), "records": json.loads(r[1])}

        run_ids = set(public["tool_run_ids"])
        for entry in [*prior, target]:
            run_ids.update(entry["public"]["tool_run_ids"])
            run_ids.update(f["run_id"] for f in entry["public"]["facts"] if f.get("run_id"))
        runs = {}
        for identifier in sorted(run_ids):
            r = db.execute("SELECT result,model_output FROM runs WHERE id=?", (identifier,)).fetchone()
            if r is None:
                raise ValueError("Referenced run is missing")
            runs[identifier] = {"result": json.loads(r[0]), "model_output": json.loads(r[1])}

        calls = [e["payload"] for e in events if e["kind"] == "model_call"]
        finalized = any(e["kind"] == "final" for e in events)
        final_event = next((e["payload"] for e in reversed(events) if e["kind"] == "final"), {})
        complete = bool(context_event and finalized and len(calls) == public["model_calls"]
                        and all(not c.get("capture_incomplete") for c in calls))
        repairs = sum(m.get("role") == "user" and (m.get("content") or "").startswith("回答校验未通过：")
                      for m in target["wire"])
        history_reused = bool(prior and not public["tool_run_ids"] and any(f.get("run_id") for f in public["facts"]))
        fallback_used = final_event.get("fallback_used", public["report_mode"] == "tool_facts"
                                        or public["status"] in {"failed", "limited"})
        reasons = ["human_review_required", "not_a_training_dataset"]
        if not complete:
            reasons.append("legacy_or_partial_capture")
        if fallback_used:
            reasons.append("deterministic_fallback_not_teacher_success")
        if history_reused:
            reasons.append("answer_requires_prior_context")
        if repairs:
            reasons.append("repair_trace_must_not_be_used_as_all_positive_labels")
        return clean_trace({
            "schema_version": 1, "sample_id": turn_id, "source_group_id": source_group_id,
            "split": "unassigned", "training_approved": False,
            "review_status": "pending", "review_reasons": reasons,
            "capture_status": "application_trace" if complete else "legacy_or_partial",
            "capture_limitations": ["Private reasoning and credential fields are deliberately omitted.",
                                    "Provider metadata is null when the service does not return it.",
                                    "Legacy requests cannot be reconstructed exactly; current settings are not substituted."],
            "binding": context, "dataset": dataset, "target_turn": target,
            "prior_context_turns": prior, "events": events, "runs": runs,
            "outcome": {"status": public["status"], "report_mode": public["report_mode"],
                        "model_calls": public["model_calls"], "repair_rounds": repairs,
                        "fallback_used": fallback_used, "history_evidence_reused": history_reused},
        })
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--turn", required=True)
    parser.add_argument("--source-group", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = export_candidate(args.db, args.turn, args.source_group)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # An audit export is a snapshot; refuse to silently replace earlier evidence.
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"Exported review candidate: {args.output.resolve()} ({data['capture_status']})")


if __name__ == "__main__":
    main()
