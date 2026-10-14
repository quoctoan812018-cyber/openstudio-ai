"""Avatar AI nói: ảnh chân dung + audio → video hoạt hình theo giọng (engine CPU "puppet"), ghép nền/khung/phụ đề, xuất 16:9 · 9:16 · 1:1."""
from __future__ import annotations

import shutil
import subprocess
import time

import numpy as np
import soundfile as sf

from ..assets import AssetStore
from ..config import Settings
from ..editor.render import texts_to_ass
from ..editor.service import ai_watermark_enabled
from ..errors import ApiError
from ..jobs import JobCancelled, JobContext, JobRunner
from ..media import _exe, extract_audio
from ..repo import Repo
from ..security import redact
from ..subtitles import cues as C
from ..subtitles.service import SubtitleService
from ..tts.service import ai_label_enabled
from . import engine as E
from .library import AvatarLibrary
from .state import TOOL, initial_state, reducer

CANVAS = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1000, 1000)}
MAX_AUDIO_SECONDS = 20 * 60


def engines(machine_tier: str) -> list[dict]:
    """Danh mục engine kèm trạng thái thật: chỉ "puppet" được cài đặt; lip-sync AI bị khoá + giải thích."""
    return [
        {"id": "puppet", "name": "Hoạt hình theo giọng (CPU)", "available": True, "implemented": True, "realLipSync": False, "minTier": "cpu",
         "note": "Miệng mở/đóng theo biên độ giọng, không khớp khẩu hình từng âm. Hợp ảnh minh hoạ/mascot."},
        {"id": "musetalk", "name": "MuseTalk 1.5 (lip-sync nhanh)", "available": machine_tier in ("gpu8", "gpu12", "gpu16plus"), "implemented": False, "realLipSync": True,
         "minTier": "gpu8", "note": "Cần GPU ≥ 6 GB VRAM; chưa tích hợp (chưa thể kiểm thử trên máy CPU). License cần đọc lại trước khi dùng (xem MODEL_LICENSES)."},
        {"id": "latentsync", "name": "LatentSync 1.5 (lip-sync đẹp)", "available": machine_tier in ("gpu8", "gpu12", "gpu16plus"), "implemented": False, "realLipSync": True,
         "minTier": "gpu8", "note": "Cần GPU ≥ 8 GB VRAM; chưa tích hợp."},
    ]


