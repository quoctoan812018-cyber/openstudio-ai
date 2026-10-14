"""Project / Revision (phiên bản) / Artifact / thư viện file."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable

from .db import Database, dumps, new_id, now
from .errors import ApiError
from .events import EventBus
from .tools import TOOL_IDS

KIND_BY_EXT = {
    ".mp4": "video", ".mov": "video", ".mkv": "video", ".webm": "video",
    ".wav": "audio", ".mp3": "audio", ".flac": "audio", ".m4a": "audio",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".srt": "subtitle", ".vtt": "subtitle", ".ass": "subtitle",
    ".txt": "text", ".md": "text", ".json": "text",
}


Reducer = Callable[[dict, str, dict], dict]


def generic_reducer(state: dict, type: str, payload: dict) -> dict:
    if type != "set-config":
        raise ApiError(400, "VALIDATION_FAILED", f"Lệnh không hỗ trợ: {type}")
    config = payload.get("config")
    if not isinstance(config, dict):
        raise ApiError(400, "VALIDATION_FAILED", "payload.config phải là object")
    return {"config": config}


class Repo:
    def __init__(self, db: Database, bus: EventBus, projects_dir: Path):
        self.db, self.bus, self.projects_dir = db, bus, projects_dir
        self.reducers: dict[str, Reducer] = {}

    # ---- project ----
    @staticmethod
    def _project(r: dict) -> dict:
        return {"id": r["id"], "name": r["name"], "createdAt": r["created_at"], "settings": json.loads(r["settings_json"])}

    def create_project(self, name: str) -> dict:
        pid = new_id("prj_")
        (self.projects_dir / pid).mkdir(parents=True, exist_ok=True)
        self.db.execute("INSERT INTO project(id, name, created_at) VALUES(?,?,?)", (pid, name, now()))
        self.bus.publish("project.created", {"name": name}, pid)
        return self.get_project(pid)

    def get_project(self, pid: str) -> dict:
        r = self.db.one("SELECT * FROM project WHERE id=?", (pid,))
        if not r:
            raise ApiError(404, "PROJECT_NOT_FOUND", "Không có project này")
        return self._project(r)

    def list_projects(self) -> list[dict]:
        return [self._project(r) for r in self.db.all("SELECT * FROM project ORDER BY created_at DESC")]

    def rename_project(self, pid: str, name: str) -> dict:
        self.get_project(pid)
        self.db.execute("UPDATE project SET name=? WHERE id=?", (name, pid))
        return self.get_project(pid)

    def delete_project(self, pid: str) -> None:
        self.get_project(pid)
        self.db.execute("DELETE FROM project WHERE id=?", (pid,))
        shutil.rmtree(self.projects_dir / pid, ignore_errors=True)
        self.bus.publish("project.deleted", {}, pid)

    # ---- state machine tối giản + phiên bản ----
    def get_state(self, pid: str, tool: str) -> dict:
        self.get_project(pid)
        self._check_tool(tool)
        r = self.db.one("SELECT * FROM tool_state WHERE project_id=? AND tool=?", (pid, tool))
        if not r:
            return {"projectId": pid, "tool": tool, "revision": 0, "state": {}}
        return {"projectId": pid, "tool": tool, "revision": r["revision"], "state": json.loads(r["state_json"])}

    @staticmethod
    def _check_tool(tool: str) -> None:
        if tool not in TOOL_IDS:
            raise ApiError(404, "TOOL_NOT_FOUND", f"Không có công cụ '{tool}'")

    def apply_command(self, pid: str, tool: str, type: str, payload: dict, expected_revision: int | None,
                      author: str = "ui") -> dict:
        """Mọi thay đổi (UI, Agent hay job) đi qua đây và tạo REVISION MỚI (snapshot đầy đủ), không bao giờ ghi đè.

        Mỗi công cụ có thể đăng ký reducer riêng: reducer(state, type, payload) -> state mới."""
        self.get_project(pid)
        self._check_tool(tool)
        with self.db.transaction():
            cur = self.db.one("SELECT * FROM tool_state WHERE project_id=? AND tool=?", (pid, tool))
            current = cur["revision"] if cur else 0
            if expected_revision is not None and expected_revision != current:
                raise ApiError(409, "REVISION_CONFLICT", "Trạng thái đã thay đổi, hãy tải lại",
                               {"expected": expected_revision, "current": current})
            parent = self.db.one("SELECT id FROM revision WHERE project_id=? AND tool=? AND n=?", (pid, tool, current))
            old = json.loads(cur["state_json"]) if cur else {}
            old.pop("revisionId", None)
            if type == "select-revision":
                src = self.db.one("SELECT config_json FROM revision WHERE id=? AND project_id=? AND tool=?",
                                  (payload.get("revisionId"), pid, tool))
                if not src:
                    raise ApiError(404, "REVISION_NOT_FOUND", "Không có phiên bản này")
                new_state = json.loads(src["config_json"])
            else:
                reducer = self.reducers.get(tool, generic_reducer)
                new_state = reducer(old, type, payload)
            n = current + 1
            rid = new_id("rev_")
            self.db.execute(
                "INSERT INTO revision(id, project_id, tool, n, parent_id, config_json, created_at, author) VALUES(?,?,?,?,?,?,?,?)",
                (rid, pid, tool, n, parent["id"] if parent else None, dumps(new_state), now(), author))
            state = {**new_state, "revisionId": rid}
            self.db.execute(
                "INSERT INTO tool_state(project_id, tool, revision, state_json) VALUES(?,?,?,?) "
                "ON CONFLICT(project_id, tool) DO UPDATE SET revision=excluded.revision, state_json=excluded.state_json",
                (pid, tool, n, dumps(state)))
        self.bus.publish("state.changed", {"tool": tool, "revision": n, "revisionId": rid, "command": type}, pid)
        return {"projectId": pid, "tool": tool, "revision": n, "state": state}

    def list_revisions(self, pid: str, tool: str) -> list[dict]:
        self.get_project(pid)
        self._check_tool(tool)
        return [{"id": r["id"], "n": r["n"], "parentId": r["parent_id"], "author": r["author"],
                 "createdAt": r["created_at"], "state": json.loads(r["config_json"])}
                for r in self.db.all("SELECT * FROM revision WHERE project_id=? AND tool=? ORDER BY n DESC", (pid, tool))]

    # ---- artifact & thư viện file ----
    def list_artifacts(self, pid: str) -> list[dict]:
        self.get_project(pid)
        return [{"id": r["id"], "kind": r["kind"], "path": r["path"], "bytes": r["bytes"], "stale": bool(r["stale"]),
                 "createdAt": r["created_at"]}
                for r in self.db.all("SELECT * FROM artifact WHERE project_id=? ORDER BY created_at DESC", (pid,))]

    def library(self, project_id: str | None = None) -> list[dict]:
        ids = [project_id] if project_id else [p["id"] for p in self.list_projects()]
        out: list[dict] = []
        for pid in ids:
            base = self.projects_dir / pid
            if not base.is_dir():
                continue
            for p in sorted(base.rglob("*")):
                if p.is_file() and not p.name.startswith(".") and p.suffix != ".part":
                    st = p.stat()
                    out.append({"projectId": pid, "path": p.relative_to(base).as_posix(), "bytes": st.st_size,
                                "modifiedAt": st.st_mtime, "kind": KIND_BY_EXT.get(p.suffix.lower(), "file")})
        return out
