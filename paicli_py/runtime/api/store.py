"""运行时线程存储 —— 对应 ``com.paicli.runtime.api.RuntimeThreadStore``。"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock


class RuntimeThreadStore:
    """SQLite 持久化（全同步，线程安全，ISO-8601 时间戳）。"""

    def __init__(self, db_path: str | None = None) -> None:
        path = db_path or str(Path.home() / ".paicli" / "runtime" / "runtime.db")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS runtime_threads (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runtime_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL, type TEXT NOT NULL,
                data TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_thread ON runtime_events(thread_id, id);
        """)
        self._conn.commit()

    def create_thread(self) -> str:
        tid = "thread_" + uuid.uuid4().hex[:12]
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute("INSERT INTO runtime_threads VALUES (?, ?)", [tid, now])
            self._conn.execute("INSERT INTO runtime_events (thread_id, type, data, created_at) VALUES (?, ?, ?, ?)", [tid, "thread.created", "{}", now])
            self._conn.commit()
        return tid

    def exists(self, thread_id: str) -> bool:
        return self._conn.execute("SELECT 1 FROM runtime_threads WHERE id = ?", [thread_id]).fetchone() is not None

    def append_event(self, thread_id: str, event_type: str, data: str) -> int:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            cur = self._conn.execute("INSERT INTO runtime_events (thread_id, type, data, created_at) VALUES (?, ?, ?, ?)", [thread_id, event_type, data, now])
            self._conn.commit()
        return cur.lastrowid

    def events(self, thread_id: str, after_id: int = 0) -> list[dict]:
        rows = self._conn.execute("SELECT id, type, data, created_at FROM runtime_events WHERE thread_id=? AND id>? ORDER BY id", [thread_id, after_id]).fetchall()
        return [{"id": r[0], "type": r[1], "data": r[2], "created_at": r[3]} for r in rows]

    def close(self) -> None:
        self._conn.close()
