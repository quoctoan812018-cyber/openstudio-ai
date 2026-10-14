"""Hàng đợi tác vụ: pool luồng + vòng đời job lưu SQLite, tiến độ chuẩn hoá qua event bus."""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .db import Database, dumps, new_id, now
from .errors import ApiError
from .events import EventBus
from .security import redact


class JobCancelled(Exception):
    pass


class JobContext:
    def __init__(self, runner: "JobRunner", job_id: str, project_id: str | None, params: dict):
        self.runner, self.job_id, self.project_id, self.params = runner, job_id, project_id, params
        self._cancel = runner._cancel_flags[job_id]

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check_cancel(self) -> None:
        if self._cancel.is_set():
            raise JobCancelled()

    def progress(self, phase: str, percent: float, message: str = "", completed: int = 0, failed: int = 0,
                 total: int = 0) -> None:
        """Schema tiến độ chuẩn: phase, percent, message, completed, failed, total."""
        p = {"phase": phase, "percent": round(max(0.0, min(100.0, percent)), 1), "message": message,
             "completed": completed, "failed": failed, "total": total}
        self.runner.db.execute("UPDATE job SET progress_json=? WHERE id=?", (dumps(p), self.job_id))
        self.runner.bus.publish("job.progress", p, self.project_id, self.job_id)


Handler = Callable[[JobContext], dict | None]


class JobRunner:
    def __init__(self, db: Database, bus: EventBus, workers: int = 2):
        self.db, self.bus = db, bus
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")
        # Lượt chạy của Agent đứng chờ job con (và chờ người duyệt) rất lâu → pool riêng để không chiếm hết worker của job thật
        self._agent_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent")
        self._handlers: dict[str, Handler] = {}
        self._cancel_flags: dict[str, threading.Event] = {}
        self.recover()

    def recover(self) -> None:
        """Job đang dở khi daemon tắt → đánh dấu failed(interrupted) để người dùng chạy lại."""
        err = dumps({"code": "INTERRUPTED", "message": "Daemon tắt giữa chừng"})
        self.db.execute("UPDATE job SET status='failed', error_json=?, finished_at=? WHERE status IN ('queued','running')",
                        (err, now()))

    def register(self, type: str, handler: Handler) -> None:
        self._handlers[type] = handler

    def submit(self, type: str, params: dict | None = None, project_id: str | None = None, tool: str | None = None,
               hw_requirement: str | None = None) -> dict:
        if type not in self._handlers:
            raise ApiError(400, "VALIDATION_FAILED", f"Loại job không hợp lệ: {type}")
        job_id = new_id("job_")
        params = params or {}
        self._cancel_flags[job_id] = threading.Event()
        self.db.execute(
            "INSERT INTO job(id, project_id, tool, type, status, created_at, hw_requirement) VALUES(?,?,?,?,?,?,?)",
            (job_id, project_id, tool, type, "queued", now(), hw_requirement),
        )
        self.bus.publish("job.queued", {"type": type, "tool": tool}, project_id, job_id)
        (self._agent_pool if type.startswith("agent.") else self._pool).submit(self._run, job_id, type, project_id, params)
        return self.get(job_id)  # type: ignore[return-value]

    def _set_status(self, job_id: str, status: str, error: dict | None = None, result: dict | None = None) -> None:
        sets, vals = ["status=?"], [status]
        if result is not None:
            sets.append("result_json=?"); vals.append(dumps(result))
        if status == "running":
            sets.append("started_at=?"); vals.append(now())
        if status in ("succeeded", "failed", "cancelled"):
            sets.append("finished_at=?"); vals.append(now())
        if error:
            sets.append("error_json=?"); vals.append(dumps(error))
        self.db.execute(f"UPDATE job SET {', '.join(sets)} WHERE id=?", (*vals, job_id))  # noqa: S608 — `sets` chỉ gồm chuỗi cố định "col=?"

    def _run(self, job_id: str, type: str, project_id: str | None, params: dict) -> None:
        flag = self._cancel_flags[job_id]
        if flag.is_set():
            self._set_status(job_id, "cancelled")
            self.bus.publish("job.cancelled", {}, project_id, job_id)
            return
        self._set_status(job_id, "running")
        self.bus.publish("job.started", {"type": type}, project_id, job_id)
        ctx = JobContext(self, job_id, project_id, params)
        try:
            result = self._handlers[type](ctx) or {}
            self._set_status(job_id, "succeeded", result=result)
            self.bus.publish("job.succeeded", result, project_id, job_id)
        except JobCancelled:
            self._set_status(job_id, "cancelled")
            self.bus.publish("job.cancelled", {}, project_id, job_id)
        except ApiError as e:
            err = {"code": e.code, "message": redact(e.message)}
            self._set_status(job_id, "failed", err)
            self.bus.publish("job.failed", err, project_id, job_id)
        except Exception as e:  # noqa: BLE001 — mọi lỗi handler đều phải thành job.failed
            err = {"code": "JOB_FAILED", "message": redact(str(e))}
            self._set_status(job_id, "failed", err)
            self.bus.publish("job.failed", err, project_id, job_id)
        finally:
            self._cancel_flags.pop(job_id, None)

    def cancel(self, job_id: str) -> dict:
        job = self.get(job_id)
        if not job:
            raise ApiError(404, "JOB_NOT_FOUND", "Không có job này")
        flag = self._cancel_flags.get(job_id)
        if flag and job["status"] in ("queued", "running"):
            flag.set()
        return job

    @staticmethod
    def _fmt(r: dict) -> dict:
        return {
            "id": r["id"], "projectId": r["project_id"], "tool": r["tool"], "type": r["type"], "status": r["status"],
            "progress": json.loads(r["progress_json"]) if r["progress_json"] else None,
            "error": json.loads(r["error_json"]) if r["error_json"] else None,
            "result": json.loads(r["result_json"]) if r.get("result_json") else None,
            "createdAt": r["created_at"], "startedAt": r["started_at"], "finishedAt": r["finished_at"],
        }

    def get(self, job_id: str) -> dict | None:
        r = self.db.one("SELECT * FROM job WHERE id=?", (job_id,))
        return self._fmt(r) if r else None

    def list(self, project_id: str | None = None, limit: int = 100) -> list[dict]:
        if project_id:
            rows = self.db.all("SELECT * FROM job WHERE project_id=? ORDER BY created_at DESC LIMIT ?", (project_id, limit))
        else:
            rows = self.db.all("SELECT * FROM job ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._fmt(r) for r in rows]

    def shutdown(self) -> None:
        for f in self._cancel_flags.values():
            f.set()
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._agent_pool.shutdown(wait=False, cancel_futures=True)


def demo_sleep_handler(ctx: JobContext) -> dict:
    """Job mẫu để kiểm thử hàng đợi/tiến độ/huỷ."""
    import time
    steps = int(ctx.params.get("steps", 5))
    delay = float(ctx.params.get("delay", 0.05))
    for i in range(steps):
        ctx.check_cancel()
        time.sleep(delay)
        ctx.progress("demo", (i + 1) / steps * 100, f"Bước {i + 1}/{steps}", completed=i + 1, total=steps)
    return {"steps": steps}
