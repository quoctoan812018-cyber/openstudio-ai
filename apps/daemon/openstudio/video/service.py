"""Ảnh → video chuyển động (FFmpeg `zoompan`). KHÔNG sinh nội dung mới như mô hình AI; chỉ làm ảnh tĩnh "sống" hơn bằng chuyển động máy quay."""
from __future__ import annotations

import time

from ..assets import AssetStore
from ..config import Settings
from ..editor.render import canvas
from ..errors import ApiError
from ..jobs import JobContext, JobRunner
from ..media import run_ffmpeg
from ..repo import Repo
from .state import TOOL, initial_state, reducer


def engines(machine_tier: str) -> list[dict]:
    return [
        {"id": "motion", "name": "Ảnh → video chuyển động (FFmpeg)", "available": True, "implemented": True, "generative": False, "minTier": "cpu",
         "note": "Zoom/lia máy trên ảnh tĩnh. Không phải AI sinh video."},
        {"id": "wan2.2-ti2v-5b", "name": "Wan2.2 TI2V 5B (sinh video AI)", "available": machine_tier == "gpu16plus", "implemented": False, "generative": True, "minTier": "gpu16plus",
         "note": "Cần GPU ≥ 16 GB VRAM; chưa tích hợp (không thể kiểm thử trên máy CPU; trên CPU một clip vài giây mất hàng giờ)."},
    ]


def zoompan_filter(preset: str, frames: int, w: int, h: int, fps: int, strength: float) -> str:
    """Biểu thức zoompan theo chỉ số khung `on` (0..frames-1). Ảnh được phóng 2× trước để chuyển động mượt (ít rung điểm ảnh)."""
    n = max(1, frames - 1)
    t = f"(on/{n})"
    k = f"{strength:.3f}"
    z, x, y = {
        "zoom-in": (f"1+{k}*{t}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
        "zoom-out": (f"1+{k}*(1-{t})", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
        "pan-left": (f"1+{k}", f"(iw-iw/zoom)*(1-{t})", "ih/2-(ih/zoom/2)"),
        "pan-right": (f"1+{k}", f"(iw-iw/zoom)*{t}", "ih/2-(ih/zoom/2)"),
        "pan-up": (f"1+{k}", "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*(1-{t})"),
        "pan-down": (f"1+{k}", "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*{t}"),
    }[preset]
    return (f"scale={2 * w}:{2 * h}:force_original_aspect_ratio=increase,crop={2 * w}:{2 * h},"
            f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps},format=yuv420p")


class VideoService:
    def __init__(self, settings: Settings, repo: Repo, runner: JobRunner, assets: AssetStore):
        self.s, self.repo, self.runner, self.assets = settings, repo, runner, assets
        repo.reducers[TOOL] = reducer
        runner.register("video.motion", self._job)

    def state(self, pid: str) -> dict:
        st = self.repo.get_state(pid, TOOL)["state"]
        return {**initial_state(), **st} if st else initial_state()

    def commit(self, pid: str, type: str, payload: dict) -> dict:
        return self.repo.apply_command(pid, TOOL, type, payload, None, author="job")

    def start(self, pid: str) -> dict:
        b = self.state(pid)["brief"]
        if not b["asset"]:
            raise ApiError(409, "ASSET_REQUIRED", "Hãy chọn một ảnh")
        if self.assets.get(pid, b["asset"])["kind"] != "image":
            raise ApiError(400, "VALIDATION_FAILED", "Cần một tài nguyên dạng ảnh")
        if b["audio"] and not self.assets.get(pid, b["audio"])["hasAudio"]:
            raise ApiError(400, "VALIDATION_FAILED", "Tài nguyên âm thanh không có tiếng")
        return self.runner.submit("video.motion", {}, pid, TOOL)

    def _job(self, ctx: JobContext) -> dict:
        pid = ctx.project_id
        base = self.s.projects_dir / pid
        b = self.state(pid)["brief"]
        img = base / self.assets.get(pid, b["asset"])["path"]
        w, h = canvas({"aspect": b["aspect"], "quality": b["quality"]}, False)
        dur, fps = float(b["duration"]), int(b["fps"])
        frames = int(round(dur * fps))
        out_dir = base / "exports" / "video"
        out_dir.mkdir(parents=True, exist_ok=True)
        name = f"motion_{int(time.time())}_{b['preset']}.mp4"
        inputs = ["-loop", "1", "-framerate", str(fps), "-i", str(img)]
        maps = ["-map", "0:v"]
        audio = []
        if b["audio"]:
            inputs += ["-i", str(base / self.assets.get(pid, b["audio"])["path"])]
            maps += ["-map", "1:a"]
            audio = ["-af", f"afade=t=out:st={max(0.0, dur - 1.5):.2f}:d=1.5", "-c:a", "aac", "-b:a", "160k"]
        ctx.progress("render", 2, "Dựng chuyển động")
        run_ffmpeg([*inputs, "-vf", zoompan_filter(b["preset"], frames, w, h, fps, float(b["strength"])), *maps, "-frames:v", str(frames), "-t", f"{dur:.3f}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", *audio, "-movflags", "+faststart", name], dur, out_dir,
                   on_progress=lambda p: ctx.progress("render", p, "Dựng chuyển động"), cancelled=ctx.cancelled)
        rel = f"exports/video/{name}"
        asset = self.assets.register_existing(pid, rel, name)
        result = {"path": rel, "assetId": asset["id"], "duration": dur, "preset": b["preset"], "generative": False}
        self.commit(pid, "_set-result", {"result": result})
        ctx.progress("done", 100, "Hoàn tất")
        return result
