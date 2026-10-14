"""Lịch chạy Skill: biểu thức cron 5 trường (phút giờ ngày tháng thứ) + vòng kiểm tra nền. Giờ theo múi giờ của máy."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Callable

from ..db import Database, new_id, now
from ..errors import ApiError

CATCH_UP_SECONDS = 3600  # daemon tắt lúc đến giờ: nếu bật lại trong 1 giờ thì chạy bù một lần, quá thì bỏ qua lần đó
MIN_INTERVAL_MIN = 5     # chống đặt lịch dày đặc làm treo máy (mỗi lần chạy là một lượt Agent)
RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]


def _field(spec: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, _, st = part.partition("/")
            if not st.isdigit() or int(st) < 1:
                raise ValueError(f"bước không hợp lệ: {st!r}")
            step = int(st)
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            x, _, y = part.partition("-")
            a, b = int(x), int(y)
        else:
            a = b = int(part)
            if step != 1:
                b = hi
        if a < lo or b > hi or a > b:
            raise ValueError(f"ngoài khoảng {lo}–{hi}: {part!r}")
        out.update(range(a, b + 1, step))
    return out


def parse_cron(expr: str) -> list[set[int]]:
    parts = expr.split()
    if len(parts) != 5:
        raise ApiError(400, "CRON_INVALID", "Cron cần đúng 5 trường: phút giờ ngày tháng thứ (ví dụ 0 8 * * *)")
    try:
        sets = [_field(p, lo, hi) for p, (lo, hi) in zip(parts, RANGES)]
    except ValueError as e:
        raise ApiError(400, "CRON_INVALID", f"Cron không hợp lệ: {e}")
    sets[4] = {d % 7 for d in sets[4]}  # 7 = Chủ nhật = 0
    return sets


def next_run(expr: str, after: datetime) -> datetime:
    mi, ho, dom, mo, dow = parse_cron(expr)
    dom_any, dow_any = expr.split()[2] == "*", expr.split()[4] == "*"
    t = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    def day_ok(d: datetime) -> bool:
        dm, dw = d.day in dom, (d.isoweekday() % 7) in dow
        if dom_any and dow_any:
            return True
        if dom_any:
            return dw
        if dow_any:
            return dm
        return dm or dw          # chuẩn cron: cả hai bị ràng buộc → khớp một trong hai

    for _ in range(366 * 24 * 60):
        if t.month not in mo or not day_ok(t):
            t = (t + timedelta(days=1)).replace(hour=0, minute=0)
        elif t.hour not in ho:
            t = (t + timedelta(hours=1)).replace(minute=0)
        elif t.minute not in mi:
            t += timedelta(minutes=1)
        else:
            return t
    raise ApiError(400, "CRON_INVALID", "Biểu thức cron không bao giờ khớp trong 1 năm tới")


def validate_interval(expr: str) -> None:
    a = next_run(expr, datetime(2026, 1, 1))
    b = next_run(expr, a)
    if (b - a) < timedelta(minutes=MIN_INTERVAL_MIN):
        raise ApiError(400, "CRON_TOO_FREQUENT", f"Lịch phải cách nhau tối thiểu {MIN_INTERVAL_MIN} phút")


class ScheduleStore:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _fmt(r: dict) -> dict:
        return {"id": r["id"], "projectId": r["project_id"], "skill": r["skill"], "message": r["message"], "cron": r["cron"], "enabled": bool(r["enabled"]),
                "autoApprove": bool(r["auto_approve"]), "lastRunAt": r["last_run_at"], "nextRunAt": r["next_run_at"], "lastThreadId": r["last_thread_id"]}

    def list(self, pid: str | None = None) -> list[dict]:
        rows = self.db.all("SELECT * FROM schedule WHERE project_id=? ORDER BY created_at" if pid else "SELECT * FROM schedule ORDER BY created_at",
                           (pid,) if pid else ())
        return [self._fmt(r) for r in rows]

    def get(self, sid: str) -> dict:
        r = self.db.one("SELECT * FROM schedule WHERE id=?", (sid,))
        if not r:
            raise ApiError(404, "SCHEDULE_NOT_FOUND", "Không có lịch này")
        return self._fmt(r)

    def create(self, pid: str, message: str, cron: str, skill: str | None, auto_approve: bool, enabled: bool = True,
               at: datetime | None = None) -> dict:
        message = message.strip()
        if not (3 <= len(message) <= 4000):
            raise ApiError(400, "VALIDATION_FAILED", "Nội dung yêu cầu 3–4000 ký tự")
        validate_interval(cron)
        sid = new_id("sch_")
        nxt = next_run(cron, at or datetime.now()).timestamp()
        self.db.execute("INSERT INTO schedule(id, project_id, skill, message, cron, enabled, auto_approve, next_run_at, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (sid, pid, skill, message, cron, int(enabled), int(auto_approve), nxt, now()))
        return self.get(sid)

    def update(self, sid: str, **f) -> dict:
        cur = self.get(sid)
        if "cron" in f:
            validate_interval(f["cron"])
            self.db.execute("UPDATE schedule SET cron=?, next_run_at=? WHERE id=?", (f["cron"], next_run(f["cron"], datetime.now()).timestamp(), sid))
        if "enabled" in f:
            nxt = next_run(f.get("cron", cur["cron"]), datetime.now()).timestamp() if f["enabled"] else cur["nextRunAt"]
            self.db.execute("UPDATE schedule SET enabled=?, next_run_at=? WHERE id=?", (int(f["enabled"]), nxt, sid))
        for k, col in (("message", "message"), ("skill", "skill"), ("autoApprove", "auto_approve")):
            if k in f:
                self.db.execute(f"UPDATE schedule SET {col}=? WHERE id=?", (int(f[k]) if k == "autoApprove" else f[k], sid))  # noqa: S608 — tên cột lấy từ bảng cố định ở trên
        return self.get(sid)

    def delete(self, sid: str) -> None:
        self.get(sid)
        self.db.execute("DELETE FROM schedule WHERE id=?", (sid,))

    def mark_run(self, sid: str, thread_id: str | None, when: datetime) -> None:
        s = self.get(sid)
        self.db.execute("UPDATE schedule SET last_run_at=?, last_thread_id=?, next_run_at=? WHERE id=?",
                        (when.timestamp(), thread_id, next_run(s["cron"], when).timestamp(), sid))

    def disable(self, sid: str) -> None:
        self.db.execute("UPDATE schedule SET enabled=0 WHERE id=?", (sid,))


class Scheduler:
    """Kiểm tra lịch mỗi `interval` giây; đến hạn thì gọi `run(schedule)` (tạo hội thoại + chạy Agent)."""

    def __init__(self, store: ScheduleStore, run: Callable[[dict], str | None], interval: float = 15.0, clock: Callable[[], datetime] = datetime.now):
        self.store, self.run, self.interval, self.clock = store, run, interval, clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self) -> list[str]:
        fired: list[str] = []
        t = self.clock()
        for s in self.store.list():
            if not s["enabled"] or s["nextRunAt"] is None or s["nextRunAt"] > t.timestamp():
                continue
            if t.timestamp() - s["nextRunAt"] > CATCH_UP_SECONDS:  # bỏ lần lỡ quá lâu
                self.store.mark_run(s["id"], s["lastThreadId"], t)
                continue
            try:
                tid = self.run(s)
            except ApiError as e:
                if e.status == 404:        # project đã bị xoá
                    self.store.disable(s["id"])
                    continue
                tid = None                 # lỗi tạm (LLM tắt…): thử lại ở lần sau
                self.store.db.execute("UPDATE schedule SET next_run_at=? WHERE id=?", (t.timestamp() + 300, s["id"]))
                continue
            self.store.mark_run(s["id"], tid, t)
            fired.append(s["id"])
        return fired

    def start(self) -> None:
        def loop() -> None:
            while not self._stop.wait(self.interval):
                try:
                    self.tick()
                except Exception:  # noqa: BLE001 — vòng lịch không bao giờ được chết vì một lỗi
                    time.sleep(1)
        self._thread = threading.Thread(target=loop, daemon=True, name="scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
