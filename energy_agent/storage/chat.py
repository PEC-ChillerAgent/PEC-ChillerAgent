"""Atomic session leases and private model transcripts in the existing SQLite DB."""

import json
import time
from uuid import uuid4

from energy_agent.contracts.chat import ChatContext, ChatReply, ChatRequest
from .repository import ReferenceNotFound, Repository, encode, utc_now


class SessionBusy(RuntimeError):
    pass


class ChatStore:
    LEASE_SECONDS = 600

    def __init__(self, repository: Repository):
        self.repository = repository
        with repository._connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS chat_sessions (id TEXT PRIMARY KEY, payload TEXT NOT NULL, active_turn TEXT, busy_until REAL NOT NULL DEFAULT 0)")
            db.execute("CREATE TABLE IF NOT EXISTS chat_turns (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, public TEXT NOT NULL, wire TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS chat_turn_session ON chat_turns(session_id)")

    def begin(self, request: ChatRequest, model: str) -> tuple[dict, ChatReply]:
        now = utc_now()
        with self.repository._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if request.session_id:
                row = db.execute("SELECT payload, active_turn, busy_until FROM chat_sessions WHERE id = ?", (request.session_id,)).fetchone()
                if row is None:
                    raise ReferenceNotFound("Chat session not found")
                session = json.loads(row[0])
                if row[1] and row[2] > time.time():
                    raise SessionBusy("该会话正在处理消息，请等待完成后再发送")
                if row[1]:
                    stale = db.execute("SELECT public FROM chat_turns WHERE id = ?", (row[1],)).fetchone()
                    if stale:
                        public = json.loads(stale[0])
                        public.update(status="failed", error_code="TURN_INTERRUPTED", answer="上次处理已中断，可以继续发送消息。")
                        db.execute("UPDATE chat_turns SET public = ?, wire = '[]' WHERE id = ?", (encode(public), row[1]))
            else:
                session = {"session_id": "chat_" + uuid4().hex, "context": (request.context or ChatContext()).model_dump(mode="json"),
                           "title": request.message[:60], "created_at": now, "updated_at": now, "fact_counter": 0}
                db.execute("INSERT INTO chat_sessions(id, payload) VALUES (?, ?)", (session["session_id"], encode(session)))
            turn = ChatReply(session_id=session["session_id"], turn_id="turn_" + uuid4().hex, created_at=now,
                             user_message=request.message, answer="", model=model, status="running")
            db.execute("INSERT INTO chat_turns VALUES (?, ?, ?, '[]')", (turn.turn_id, turn.session_id, turn.model_dump_json()))
            db.execute("UPDATE chat_sessions SET active_turn = ?, busy_until = ? WHERE id = ?",
                       (turn.turn_id, time.time() + self.LEASE_SECONDS, turn.session_id))
        return session, turn

    def renew(self, turn: ChatReply) -> None:
        with self.repository._connection() as db:
            count = db.execute("UPDATE chat_sessions SET busy_until = ? WHERE id = ? AND active_turn = ?",
                               (time.time() + self.LEASE_SECONDS, turn.session_id, turn.turn_id)).rowcount
        if not count:
            raise SessionBusy("会话处理权已变更，请刷新对话")

    def finish(self, session: dict, turn: ChatReply, wire: list[dict]) -> None:
        session = {**session, "updated_at": utc_now()}
        session["fact_counter"] = max([session["fact_counter"], *[int(f.fact_id[1:]) for f in turn.facts if f.fact_id.startswith("F")]])
        with self.repository._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute("SELECT active_turn FROM chat_sessions WHERE id = ?", (turn.session_id,)).fetchone()
            if not active or active[0] != turn.turn_id:
                raise SessionBusy("会话处理权已变更，请刷新对话")
            db.execute("UPDATE chat_turns SET public = ?, wire = ? WHERE id = ?", (turn.model_dump_json(), encode(wire), turn.turn_id))
            db.execute("UPDATE chat_sessions SET payload = ?, active_turn = NULL, busy_until = 0 WHERE id = ?", (encode(session), turn.session_id))

    def recent(self, session_id: str, *, limit: int = 10) -> list[dict]:
        with self.repository._connection() as db:
            rows = db.execute("SELECT public, wire FROM chat_turns WHERE session_id = ? ORDER BY rowid DESC LIMIT ?", (session_id, limit + 1)).fetchall()
        entries = [{"public": json.loads(row[0]), "wire": json.loads(row[1])} for row in reversed(rows)]
        return [entry for entry in entries if entry["public"]["status"] != "running"][-limit:]

    def list_sessions(self, *, limit: int = 50, offset: int = 0) -> list[dict]:
        with self.repository._connection() as db:
            rows = db.execute("SELECT payload FROM chat_sessions ORDER BY rowid DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get_session(self, session_id: str) -> dict:
        with self.repository._connection() as db:
            row = db.execute("SELECT payload FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                raise ReferenceNotFound("Chat session not found")
            turns = db.execute("SELECT public FROM chat_turns WHERE session_id = ? ORDER BY rowid", (session_id,)).fetchall()
        return {"session": json.loads(row[0]), "turns": [json.loads(turn[0]) for turn in turns]}

    def get_turn(self, session_id: str, turn_id: str) -> ChatReply:
        with self.repository._connection() as db:
            row = db.execute("SELECT public FROM chat_turns WHERE id = ? AND session_id = ?", (turn_id, session_id)).fetchone()
        if not row:
            raise ReferenceNotFound("Chat turn not found")
        return ChatReply.model_validate_json(row[0])
