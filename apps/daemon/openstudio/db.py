"""SQLite + migration đánh số. Một kết nối, có khoá, chế độ WAL."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
    CREATE TABLE project(id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at REAL NOT NULL, settings_json TEXT NOT NULL DEFAULT '{}');
    CREATE TABLE tool_state(project_id TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE, tool TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 0, state_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY(project_id, tool));
    CREATE TABLE revision(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
        tool TEXT NOT NULL, n INTEGER NOT NULL, parent_id TEXT, config_json TEXT NOT NULL, created_at REAL NOT NULL,
        author TEXT NOT NULL DEFAULT 'ui', UNIQUE(project_id, tool, n));
    CREATE TABLE job(id TEXT PRIMARY KEY, project_id TEXT, tool TEXT, type TEXT NOT NULL, revision_id TEXT,
        status TEXT NOT NULL, progress_json TEXT, error_json TEXT, created_at REAL NOT NULL, started_at REAL,
        finished_at REAL, hw_requirement TEXT);
    CREATE TABLE artifact(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
        job_id TEXT, kind TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT, bytes INTEGER, meta_json TEXT DEFAULT '{}',
        stale INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
    CREATE TABLE artifact_source(artifact_id TEXT NOT NULL, source_artifact_id TEXT NOT NULL, PRIMARY KEY(artifact_id, source_artifact_id));
    CREATE TABLE approval(id TEXT PRIMARY KEY, job_id TEXT, reason TEXT, estimate_json TEXT, status TEXT NOT NULL, decided_at REAL);
    CREATE TABLE consent(id TEXT PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, statement TEXT NOT NULL,
        project_id TEXT, created_at REAL NOT NULL, evidence_path TEXT);
    CREATE TABLE model(id TEXT PRIMARY KEY, version TEXT, path TEXT, sha256 TEXT, bytes INTEGER, status TEXT NOT NULL, installed_at REAL);
    CREATE TABLE event(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, job_id TEXT, type TEXT NOT NULL,
        payload_json TEXT NOT NULL, ts REAL NOT NULL);
    CREATE INDEX idx_job_project ON job(project_id);
    CREATE INDEX idx_event_project ON event(project_id);
    """),
    (2, "ALTER TABLE job ADD COLUMN result_json TEXT"),
    (3, "ALTER TABLE consent ADD COLUMN used_by TEXT"),
    (4, """
    CREATE TABLE thread(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE, title TEXT NOT NULL,
        created_at REAL NOT NULL, auto_approve INTEGER NOT NULL DEFAULT 0, skill TEXT, run_job_id TEXT);
    CREATE TABLE message(id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL REFERENCES thread(id) ON DELETE CASCADE,
        role TEXT NOT NULL, kind TEXT NOT NULL, content_json TEXT NOT NULL, created_at REAL NOT NULL);
    CREATE INDEX idx_message_thread ON message(thread_id);
    CREATE TABLE schedule(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE, skill TEXT, message TEXT NOT NULL,
        cron TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, auto_approve INTEGER NOT NULL DEFAULT 0, last_run_at REAL, next_run_at REAL,
        last_thread_id TEXT, created_at REAL NOT NULL);
    ALTER TABLE approval ADD COLUMN thread_id TEXT;
    ALTER TABLE approval ADD COLUMN created_at REAL
    """),
]


def new_id(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:16]


def now() -> float:
    return time.time()


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self.migrate()

    def migrate(self) -> None:
        with self._lock:
            self._conn.execute("CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY)")
            row = self._conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()
            current = row["v"] or 0
            for version, sql in MIGRATIONS:
                if version > current:
                    self._conn.execute("BEGIN")
                    try:
                        for stmt in filter(None, (s.strip() for s in sql.split(";"))):
                            self._conn.execute(stmt)
                        self._conn.execute("INSERT INTO schema_version(version) VALUES(?)", (version,))
                        self._conn.execute("COMMIT")
                    except Exception:
                        self._conn.execute("ROLLBACK")
                        raise

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, tuple(params))

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        with self._lock:
            r = self._conn.execute(sql, tuple(params)).fetchone()
            return dict(r) if r else None

    def all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, tuple(params)).fetchall()]

    def transaction(self) -> "_Tx":
        return _Tx(self)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class _Tx:
    def __init__(self, db: Database):
        self.db = db

    def __enter__(self) -> Database:
        self.db._lock.acquire()
        self.db._conn.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, exc_type, *_):
        try:
            self.db._conn.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.db._lock.release()
