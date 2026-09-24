"""Study 저장소 — state snapshot + append-only 이벤트 + 결정 원장 (명세 v6.1 §3.1, §13).

- 모든 mutation은 `Idempotency-Key`를 가진다. 같은 키가 다시 오면 **새 행 없이** 처음 결과를 돌려준다.
- `Expected-State-Version`이 현재 버전과 다르면 덮어쓰지 않고 `VersionConflict`를 던진다
  (동시 승인 2건 중 1건만 성공 — 인계 문서 §8 서비스 테스트).
- 과거 이벤트·결정은 지우지 않는다. 최신 결과만 남기는 저장소는 명세 §2.1이 금지한다.

기본 경로는 컨테이너 `/tmp` — 파드 재시작 시 study가 사라진다(데모 범위). 운영은
PostgreSQL + object storage(§12.1)이며, 그 전에는 PVC로 옮겨야 한다.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class VersionConflict(RuntimeError):
    def __init__(self, expected: int, actual: int):
        super().__init__(f"state_version 불일치: 요청 {expected}, 현재 {actual}")
        self.expected, self.actual = expected, actual


class StudyStore:
    def __init__(self, path: Optional[Path] = None):
        path = Path(path or os.environ.get("FORMULA1_DEV_DB", "/tmp/formula1/development.db"))
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS studies (
                study_id TEXT PRIMARY KEY, state_json TEXT NOT NULL, state_version INTEGER NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS study_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, study_id TEXT NOT NULL, event_type TEXT NOT NULL,
                idempotency_key TEXT UNIQUE, actor_id TEXT, payload_json TEXT, result_json TEXT,
                state_version INTEGER, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS study_decisions (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, study_id TEXT NOT NULL, decision_json TEXT NOT NULL,
                created_at TEXT NOT NULL);
        """)

    def load(self, study_id: str) -> Optional[Tuple[Dict[str, Any], int]]:
        with self._lock:
            row = self._db.execute("SELECT state_json, state_version FROM studies WHERE study_id=?",
                                   (study_id,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def list(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT state_json FROM studies ORDER BY updated_at DESC LIMIT ?",
                                    (limit,)).fetchall()
        out = []
        for (js,) in rows:
            s = json.loads(js)
            out.append({"study_id": s["study_id"], "status": s["status"], "mode": s["mode"],
                        "candidate_ref": s["candidate_ref"], "title": s.get("title"),
                        "updated_at": s.get("updated_at")})
        return out

    def replay(self, key: Optional[str]) -> Optional[Dict[str, Any]]:
        if not key:
            return None
        with self._lock:
            row = self._db.execute("SELECT result_json FROM study_events WHERE idempotency_key=?",
                                   (key,)).fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def save(self, state: Dict[str, Any], *, expected_version: Optional[int], event_type: str,
             idempotency_key: Optional[str], actor_id: str, payload: Dict[str, Any],
             result: Dict[str, Any], decisions: List[Dict[str, Any]], now: str) -> int:
        """조건부 UPDATE — 버전이 어긋나면 아무것도 쓰지 않는다. 이벤트·결정은 같은 트랜잭션."""
        sid = state["study_id"]
        with self._lock:
            cur = self._db.execute("SELECT state_version FROM studies WHERE study_id=?", (sid,)).fetchone()
            try:
                if cur is None:
                    new_version = 1
                    state["state_version"] = new_version
                    self._db.execute("INSERT INTO studies VALUES (?,?,?,?,?)",
                                     (sid, json.dumps(state, ensure_ascii=False), new_version, now, now))
                else:
                    if expected_version is not None and expected_version != cur[0]:
                        raise VersionConflict(expected_version, cur[0])
                    new_version = cur[0] + 1
                    state["state_version"] = new_version
                    res = self._db.execute(
                        "UPDATE studies SET state_json=?, state_version=?, updated_at=? "
                        "WHERE study_id=? AND state_version=?",
                        (json.dumps(state, ensure_ascii=False), new_version, now, sid, cur[0]))
                    if res.rowcount != 1:
                        raise VersionConflict(expected_version or cur[0], cur[0] + 1)
                result = {**result, "state_version": new_version}
                self._db.execute(
                    "INSERT INTO study_events (study_id, event_type, idempotency_key, actor_id, payload_json,"
                    " result_json, state_version, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (sid, event_type, idempotency_key, actor_id, json.dumps(payload, ensure_ascii=False),
                     json.dumps(result, ensure_ascii=False), new_version, now))
                for d in decisions:
                    self._db.execute("INSERT INTO study_decisions (study_id, decision_json, created_at) VALUES (?,?,?)",
                                     (sid, json.dumps(d, ensure_ascii=False), now))
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return new_version

    def events(self, study_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT seq, event_type, actor_id, payload_json, state_version, created_at FROM study_events "
                "WHERE study_id=? ORDER BY seq", (study_id,)).fetchall()
        return [{"seq": r[0], "event_type": r[1], "actor_id": r[2], "payload": json.loads(r[3] or "{}"),
                 "state_version": r[4], "created_at": r[5]} for r in rows]

    def decisions(self, study_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT decision_json FROM study_decisions WHERE study_id=? ORDER BY seq",
                                    (study_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]
