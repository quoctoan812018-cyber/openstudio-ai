"""Chỉnh sửa video: gắn tài nguyên vào dòng thời gian, xem trước nhanh, xuất bản cuối (FFmpeg)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from ..assets import AssetStore
from ..config import Settings
from ..errors import ApiError
from ..jobs import JobContext, JobRunner
from ..media import run_ffmpeg
from ..repo import Repo
from .render import build
from .state import TOOL, initial_state, reducer


def ai_watermark_enabled(settings: Settings) -> bool:
    try:
        return bool(json.loads(settings.settings_file.read_text(encoding="utf-8")).get("ai_label_watermark", False))
    except (OSError, ValueError):
        return False


class EditorService:
    def __init__(self, settings: Settings, repo: Repo, runner: JobRunner, assets: AssetStore):
        self.s, self.repo, self.runner, self.assets = settings, repo, runner, assets
        repo.reducers[TOOL] = reducer
        runner.register("editor.render", self._job_render)

    def state(self, pid: str) -> dict:
        st = self.repo.get_state(pid, TOOL)["state"]
        return {**initial_state(), **st} if st else initial_state()

    def commit(self, pid: str, type: str, payload: dict, author: str = "ui") -> dict:
        return self.repo.apply_command(pid, TOOL, type, payload, None, author=author)

    def attach(self, pid: str, kind: str, asset_id: str, params: dict, author: str = "ui") -> dict:
        a = self.assets.get(pid, asset_id)
        if kind == "segment":
            if a["kind"] == "audio":
                raise ApiError(400, "VALIDATION_FAILED", "Track chính nhận video hoặc ảnh; audio hãy đặt làm nhạc nền")
            payload = {"asset": asset_id, "kind": a["kind"], "name": a["name"], "srcDuration": a["duration"], "hasAudio": a["hasAudio"], **params}
            return self.commit(pid, "_add-segment", payload, author)
        if kind == "overlay":
            if a["kind"] == "audio":
                raise ApiError(400, "VALIDATION_FAILED", "Lớp chèn nhận ảnh hoặc video")
            return self.commit(pid, "_add-overlay", {**params, "asset": asset_id, "kind": a["kind"], "name": a["name"]}, author)
        if kind == "music":
            if not a["hasAudio"]:
                raise ApiError(400, "VALIDATION_FAILED", "Tài nguyên này không có âm thanh")
            return self.commit(pid, "_set-music", {"asset": asset_id, "name": a["name"]}, author)
        raise ApiError(400, "VALIDATION_FAILED", "kind phải là segment, overlay hoặc music")

    def start_render(self, pid: str, preview: bool) -> dict:
        if not self.state(pid)["segments"]:
            raise ApiError(409, "TIMELINE_EMPTY", "Dòng thời gian trống: hãy thêm ít nhất một đoạn video/ảnh")
        return self.runner.submit("editor.render", {"preview": preview}, pid, TOOL)

    def _job_render(self, ctx: JobContext) -> dict:
        pid, preview = ctx.project_id, bool(ctx.params.get("preview"))
        base = self.s.projects_dir / pid
        st = self.state(pid)
        ids = {x["asset"] for x in st["segments"]} | {x["asset"] for x in st["overlays"]} | ({st["music"]["asset"]} if st["music"].get("asset") else set())
        paths = {aid: str(base / self.assets.get(pid, aid)["path"]) for aid in ids}
        out_dir = base / "exports" / "editor"
        out_dir.mkdir(parents=True, exist_ok=True)
        ass_name = "timeline.preview.ass" if preview else "timeline.ass"
        wm = "Nội dung tạo bởi AI" if (not preview and ai_watermark_enabled(self.s)) else None
        plan = build(st, paths, preview=preview, ass_name=ass_name, watermark=wm)
        if plan.ass:
            (out_dir / ass_name).write_text(plan.ass, encoding="utf-8")
        name = "preview.mp4" if preview else f"edit_{int(time.time())}.mp4"
        quality = ["-crf", "30", "-preset", "ultrafast"] if preview else ["-crf", "20", "-preset", "medium"]
        msg = "Xem trước nhanh" if preview else "Xuất video"
        ctx.progress("render", 1, msg)
        run_ffmpeg([*plan.inputs, "-filter_complex", plan.graph, "-map", plan.out_map[0], "-map", plan.out_map[1], "-r", str(st["settings"]["fps"]),
                    "-c:v", "libx264", *quality, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-t", f"{plan.total:.3f}", name],
                   plan.total, out_dir, on_progress=lambda p: ctx.progress("render", p, msg), cancelled=ctx.cancelled)
        rel = f"exports/editor/{name}"
        self.commit(pid, "_set-result", {"preview": preview, "file": {"path": rel, "duration": round(plan.total, 2), "bytes": Path(out_dir / name).stat().st_size}}, "job")
        ctx.progress("done", 100, "Hoàn tất")
        return {"path": rel, "duration": plan.total, "preview": preview}
