"""SQLite persistence for immutable source datasets and reproducible runs."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from energy_agent.contracts.datasets import DatasetCreate, DatasetInfo, DatasetSnapshot
from energy_agent.contracts.tools import ToolResult


class ReferenceNotFound(LookupError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode(value: dict | list) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class Repository:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "agent.sqlite3"
        with self._connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS datasets (id TEXT PRIMARY KEY, info TEXT NOT NULL, records TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, result TEXT NOT NULL, model_output TEXT NOT NULL)")

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_dataset(self, request: DatasetCreate, *, effective_schema=None, quality=None) -> DatasetInfo:
        columns = list(dict.fromkeys(column for row in request.records for column in row))
        unknown = sorted(set(request.data_schema.column_map.values()) - set(columns))
        if unknown:
            raise ValueError(f"Mapped source columns not found: {unknown}")
        info = DatasetInfo(
            dataset_id="ds_" + uuid4().hex, asset_id=request.asset_id, created_at=utc_now(),
            row_count=len(request.records), columns=columns, source=request.source,
            source_schema=request.data_schema,
            effective_schema=effective_schema or request.data_schema,
            quality=quality or {},
            source_unit_policy=request.source_unit_policy,
        )
        with self._connection() as db:
            db.execute("INSERT INTO datasets VALUES (?, ?, ?)",
                       (info.dataset_id, info.model_dump_json(), encode(request.records)))
        return info

    def get_dataset(self, dataset_id: str) -> DatasetSnapshot:
        with self._connection() as db:
            row = db.execute("SELECT info, records FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        if row is None:
            raise ReferenceNotFound(f"Dataset not found: {dataset_id}")
        return DatasetSnapshot(info=DatasetInfo.model_validate_json(row[0]), records=json.loads(row[1]))

    def list_datasets(self, *, offset: int = 0, limit: int = 50) -> list[DatasetInfo]:
        with self._connection() as db:
            rows = db.execute("SELECT info FROM datasets ORDER BY rowid DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return [DatasetInfo.model_validate_json(row[0]) for row in rows]

    def save_run(self, result: dict, model_output: dict) -> None:
        with self._connection() as db:
            db.execute("INSERT INTO runs VALUES (?, ?, ?)",
                       (result["run_id"], encode(result), encode(model_output)))

    def get_run(self, run_id: str) -> dict:
        with self._connection() as db:
            row = db.execute("SELECT result, model_output FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise ReferenceNotFound(f"Run not found: {run_id}")
        return {"result": ToolResult.model_validate_json(row[0]).model_dump(mode="json"), "model_output": json.loads(row[1])}
