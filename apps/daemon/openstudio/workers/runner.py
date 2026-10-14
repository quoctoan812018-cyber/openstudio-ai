"""Chạy tiến trình con: đọc stdout theo dòng, huỷ được (kill cả cây tiến trình), giữ đuôi stderr để báo lỗi."""
from __future__ import annotations

import queue
import subprocess
import threading
from pathlib import Path
from typing import Callable

import psutil

from ..jobs import JobCancelled


def kill_tree(pid: int) -> None:
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    for p in [*parent.children(recursive=True), parent]:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass


def run_process(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None,
                on_line: Callable[[str], None], cancelled: Callable[[], bool], on_err_line: Callable[[str], None] | None = None) -> tuple[int, str]:
    """Trả về (exit_code, đuôi stderr). Nếu `cancelled()` thành True: kill và ném JobCancelled."""
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", bufsize=1,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines: queue.Queue[str | None] = queue.Queue()
    err_tail: list[str] = []

    def pump_out() -> None:
        assert proc.stdout
        for line in proc.stdout:
            lines.put(line.rstrip("\r\n"))
        lines.put(None)

    def pump_err() -> None:
        assert proc.stderr
        for line in proc.stderr:
            err_tail.append(line)
            del err_tail[:-40]
            if on_err_line:
                on_err_line(line.rstrip("\r\n"))

    threads = [threading.Thread(target=pump_out, daemon=True), threading.Thread(target=pump_err, daemon=True)]
    for t in threads:
        t.start()
    try:
        while True:
            if cancelled():
                kill_tree(proc.pid)
                raise JobCancelled()
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                break
            on_line(line)
        code = proc.wait()
        threads[1].join(timeout=2)
        return code, "".join(err_tail)
    except BaseException:
        kill_tree(proc.pid)
        raise
