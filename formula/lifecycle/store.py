"""SQLite 기반 append-only 이벤트·상태 저장소.

한 프로세스의 메모리에 run을 두는 기존 SSE 경로는 유지하되, 장기 실험 상태는 이 저장소가
진실원이다. `idempotency_key`와 `state_version`을 DB 제약으로 보장한다.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import EventEnvelope, ProjectState


class WorkflowStore:
    def __init__(self, path: Optional[str | Path] = None):
        configured = os.environ.get("FORMULA1_DB_PATH", "").strip()
        self.path = Path(path or configured or "/tmp/formula1/formula1.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    run_id TEXT UNIQUE,
                    state_version INTEGER NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    project_id TEXT NOT NULL,
                    run_id TEXT,
                    event_type TEXT NOT NULL,
                    envelope_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(project_id)
                );
                CREATE INDEX IF NOT EXISTS idx_events_project_seq
                    ON workflow_events(project_id, seq);
                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    decision_type TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(project_id)
                );
            """)

    def create(self, state: ProjectState, event: EventEnvelope) -> ProjectState:
        data = state.model_dump_json()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?)",
                (state.project_id, state.run_id or None, state.state_version, data,
                 state.created_at, state.updated_at),
            )
            self._insert_event(conn, event)
            conn.commit()
        return state

    def get(self, project_id: str) -> Optional[ProjectState]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM projects WHERE project_id=?", (project_id,)
            ).fetchone()
        return ProjectState.model_validate_json(row["state_json"]) if row else None

    def by_run(self, run_id: str) -> Optional[ProjectState]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM projects WHERE run_id=?", (run_id,)
            ).fetchone()
        return ProjectState.model_validate_json(row["state_json"]) if row else None

    def save(self, state: ProjectState, event: EventEnvelope,
             expected_version: Optional[int] = None) -> Tuple[ProjectState, bool]:
        """상태와 이벤트를 원자적으로 저장한다. 반환 bool=False면 중복 이벤트다."""
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            duplicate = conn.execute(
                "SELECT 1 FROM workflow_events WHERE idempotency_key=?",
                (event.idempotency_key,),
            ).fetchone()
            if duplicate:
                conn.rollback()
                current = self.get(state.project_id)
                return (current or state), False
            row = conn.execute(
                "SELECT state_version FROM projects WHERE project_id=?", (state.project_id,)
            ).fetchone()
            if row is None:
                conn.rollback()
                raise KeyError(state.project_id)
            actual = int(row["state_version"])
            wanted = actual if expected_version is None else expected_version
            if actual != wanted:
                conn.rollback()
                raise ValueError(f"state_version 충돌: expected={wanted}, actual={actual}")
            state.state_version = actual + 1
            state.updated_at = event.created_at
            changed = conn.execute(
                "UPDATE projects SET run_id=?, state_version=?, state_json=?, updated_at=? "
                "WHERE project_id=? AND state_version=?",
                (state.run_id or None, state.state_version, state.model_dump_json(),
                 state.updated_at, state.project_id, actual),
            ).rowcount
            if changed != 1:
                conn.rollback()
                raise ValueError("동시 상태 갱신 충돌")
            self._insert_event(conn, event)
            conn.commit()
        return state, True

    def events(self, project_id: str, after: int = 0) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT seq, envelope_json FROM workflow_events "
                "WHERE project_id=? AND seq>? ORDER BY seq", (project_id, after)
            ).fetchall()
        return [{"seq": row["seq"], **json.loads(row["envelope_json"])} for row in rows]

    def project_for_idempotency(self, key: str) -> Optional[ProjectState]:
        if not key:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT p.state_json FROM workflow_events e JOIN projects p "
                "ON p.project_id=e.project_id WHERE e.idempotency_key=?", (key,)
            ).fetchone()
        return ProjectState.model_validate_json(row["state_json"]) if row else None

    def decision(self, project_id: str, decision_type: str,
                 record: Dict[str, Any]) -> str:
        decision_id = f"dec-{uuid.uuid4().hex}"
        created_at = float(record.get("created_at") or __import__("time").time())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO decisions VALUES (?, ?, ?, ?, ?)",
                (decision_id, project_id, decision_type,
                 json.dumps(record, ensure_ascii=False, default=str), created_at),
            )
        return decision_id

    def decisions(self, project_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT decision_id, decision_type, record_json, created_at FROM decisions "
                "WHERE project_id=? ORDER BY created_at", (project_id,)
            ).fetchall()
        return [{"decision_id": row["decision_id"], "decision_type": row["decision_type"],
                 "created_at": row["created_at"], **json.loads(row["record_json"])} for row in rows]

    @staticmethod
    def _insert_event(conn: sqlite3.Connection, event: EventEnvelope) -> None:
        conn.execute(
            "INSERT INTO workflow_events "
            "(event_id,idempotency_key,project_id,run_id,event_type,envelope_json,created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event.event_id, event.idempotency_key, event.project_id, event.run_id,
             event.event_type, event.model_dump_json(), event.created_at),
        )
