"""Hội thoại (thread), tin nhắn và phê duyệt của Agent. Nguồn sự thật duy nhất là SQLite; UI chỉ hiển thị lại."""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from ..db import Database, dumps, new_id, now
from ..errors import ApiError
from ..events import EventBus

MAX_TEXT = 8000


class ThreadStore:
    def __init__(self, db: Database, bus: EventBus):
        self.db, self.bus = db, bus
        self._gates: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        # phê duyệt đang chờ của lần chạy trước (daemon tắt giữa chừng) không còn ai chờ → hết hiệu lực
        self.db.execute("UPDATE approval SET status='expired', decided_at=? WHERE status='pending'", (now(),))

    # ---- thread ----
    @staticmethod
    def _thread(r: dict) -> dict:
        return {"id": r["id"], "projectId": r["project_id"], "title": r["title"], "createdAt": r["created_at"],
                "autoApprove": bool(r["auto_approve"]), "skill": r["skill"], "runJobId": r["run_job_id"]}

    def create(self, pid: str, title: str = "", skill: str | None = None, auto_approve: bool = False) -> dict:
        tid = new_id("thr_")
        self.db.execute("INSERT INTO thread(id, project_id, title, created_at, auto_approve, skill) VALUES(?,?,?,?,?,?)",
                        (tid, pid, (title or "Hội thoại mới").strip()[:120], now(), int(auto_approve), skill))
        return self.get(tid)

    def get(self, tid: str) -> dict:
        r = self.db.one("SELECT * FROM thread WHERE id=?", (tid,))
        if not r:
            raise ApiError(404, "THREAD_NOT_FOUND", "Không có hội thoại này")
        return self._thread(r)

    def list(self, pid: str) -> list[dict]:
        return [self._thread(r) for r in self.db.all("SELECT * FROM thread WHERE project_id=? ORDER BY created_at DESC", (pid,))]

    def update(self, tid: str, **fields: Any) -> None:
        cols = {"title": "title", "skill": "skill", "run_job_id": "run_job_id", "auto_approve": "auto_approve"}
        sets = [f"{cols[k]}=?" for k in fields if k in cols]
        if sets:
            self.db.execute(f"UPDATE thread SET {', '.join(sets)} WHERE id=?",  # noqa: S608 — tên cột từ whitelist `cols`
                             (*[int(v) if k == 'auto_approve' else v for k, v in fields.items() if k in cols], tid))

    # ---- tin nhắn ----
    def add(self, tid: str, role: str, kind: str, content: dict, job_id: str | None = None) -> dict:
        th = self.get(tid)
        text = dumps(content)
        if len(text) > 60_000:  # observation quá lớn không lưu nguyên
            content = {**content, "data": None, "truncated": True}
            text = dumps(content)
        cur = self.db.execute("INSERT INTO message(thread_id, role, kind, content_json, created_at) VALUES(?,?,?,?,?)", (tid, role, kind, text, now()))
        msg = {"id": cur.lastrowid, "threadId": tid, "role": role, "kind": kind, "content": content, "createdAt": time.time()}
        self.bus.publish(f"agent.{kind}", msg, th["projectId"], job_id)
        return msg

    def messages(self, tid: str, limit: int = 500) -> list[dict]:
        rows = self.db.all("SELECT * FROM message WHERE thread_id=? ORDER BY id LIMIT ?", (tid, limit))
        return [{"id": r["id"], "threadId": tid, "role": r["role"], "kind": r["kind"], "content": json.loads(r["content_json"]),
                 "createdAt": r["created_at"]} for r in rows]

    # ---- phê duyệt ----
    def request_approval(self, tid: str, job_id: str, tool: str, args: dict, category: str, reason: str) -> str:
        th = self.get(tid)
        aid = new_id("apr_")
        self.db.execute("INSERT INTO approval(id, job_id, reason, estimate_json, status, thread_id, created_at) VALUES(?,?,?,?,?,?,?)",
                        (aid, job_id, reason, dumps({"tool": tool, "args": args, "category": category}), "pending", tid, now()))
        with self._lock:
            self._gates[aid] = threading.Event()
        self.bus.publish("approval.requested", {"approvalId": aid, "threadId": tid, "tool": tool, "args": args, "category": category,
                                                "reason": reason}, th["projectId"], job_id)
        return aid

    def approval(self, aid: str) -> dict:
        r = self.db.one("SELECT * FROM approval WHERE id=?", (aid,))
        if not r:
            raise ApiError(404, "APPROVAL_NOT_FOUND", "Không có yêu cầu phê duyệt này")
        est = json.loads(r["estimate_json"] or "{}")
        return {"id": r["id"], "threadId": r["thread_id"], "jobId": r["job_id"], "status": r["status"], "reason": r["reason"],
                "tool": est.get("tool"), "args": est.get("args", {}), "category": est.get("category"), "createdAt": r["created_at"],
                "decidedAt": r["decided_at"]}

    def approvals(self, thread_id: str | None = None, status: str | None = None) -> list[dict]:
        sql, params = "SELECT id FROM approval WHERE 1=1", []
        if thread_id:
            sql += " AND thread_id=?"
            params.append(thread_id)
        if status:
            sql += " AND status=?"
            params.append(status)
        return [self.approval(r["id"]) for r in self.db.all(sql + " ORDER BY created_at", params)]

    def resolve(self, aid: str, decision: str, auto: bool = False) -> dict:
        if decision not in ("approve", "reject"):
            raise ApiError(400, "VALIDATION_FAILED", "decision phải là approve hoặc reject")
        a = self.approval(aid)
        if a["status"] != "pending":
            raise ApiError(409, "APPROVAL_ALREADY_RESOLVED", f"Yêu cầu đã ở trạng thái '{a['status']}'")
        status = "approved" if decision == "approve" else "rejected"
        self.db.execute("UPDATE approval SET status=?, decided_at=? WHERE id=?", (status, now(), aid))
        th = self.get(a["threadId"])
        self.bus.publish("approval.resolved", {"approvalId": aid, "threadId": a["threadId"], "status": status, "auto": auto}, th["projectId"], a["jobId"])
        with self._lock:
            gate = self._gates.get(aid)
        if gate:
            gate.set()
        return self.approval(aid)

    def wait_approval(self, aid: str, cancelled, timeout: float) -> str:
        """Chặn tới khi có quyết định. Trả về approved | rejected | timeout. `cancelled()` True → ném lại cho vòng lặp xử lý."""
        with self._lock:
            gate = self._gates.get(aid)
        end = time.time() + timeout
        while gate and not gate.wait(0.3):
            if cancelled():
                self.db.execute("UPDATE approval SET status='expired', decided_at=? WHERE id=? AND status='pending'", (now(), aid))
                return "cancelled"
            if time.time() > end:
                self.db.execute("UPDATE approval SET status='expired', decided_at=? WHERE id=? AND status='pending'", (now(), aid))
                return "timeout"
        with self._lock:
            self._gates.pop(aid, None)
        return self.approval(aid)["status"]
