"""Event bus: ghi mọi sự kiện vào SQLite (phát lại được) và đẩy tới các subscriber SSE."""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from .db import Database, dumps, now


def _matches(ev: dict, project_id: str | None, job_id: str | None) -> bool:
    return (project_id is None or ev.get("projectId") == project_id) and (job_id is None or ev.get("jobId") == job_id)


class EventBus:
    def __init__(self, db: Database):
        self.db = db
        self.loop: asyncio.AbstractEventLoop | None = None
        self._subs: set[asyncio.Queue] = set()

    def publish(self, type: str, data: dict[str, Any] | None = None, project_id: str | None = None,
                job_id: str | None = None) -> dict:
        ts = now()
        data = data or {}
        cur = self.db.execute(
            "INSERT INTO event(project_id, job_id, type, payload_json, ts) VALUES(?,?,?,?,?)",
            (project_id, job_id, type, dumps(data), ts),
        )
        ev = {"id": cur.lastrowid, "type": type, "projectId": project_id, "jobId": job_id, "ts": ts, "data": data}
        if self.loop is not None:
            for q in list(self._subs):
                try:
                    self.loop.call_soon_threadsafe(q.put_nowait, ev)
                except RuntimeError:  # loop đã đóng
                    pass
        return ev

    def _row_to_event(self, r: dict) -> dict:
        return {"id": r["id"], "type": r["type"], "projectId": r["project_id"], "jobId": r["job_id"],
                "ts": r["ts"], "data": json.loads(r["payload_json"])}

    async def stream(self, project_id: str | None = None, job_id: str | None = None, last_id: int = 0,
                     replay_only: bool = False, heartbeat: float = 15.0) -> AsyncIterator[dict | None]:
        """Yield sự kiện (dict) hoặc None làm heartbeat."""
        q: asyncio.Queue = asyncio.Queue()
        self._subs.add(q)
        try:
            max_id = last_id
            sql, params = "SELECT * FROM event WHERE id > ?", [last_id]
            if project_id:
                sql += " AND project_id = ?"
                params.append(project_id)
            if job_id:
                sql += " AND job_id = ?"
                params.append(job_id)
            for r in self.db.all(sql + " ORDER BY id LIMIT 1000", params):
                ev = self._row_to_event(r)
                max_id = ev["id"]
                yield ev
            if replay_only:
                return
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), heartbeat)
                except TimeoutError:
                    yield None
                    continue
                if ev["id"] > max_id and _matches(ev, project_id, job_id):
                    max_id = ev["id"]
                    yield ev
        finally:
            self._subs.discard(q)