class AvatarService:
    def __init__(self, settings: Settings, repo: Repo, runner: JobRunner, assets: AssetStore, library: AvatarLibrary, subs: SubtitleService):
        self.s, self.repo, self.runner, self.assets, self.lib, self.subs = settings, repo, runner, assets, library, subs
        repo.reducers[TOOL] = reducer
        runner.register("avatar.render", self._job)

    def state(self, pid: str) -> dict:
        st = self.repo.get_state(pid, TOOL)["state"]
        return {**initial_state(), **st} if st else initial_state()

    def commit(self, pid: str, type: str, payload: dict) -> dict:
        return self.repo.apply_command(pid, TOOL, type, payload, None, author="job")

    def start(self, pid: str) -> dict:
        b = self.state(pid)["brief"]
        if not b["avatar"]:
            raise ApiError(409, "AVATAR_REQUIRED", "Hãy chọn một avatar")
        if not b["audio"]:
            raise ApiError(409, "AUDIO_REQUIRED", "Hãy chọn audio (tải lên hoặc dùng kết quả của Giọng đọc/Lồng tiếng/Podcast)")
        self._check_avatar(b["avatar"])
        a = self.assets.get(pid, b["audio"])
        if not a["hasAudio"]:
            raise ApiError(400, "VALIDATION_FAILED", "Tài nguyên được chọn không có âm thanh")
        if a["duration"] > MAX_AUDIO_SECONDS:
            raise ApiError(400, "VALIDATION_FAILED", f"Audio tối đa {MAX_AUDIO_SECONDS // 60} phút")
        return self.runner.submit("avatar.render", {}, pid, TOOL)

    def _check_avatar(self, aid: str) -> dict:
        """Kiểm lại đồng ý TẠI THỜI ĐIỂM XUẤT (không chỉ lúc tạo): avatar người thật phải còn bản ghi đồng ý hợp lệ gắn đúng avatar."""
        m = self.lib.get(aid)
        if m["realPerson"]:
            c = self.lib.consents.get(m["consentId"] or "")
            if not c or c["kind"] != "face" or c["usedBy"] != aid:
                raise ApiError(409, "CONSENT_REQUIRED", "Avatar người thật này không có bản ghi đồng ý hợp lệ; hãy tạo lại avatar kèm xác nhận")
        return m

    def _job(self, ctx: JobContext) -> dict:
        pid = ctx.project_id
        base = self.s.projects_dir / pid
        st = self.state(pid)
        b = st["brief"]
        meta = self._check_avatar(b["avatar"])
        W, H = CANVAS[b["aspect"]]
        out_dir = base / "exports" / "avatar"
        out_dir.mkdir(parents=True, exist_ok=True)
        work = out_dir / "_work"
        work.mkdir(exist_ok=True)

        # 1) âm thanh → đường bao biên độ
        ctx.progress("audio", 2, "Phân tích giọng nói")
        audio_asset = self.assets.get(pid, b["audio"])
        wav = work / "audio.wav"
        extract_audio(base / audio_asset["path"], wav)
        samples, sr = sf.read(str(wav), dtype="float32")
        duration = len(samples) / sr
        env = E.envelope(samples, sr, E.FPS)
        n_frames = len(env)

        # 2) nền + avatar (các mức mở miệng) → khung dựng sẵn
        ctx.progress("prepare", 6, "Chuẩn bị nền và avatar")
        img_path = self.lib.image_path(b["avatar"])
        portrait = H > W
        box_w, box_h = (int(W * 0.86), int(H * 0.58)) if portrait else (int(W * 0.72), int(H * 0.86))
        if b["aspect"] == "1:1":
            box_w, box_h = int(W * 0.8), int(H * 0.8)
        if b["frame"] == "circle":
            side = min(box_w, box_h)
            box_w = box_h = side
        aw, ah = E.fit_size(meta["width"], meta["height"], box_w, box_h)
        crop = ""
        if b["frame"] == "circle":
            # cắt vuông ở giữa theo chiều rộng/cao nhỏ hơn rồi scale: miệng phải quy đổi theo vùng cắt
            s0 = min(meta["width"], meta["height"])
            ox, oy = (meta["width"] - s0) // 2, (meta["height"] - s0) // 2
            crop = f"crop={s0}:{s0}:{ox}:{oy},"
            m = meta["mouth"]
            mouth = {"x": (m["x"] * meta["width"] - ox) / s0, "y": (m["y"] * meta["height"] - oy) / s0, "w": m["w"] * meta["width"] / s0}
            mouth["x"], mouth["y"] = float(np.clip(mouth["x"], 0.05, 0.95)), float(np.clip(mouth["y"], 0.05, 0.95))
            aw = ah = min(aw, ah)
        else:
            mouth = meta["mouth"]
        face = E.ffmpeg_rgb(["-i", str(img_path), "-vf", f"{crop}scale={aw}:{ah}"], aw, ah)
        bg = b["background"]
        if bg["kind"] == "color":
            bgimg = E.ffmpeg_rgb(["-f", "lavfi", "-i", f"color=c=0x{bg['color'][1:]}:s={W}x{H}"], W, H)
        elif bg["kind"] == "image":
            ba = self.assets.get(pid, bg["asset"])
            if ba["kind"] != "image":
                raise ApiError(400, "VALIDATION_FAILED", "Nền ảnh phải là tài nguyên dạng ảnh")
            bgimg = E.ffmpeg_rgb(["-i", str(base / ba["path"]), "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"], W, H)
        else:
            bgimg = E.ffmpeg_rgb(["-i", str(img_path), "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=40,eq=brightness=-0.18:saturation=1.1"], W, H)
        levels = E.mouth_levels(face, mouth)
        mask = E.shape_mask(aw, ah, b["frame"])
        pos = ((W - aw) // 2, int((H - ah) * (0.38 if portrait else 0.5)))
        frames = E.compose_levels(bgimg, levels, pos, mask, 5 if b["border"] and mask is not None else 0)

        # 3) phụ đề (tuỳ chọn, từ công cụ Phụ đề) + watermark AI (nếu bật)
        warnings: list[str] = []
        vf = []
        lang = b["subtitleLang"]
        if lang:
            sst = self.subs.state(pid)
            track = (sst.get("tracks") or {}).get(lang)
            if not track:
                raise ApiError(409, "TRACK_NOT_FOUND", f"Project chưa có phụ đề '{lang}' (làm ở công cụ Phụ đề & Dịch)")
            src = sst.get("source")
            if src and abs(float(src["duration"]) - duration) > 2.0:
                warnings.append(f"Phụ đề dài {src['duration']:.0f}s nhưng audio dài {duration:.0f}s — phụ đề có thể lệch.")
            (out_dir / "avatar.subs.ass").write_text(C.to_ass(track["cues"], width=W, height=H, wrap_chars=26 if portrait else 42), encoding="utf-8")
            vf.append("subtitles=avatar.subs.ass")
        wm = "Nội dung tạo bởi AI" if ai_watermark_enabled(self.s) else None
        if wm:
            (out_dir / "avatar.wm.ass").write_text(texts_to_ass([], W, H, wm, duration), encoding="utf-8")
            vf.append("subtitles=avatar.wm.ass")

        # 4) xuất khung hình → ffmpeg (đồng thời mã hoá)
        name = f"avatar_{int(time.time())}_{b['aspect'].replace(':', 'x')}.mp4"
        label = ["-metadata", "comment=AI-generated avatar video (OpenStudio AI)", "-metadata", "ai_generated=true"] if ai_label_enabled(self.s) else []
        cmd = [_exe("ffmpeg"), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(E.FPS), "-i", "-", "-i", str(wav),
               *(["-vf", ",".join(vf)] if vf else []), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
               "-shortest", "-movflags", "+faststart", *label, name]
        err_file = work / "ffmpeg.err"
        with err_file.open("wb") as ef:
            proc = subprocess.Popen(cmd, cwd=out_dir, stdin=subprocess.PIPE, stderr=ef)
        try:
            assert proc.stdin is not None
            lv = [E.level_for(float(x)) for x in env]
            last = time.time()
            for i, k in enumerate(lv):
                if ctx.cancelled():
                    raise JobCancelled()
                proc.stdin.write(frames[k])
                if time.time() - last > 1.0:
                    ctx.progress("render", 10 + 88 * i / n_frames, f"Dựng video {i}/{n_frames} khung")
                    last = time.time()
            proc.stdin.close()
            code = proc.wait()
        except BaseException:
            proc.kill()
            raise
        if code != 0:
            raise ApiError(422, "FFMPEG_FAILED", "FFmpeg lỗi: " + redact(err_file.read_text(encoding="utf-8", errors="replace")[-400:]))
        for f in ("avatar.subs.ass", "avatar.wm.ass"):
            (out_dir / f).unlink(missing_ok=True)
        shutil.rmtree(work, ignore_errors=True)
        result = {"path": f"exports/avatar/{name}", "duration": round(duration, 2), "aspect": b["aspect"], "engine": "puppet", "avatarId": b["avatar"],
                  "consentId": meta["consentId"], "frames": n_frames, "warnings": warnings}
        self.commit(pid, "_set-result", {"result": result})
        ctx.progress("done", 100, "Hoàn tất")
        return result
