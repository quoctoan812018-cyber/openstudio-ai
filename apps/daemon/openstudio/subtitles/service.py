"""Dịch vụ Phụ đề & Dịch: các job (chuẩn bị nguồn, tải link, nhận dạng giọng nói, dịch, xuất, burn-in)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from ..config import Settings
from ..errors import ApiError
from ..jobs import JobContext, JobRunner
from ..media import extract_audio, probe, run_ffmpeg
from ..models import ModelManager
from ..repo import Repo
from ..security import redact, safe_join
from ..workers.runner import run_process
from . import cues as C
from .llm import LLMClient, polish_cues, translate_cues
from .segment import words_to_cues
from .state import TOOL, reducer

MEDIA_EXT = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".opus"}
STT_PREFERENCE = {"strong": ["faster-whisper-large-v3-turbo", "faster-whisper-small", "faster-whisper-tiny"],
                  "weak": ["faster-whisper-small", "faster-whisper-tiny"]}
FORMATS = {"srt", "vtt", "ass"}


def safe_filename(name: str) -> str:
    name = Path(name).name
    stem = re.sub(r"[^\w.\- ()\[\]]+", "_", Path(name).stem, flags=re.UNICODE).strip(" ._")[:80] or "media"
    return stem + Path(name).suffix.lower()


def choose_stt_model(hw: dict, installed: set[str], requested: str | None = None) -> str | None:
    if requested:
        return requested if requested in installed else None
    strong = hw["tier"] != "cpu" or hw["ram_gb"] >= 12
    return next((m for m in STT_PREFERENCE["strong" if strong else "weak"] if m in installed), None)


def align_second(primary: list[dict], second: list[dict]) -> list[dict]:
    """Ghép bản dịch vào từng cue gốc theo thời gian (cue dịch nào có điểm giữa nằm trong cue gốc)."""
    out = []
    for p in primary:
        parts = [s["text"] for s in second if p["start"] - 0.05 <= (s["start"] + s["end"]) / 2 <= p["end"] + 0.05]
        out.append(C.make_cue(p["start"], p["end"], " ".join(parts)))
    return out


class SubtitleService:
    def __init__(self, settings: Settings, repo: Repo, runner: JobRunner, models: ModelManager,
                 llm: LLMClient, hw: dict, stt_cmd: list[str] | None = None):
        self.s, self.repo, self.runner, self.models, self.llm, self.hw = settings, repo, runner, models, llm, hw
        self.stt_cmd = stt_cmd or [sys.executable, "-m", "openstudio.workers.stt_worker"]
        repo.reducers[TOOL] = reducer
        for name in ("prepare", "fetch", "transcribe", "translate", "burn"):
            runner.register(f"subtitles.{name}", getattr(self, f"_job_{name}"))

    # ---- tiện ích ----
    def project_dir(self, pid: str) -> Path:
        d = self.s.projects_dir / pid
        d.mkdir(parents=True, exist_ok=True)
        return d

    def state(self, pid: str) -> dict:
        st = self.repo.get_state(pid, TOOL)
        return st["state"] if st["state"] else {"source": None, "tracks": {}, "glossary": [], "options": {}}

    def commit(self, pid: str, type: str, payload: dict) -> dict:
        return self.repo.apply_command(pid, TOOL, type, payload, None, author="job")

    def installed_stt(self) -> set[str]:
        return {m["id"] for m in self.models.list() if m["capability"] == "stt" and m["status"] == "installed"}

    def pick_stt(self, requested: str | None) -> str:
        mid = choose_stt_model(self.hw, self.installed_stt(), requested)
        if not mid:
            want = requested or ("faster-whisper-large-v3-turbo" if self.hw["ram_gb"] >= 12 else "faster-whisper-small")
            raise ApiError(424, "MODEL_MISSING", f"Cần tải mô hình nhận dạng giọng nói '{want}' trước", {"modelId": want})
        return mid

    def _need_source(self, pid: str) -> dict:
        src = self.state(pid).get("source")
        if not src:
            raise ApiError(409, "SOURCE_REQUIRED", "Chưa có video/audio nguồn")
        return src

    # ---- tạo job (gọi từ API) ----
    def start_prepare(self, pid: str, rel_path: str, origin: dict) -> dict:
        return self.runner.submit("subtitles.prepare", {"path": rel_path, "origin": origin}, pid, TOOL)

    def start_fetch(self, pid: str, url: str) -> dict:
        if not re.match(r"^https?://", url, re.I):
            raise ApiError(400, "VALIDATION_FAILED", "Chỉ hỗ trợ liên kết http(s)")
        return self.runner.submit("subtitles.fetch", {"url": url}, pid, TOOL)

    def start_transcribe(self, pid: str, language: str | None, model: str | None, polish: bool | None) -> dict:
        self._need_source(pid)
        mid = self.pick_stt(model)
        if polish is None:
            polish = bool(self.state(pid).get("options", {}).get("polish", True))
        return self.runner.submit("subtitles.transcribe", {"language": language, "model": mid, "polish": polish}, pid, TOOL)

    def start_translate(self, pid: str, targets: list[str], tone: str | None, market: str | None) -> dict:
        st = self.state(pid)
        if not st.get("sourceLang") or st["sourceLang"] not in st.get("tracks", {}):
            raise ApiError(409, "TRANSCRIPT_REQUIRED", "Cần có bản gốc (transcript) trước khi dịch")
        targets = [t for t in dict.fromkeys(targets) if t != st["sourceLang"]]
        if not targets:
            raise ApiError(400, "VALIDATION_FAILED", "Chọn ít nhất một ngôn ngữ đích khác ngôn ngữ gốc")
        self.llm.require()
        return self.runner.submit("subtitles.translate", {"targets": targets, "tone": tone, "market": market}, pid, TOOL)

    def start_burn(self, pid: str, params: dict) -> dict:
        self._need_source(pid)
        if params["lang"] not in self.state(pid).get("tracks", {}):
            raise ApiError(404, "TRACK_NOT_FOUND", "Không có bản phụ đề này")
        return self.runner.submit("subtitles.burn", params, pid, TOOL)

    # ---- job: chuẩn bị nguồn ----
    def _job_prepare(self, ctx: JobContext) -> dict:
        return self._prepare(ctx, ctx.params["path"], ctx.params.get("origin", {}), 0)

    def _prepare(self, ctx: JobContext, rel: str, origin: dict, base_pct: float) -> dict:
        pid = ctx.project_id
        base = self.project_dir(pid)
        src = safe_join(base, rel)
        scale = (100 - base_pct) / 100
        ctx.progress("probe", base_pct + 5 * scale, src.name)
        info = probe(src)
        ctx.check_cancel()
        ctx.progress("extract-audio", base_pct + 30 * scale, "Tách âm thanh")
        extract_audio(src, base / "work" / "audio.wav")
        self.commit(pid, "set-source", {"source": {
            "path": rel, "filename": src.name, "audio": "work/audio.wav", **info, "origin": origin}})
        ctx.progress("done", 100, "Sẵn sàng")
        return {"duration": info["duration"]}

    # ---- job: tải link bằng yt-dlp ----
    def _job_fetch(self, ctx: JobContext) -> dict:
        pid, url = ctx.project_id, ctx.params["url"]
        base = self.project_dir(pid)
        (base / "source").mkdir(exist_ok=True)
        found: list[str] = []

        def on_line(line: str) -> None:
            if line.startswith("download:"):
                try:
                    ctx.progress("download", float(line[9:].strip().rstrip("%")) * 0.8, "Đang tải")
                except ValueError:
                    pass
            elif line.startswith("FILE:"):
                found.append(line[5:])

        cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--newline", "--no-simulate", "--restrict-filenames",
               "-f", "bv*[height<=1080]+ba/b", "--merge-output-format", "mp4",
               "--progress-template", "download:%(progress._percent_str)s", "--print", "after_move:FILE:%(filepath)s",
               "-o", "source/%(title).80B-%(id)s.%(ext)s", url]
        code, tail = run_process(cmd, cwd=base, on_line=on_line, cancelled=ctx.cancelled)
        if code != 0 or not found:
            raise ApiError(422, "DOWNLOAD_FAILED", "Không tải được: " + redact(tail[-300:]))
        fp = Path(found[-1])
        rel = fp.resolve().relative_to(base.resolve()).as_posix() if fp.is_absolute() else fp.as_posix()
        return self._prepare(ctx, rel, {"type": "url", "url": url}, 80)

    # ---- job: nhận dạng giọng nói ----
    def _job_transcribe(self, ctx: JobContext) -> dict:
        pid, p = ctx.project_id, ctx.params
        base = self.project_dir(pid)
        st = self.state(pid)
        src = st["source"]
        mid = p["model"]
        gpu = self.hw["tier"] != "cpu"
        out = base / "work" / "stt.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.unlink(missing_ok=True)
        terms = [g["src"] for g in st.get("glossary", [])][:40]
        args = {
            "model_dir": str(safe_join(self.s.models_dir, f"stt/{mid}")), "audio": str(safe_join(base, src["audio"])),
            "language": p.get("language"), "device": "cuda" if gpu else "cpu",
            "compute_type": "float16" if gpu else "int8", "cpu_threads": 0, "out": str(out),
            "initial_prompt": ("Thuật ngữ: " + ", ".join(terms) + ".") if terms else None,
        }
        done: list[str] = []

        def on_line(line: str) -> None:
            try:
                m = json.loads(line)
            except ValueError:
                return
            if m.get("type") == "progress":
                ctx.progress("transcribe", m["percent"] * 0.85, "Nhận dạng giọng nói")
            elif m.get("type") == "done":
                done.append(m["result"])

        env = {**__import__("os").environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2]), "PYTHONIOENCODING": "utf-8"}
        ctx.progress("transcribe", 0, "Nạp mô hình " + mid)
        code, tail = run_process([*self.stt_cmd, json.dumps(args)], cwd=base, env=env, on_line=on_line, cancelled=ctx.cancelled)
        if code != 0 or not done:
            raise ApiError(422, "STT_FAILED", "Nhận dạng giọng nói lỗi: " + redact(tail[-400:]))
        res = json.loads(out.read_text(encoding="utf-8"))
        lang = p.get("language") or res["language"]
        opts = st.get("options", {})
        cues = words_to_cues(res["words"], max_chars=int(opts.get("maxChars", 84)))
        if not cues:
            raise ApiError(422, "NO_SPEECH", "Không phát hiện lời nói trong file")
        meta = {"model": mid, "detectedLanguage": res["language"], "polished": False, "duration": res["duration"]}
        self.commit(pid, "set-track", {"lang": lang, "kind": "transcript", "cues": cues, "meta": meta})
        warnings: list[str] = []
        if p.get("polish"):
            ctx.progress("polish", 86, "LLM sửa lỗi")
            try:
                self.llm.require()
                self.llm.stats.update(calls=0, fallbacks=0, glossary_misses=0)
                fixed = polish_cues(self.llm, cues, language=lang, glossary=st.get("glossary"),
                                    on_progress=lambda d, t: ctx.progress("polish", 86 + 13 * d / t, "LLM sửa lỗi", d, 0, t))
                self.commit(pid, "set-track", {"lang": lang, "kind": "transcript", "cues": fixed,
                                               "meta": {**meta, "polished": True, "llmModel": self.llm.model,
                                                        "fallbacks": self.llm.stats["fallbacks"]}})
            except ApiError as e:  # không có LLM thì vẫn giữ bản thô, báo cho người dùng
                warnings.append(e.message)
        ctx.progress("done", 100, "Hoàn tất")
        return {"lang": lang, "cues": len(cues), "warnings": warnings}

    # ---- job: dịch ----
    def _job_translate(self, ctx: JobContext) -> dict:
        pid, p = ctx.project_id, ctx.params
        st = self.state(pid)
        src_lang = st["sourceLang"]
        src_cues = st["tracks"][src_lang]["cues"]
        opts = st.get("options", {})
        tone, market = p.get("tone") or opts.get("tone", "neutral"), p.get("market") or opts.get("market")
        targets = p["targets"]
        summary = {}
        for i, tgt in enumerate(targets):
            ctx.check_cancel()
            self.llm.stats.update(calls=0, fallbacks=0, glossary_misses=0)
            lo, span = i / len(targets) * 100, 100 / len(targets)

            def prog(d: int, t: int, lo=lo, span=span, tgt=tgt, i=i) -> None:
                ctx.check_cancel()
                ctx.progress(f"translate:{tgt}", lo + span * d / t, f"Dịch sang {tgt}", i, 0, len(targets))

            out = translate_cues(self.llm, src_cues, source=src_lang, target=tgt, tone=tone, market=market,
                                 glossary=st.get("glossary"), on_progress=prog)
            meta = {"sourceLang": src_lang, "tone": tone, "market": market, "llmModel": self.llm.model,
                    "fallbacks": self.llm.stats["fallbacks"], "glossaryMisses": self.llm.stats["glossary_misses"]}
            self.commit(pid, "set-track", {"lang": tgt, "kind": "translation", "cues": out, "meta": meta})
            summary[tgt] = meta
        ctx.progress("done", 100, "Hoàn tất")
        return {"targets": summary}

    # ---- xuất ----
    def export(self, pid: str, lang: str, fmt: str, second: str | None = None, order: str = "primary-top",
               layout: str = "horizontal") -> dict:
        if fmt not in FORMATS:
            raise ApiError(400, "VALIDATION_FAILED", "Định dạng phải là srt, vtt hoặc ass")
        st = self.state(pid)
        tracks = st.get("tracks", {})
        if lang not in tracks or (second and second not in tracks):
            raise ApiError(404, "TRACK_NOT_FOUND", "Không có bản phụ đề này")
        primary = tracks[lang]["cues"]
        sec = align_second(primary, tracks[second]["cues"]) if second else None
        if fmt == "ass":
            w, h = (1080, 1920) if layout == "vertical" else (1920, 1080)
            body = C.to_ass(primary, sec, width=w, height=h, order=order, wrap_chars=30 if layout == "vertical" else 42)
        else:
            merged = primary
            if sec:  # SRT/VTT song ngữ: hai dòng trong cùng cue
                def two(p: dict, q: dict) -> str:
                    a, b = (p["text"], q["text"]) if order == "primary-top" else (q["text"], p["text"])
                    return f"{a}\n{b}" if q["text"] else p["text"]
                merged = [C.make_cue(p["start"], p["end"], two(p, q)) for p, q in zip(primary, sec)]
            body = (C.to_srt if fmt == "srt" else C.to_vtt)(merged, wrap=not sec)
        stem = Path(st["source"]["filename"]).stem if st.get("source") else "subtitles"
        name = f"{stem}.{lang}{'+' + second if second else ''}.{fmt}"
        out = self.project_dir(pid) / "exports" / safe_filename(name)
        out.parent.mkdir(exist_ok=True)
        out.write_text(body, encoding="utf-8-sig" if fmt == "srt" else "utf-8")
        return {"path": out.relative_to(self.project_dir(pid)).as_posix(), "bytes": out.stat().st_size}

    # ---- job: burn-in ----
    def _job_burn(self, ctx: JobContext) -> dict:
        pid, p = ctx.project_id, ctx.params
        base = self.project_dir(pid)
        st = self.state(pid)
        src = st["source"]
        layout, fit = p.get("layout", "horizontal"), p.get("fit", "pad")
        lang, second = p["lang"], p.get("second")
        tracks = st["tracks"]
        primary = tracks[lang]["cues"]
        sec = align_second(primary, tracks[second]["cues"]) if second else None
        if layout == "vertical":
            w, h = 1080, 1920
        else:
            w, h = (src["width"] or 1920) // 2 * 2, (src["height"] or 1080) // 2 * 2
        exports = base / "exports"
        exports.mkdir(exist_ok=True)
        stem = safe_filename(Path(src["filename"]).stem)
        tag = f"{lang}{'+' + second if second else ''}.{layout}"
        ass_name = f"{Path(stem).stem}.{tag}.burn.ass"
        (exports / ass_name).write_text(
            C.to_ass(primary, sec, width=w, height=h, order=p.get("order", "primary-top"),
                     font=p.get("font", "Arial"), size=p.get("size"),
                     margin_v=round(h * (0.12 if layout == "vertical" else 0.06)),
                     wrap_chars=28 if layout == "vertical" else 42), encoding="utf-8")
        if layout == "vertical":
            vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
                  if fit == "pad" else f"scale=-2:{h},crop={w}:{h}")
        else:
            vf = f"scale={w}:{h}"
        vf += f",subtitles={ass_name}"
        out_name = f"{Path(stem).stem}.{tag}.mp4"
        in_abs = str(safe_join(base, src["path"]))
        inputs = ["-i", in_abs] if src.get("hasVideo") else \
            ["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r=25", "-i", in_abs]
        maps = [] if src.get("hasVideo") else ["-map", "0:v", "-map", "1:a", "-shortest"]
        args = [*inputs, *maps, "-vf", vf, "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out_name]
        ctx.progress("burn", 0, "Ghi phụ đề vào video")
        run_ffmpeg(args, float(src["duration"]), exports, on_progress=lambda pc: ctx.progress("burn", pc, "Ghi phụ đề vào video"),
                   cancelled=ctx.cancelled)
        ctx.progress("done", 100, "Hoàn tất")
        return {"path": f"exports/{out_name}"}
