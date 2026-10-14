"""Lồng tiếng video: kế hoạch (gộp câu) → TTS từng câu → khớp thời lượng (tăng tốc / LLM rút gọn) → tách nhạc nền
(Demucs) → trộn có ducking + chuẩn hoá âm lượng → ghép vào video, kèm phụ đề khớp với giọng."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ..config import Settings
from ..errors import ApiError
from ..jobs import JobContext, JobRunner
from ..media import run_ffmpeg
from ..models import ModelManager
from ..repo import Repo
from ..security import redact, safe_join
from ..subtitles import cues as C
from ..subtitles.llm import LLMClient, shorten_lines
from ..subtitles.service import SubtitleService, safe_filename
from ..tts import audio as A
from ..tts.engines import engine_for
from ..tts.service import TTSService, ai_label_enabled
from ..workers.runner import run_process
from . import plan as P
from .state import TOOL, reducer

SEP_MODEL = "demucs-htdemucs"
MAX_PASSES = 3


class DubbingService:
    def __init__(self, settings: Settings, repo: Repo, runner: JobRunner, models: ModelManager, subs: SubtitleService,
                 tts: TTSService, llm: LLMClient, sep_engine: str = "demucs"):
        self.s, self.repo, self.runner, self.models, self.subs, self.tts, self.llm = settings, repo, runner, models, subs, tts, llm
        self.sep_engine = sep_engine
        repo.reducers[TOOL] = reducer
        runner.register("dubbing.synthesize", self._job_synthesize)
        runner.register("dubbing.mix", self._job_mix)

    # ---- tiện ích ----
    def state(self, pid: str) -> dict:
        st = self.repo.get_state(pid, TOOL)["state"]
        return st or {"options": {}, "plan": None, "result": None}

    def opts(self, pid: str) -> dict:
        from .state import DEFAULTS
        return {**DEFAULTS, **self.state(pid).get("options", {})}

    def commit(self, pid: str, type: str, payload: dict) -> dict:
        return self.repo.apply_command(pid, TOOL, type, payload, None, author="job")

    def pdir(self, pid: str) -> Path:
        d = self.s.projects_dir / pid
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _installed(self, model_id: str) -> bool:
        return any(m["id"] == model_id and m["status"] == "installed" for m in self.models.list())

    # ---- kế hoạch (nhanh, đồng bộ) ----
    def build_plan(self, pid: str) -> dict:
        sub = self.subs.state(pid)
        o = self.opts(pid)
        target = o["targetLang"]
        if not sub.get("source"):
            raise ApiError(409, "SOURCE_REQUIRED", "Chưa có video/audio nguồn (làm ở công cụ Phụ đề & Dịch trước)")
        if not target or target not in sub.get("tracks", {}):
            raise ApiError(409, "TRACK_REQUIRED", "Chọn ngôn ngữ lồng tiếng đã có bản dịch trong công cụ Phụ đề & Dịch")
        if target == sub.get("sourceLang"):
            raise ApiError(400, "VALIDATION_FAILED", "Ngôn ngữ lồng tiếng phải khác ngôn ngữ gốc")
        if sub["tracks"][target].get("stale"):
            raise ApiError(409, "TRACK_STALE", "Bản dịch đã cũ so với bản gốc — hãy dịch lại trước khi lồng tiếng")
        if not o.get("voice") and not engine_for(target):
            raise ApiError(400, "UNSUPPORTED_LANGUAGE", f"Chưa có engine đọc cho ngôn ngữ '{target}'")
        src_cues = sub["tracks"][sub["sourceLang"]]["cues"] if sub.get("sourceLang") in sub["tracks"] else None
        items = P.build_items(sub["tracks"][target]["cues"], src_cues, total=float(sub["source"]["duration"]),
                              min_gap=float(o["minGap"]))
        plan = {"targetLang": target, "sourceLang": sub.get("sourceLang"), "fromRevision": sub.get("revisionId"), "items": items}
        return self.commit(pid, "_set-plan", {"plan": plan})

    # ---- tạo job ----
    def _voice_for(self, item: dict, o: dict, lang: str) -> str:
        return item.get("voice") or o.get("voice") or self.tts.default_voice(lang, 0)

    def start_synthesize(self, pid: str) -> dict:
        st, o = self.state(pid), self.opts(pid)
        plan = st.get("plan")
        if not plan:
            raise ApiError(409, "PLAN_REQUIRED", "Hãy tạo kế hoạch lồng tiếng trước")
        for eng in {self.tts.resolve_voice(self._voice_for(it, o, plan["targetLang"])).engine for it in plan["items"]}:
            self.tts.model_paths(eng)
        return self.runner.submit("dubbing.synthesize", {}, pid, TOOL)

    def start_mix(self, pid: str) -> dict:
        st, o = self.state(pid), self.opts(pid)
        plan = st.get("plan")
        if not plan or not any(it.get("audio") for it in plan["items"]):
            raise ApiError(409, "SYNTH_REQUIRED", "Hãy tổng hợp giọng nói trước khi trộn")
        if o["keepBackground"] and self.sep_engine != "fake" and not self._installed(SEP_MODEL):
            raise ApiError(424, "MODEL_MISSING", "Cần tải mô hình tách nhạc nền 'demucs-htdemucs' (hoặc tắt giữ nhạc nền)", {"modelId": SEP_MODEL})
        return self.runner.submit("dubbing.mix", {}, pid, TOOL)

    # ---- job: tổng hợp + khớp thời lượng ----
    def _job_synthesize(self, ctx: JobContext) -> dict:
        pid = ctx.project_id
        base = self.pdir(pid)
        st, o = self.state(pid), self.opts(pid)
        plan = st["plan"]
        lang, items = plan["targetLang"], plan["items"]
        work = base / "work" / "dub"
        work.mkdir(parents=True, exist_ok=True)
        max_speed = float(o["maxSpeed"])
        glossary = self.subs.state(pid).get("glossary")
        llm_ok = True
        try:
            self.llm.require()
        except ApiError:
            llm_ok = False
        notes: list[str] = []

        def pending() -> list[dict]:
            return [it for it in items if it["status"] in ("pending", "retry")]

        total_passes = MAX_PASSES
        fresh: set[str] = set()
        for n in range(total_passes):
            todo = pending()
            if not todo:
                break
            lo, hi = 95 * n / total_passes, 95 * (n + 1) / total_passes
            by_engine: dict[str, list[dict]] = {}
            for it in todo:
                r = self.tts.resolve_voice(self._voice_for(it, o, lang))
                by_engine.setdefault(r.engine, []).append({
                    "id": it["id"], "text": it["text"], "voice": r.voice, "ref_audio": r.ref_audio, "speed": 1.0, "lang": lang,
                    "out": str(work / f"raw_{it['id']}.wav")})
            results: dict[str, dict] = {}
            errors: dict[str, str] = {}
            engines = list(by_engine)
            for k, eng in enumerate(engines):
                a, b = lo + (hi - lo) * k / len(engines) * 0.9, lo + (hi - lo) * (k + 1) / len(engines) * 0.9
                res = self.tts.synth_batch(ctx, eng, by_engine[eng], a, b, "dub-tts")
                errors.update(res.pop("_errors"))
                results.update(res)
            too_long: list[dict] = []
            for it in todo:
                if it["id"] not in results:
                    it.update(status="failed", note=errors.get(it["id"], "Không tổng hợp được"))
                    continue
                data = A.trim_silence(A.read_mono(Path(results[it["id"]]["out"])), A.MIX_SR)
                trimmed = work / f"trim_{it['id']}.wav"
                A.write_wav(trimmed, data)
                dur = len(data) / A.MIX_SR
                tempo, status = P.fit_decision(dur, it["slot"], max_speed)
                fresh.add(it["id"])
                it.update(duration=round(dur, 3), speed=tempo, status=status, audio=str(trimmed.relative_to(base).as_posix()), note=None)
                if status == "too_long":
                    too_long.append(it)
            if too_long and llm_ok and n < total_passes - 1:
                ctx.progress("dub-shorten", hi * 0.97, f"LLM rút gọn {len(too_long)} câu", 0, 0, len(too_long))
                lines = [{"text": it["text"], "max_chars": P.target_chars(it["text"], it["duration"], it["slot"], max_speed)} for it in too_long]
                try:
                    new = shorten_lines(self.llm, lines, language=lang, glossary=glossary)
                except Exception as e:  # noqa: BLE001 — LLM lỗi thì tăng tốc tối đa thay vì dừng cả job
                    notes.append("LLM rút gọn lỗi: " + redact(str(e))[:120])
                    new = [it["text"] for it in too_long]
                for it, text in zip(too_long, new):
                    if text != it["text"]:
                        it.update(text=text, status="retry", shortened=True)
        # câu còn "too_long" sau các lượt: tăng tốc tới trần cứng, đánh dấu để người dùng biết
        for it in items:
            if it["status"] in ("too_long", "retry"):
                it["status"] = "too_long"
                it["note"] = "Vẫn dài hơn khung thời gian; đã tăng tốc tối đa"
        ctx.progress("dub-speed", 96, "Áp dụng tốc độ")
        for it in items:
            if it["id"] not in fresh or it["status"] == "failed":
                continue  # câu cũ đã có bản đã áp tốc độ từ lần trước
            src = base / it["audio"]
            final = work / f"final_{it['id']}.wav"
            A.change_tempo(src, final, it["speed"])
            it["finalDuration"] = round(A.duration_of(final), 3)
            it["final"] = final.relative_to(base).as_posix()
        # `audio` trỏ tới bản đã áp tốc độ để bước trộn dùng
        for it in items:
            if it.get("final"):
                it["audio"] = it.pop("final")
        self.commit(pid, "_set-plan", {"plan": plan})
        stats = self.stats(items)
        ctx.progress("done", 100, "Hoàn tất")
        return {"stats": stats, "notes": notes, "llm": llm_ok}

    @staticmethod
    def stats(items: list[dict]) -> dict:
        out = {"total": len(items)}
        for k in ("ok", "sped", "too_long", "failed", "pending"):
            out[k] = sum(1 for it in items if it["status"] == k)
        out["shortened"] = sum(1 for it in items if it.get("shortened"))
        return out

    # ---- nhạc nền ----
    def _background(self, ctx: JobContext, src: Path, work: Path) -> Path:
        sep = work / "sep"
        meta = sep / "source.json"
        sig = {"path": str(src), "size": src.stat().st_size, "mtime": int(src.stat().st_mtime), "engine": self.sep_engine}
        if (sep / "no_vocals.wav").is_file() and meta.is_file() and json.loads(meta.read_text()) == sig:
            ctx.progress("dub-separate", 55, "Dùng lại nhạc nền đã tách")
            return sep / "no_vocals.wav"
        sep.mkdir(parents=True, exist_ok=True)
        orig = work / "orig44.wav"
        r = subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "2", "-ar", "44100",
                            "-c:a", "pcm_s16le", str(orig)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise ApiError(422, "AUDIO_EXTRACT_FAILED", redact(r.stderr[-300:]))
        args = {"engine": self.sep_engine, "model_dir": str(self.s.models_dir / "separation/htdemucs"), "audio": str(orig), "out_dir": str(sep)}
        done: list[str] = []

        def on_line(line: str) -> None:
            try:
                m = json.loads(line)
            except ValueError:
                return
            if m.get("type") == "progress":
                ctx.progress("dub-separate", 5 + 50 * m["percent"] / 100, "Tách giọng/nhạc nền (Demucs)")
            elif m.get("type") == "done":
                done.append(m["no_vocals"])

        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2]), "PYTHONIOENCODING": "utf-8"}
        code, tail = run_process([sys.executable, "-m", "openstudio.workers.separate_worker", json.dumps(args)], env=env,
                                 on_line=on_line, cancelled=ctx.cancelled)
        if code != 0 or not done:
            raise ApiError(422, "SEPARATION_FAILED", "Tách nhạc nền lỗi: " + redact(tail[-400:]))
        meta.write_text(json.dumps(sig), encoding="utf-8")
        orig.unlink(missing_ok=True)
        return sep / "no_vocals.wav"

    # ---- job: trộn + ghép video ----
    def _job_mix(self, ctx: JobContext) -> dict:
        pid = ctx.project_id
        base = self.pdir(pid)
        st, o = self.state(pid), self.opts(pid)
        plan = st["plan"]
        sub = self.subs.state(pid)
        src = sub["source"]
        src_path = safe_join(base, src["path"])
        duration = float(src["duration"])
        work = base / "work" / "dub"
        work.mkdir(parents=True, exist_ok=True)
        exports = base / "exports"
        exports.mkdir(exist_ok=True)
        lang = plan["targetLang"]
        stem = Path(safe_filename(Path(src["filename"]).stem)).stem
        ai = ai_label_enabled(self.s)

        bg = self._background(ctx, src_path, work) if o["keepBackground"] else None
        ctx.progress("dub-voice", 58, "Đặt giọng lên dòng thời gian")
        places = P.compute_starts(plan["items"], float(o["minGap"]))
        clips = []
        for it, pl in zip(plan["items"], places):
            if pl["skipped"]:
                continue
            clips.append((A.fade(A.read_mono(base / it["audio"]), A.MIX_SR, 20), pl["start"]))
        voice = A.place_on_timeline(clips, duration)
        voice = voice[: int(duration * A.MIX_SR)]
        voice_wav = work / "voice.wav"
        A.write_wav(voice_wav, voice)

        fmt = o["format"]
        audio_out = exports / f"{stem}.{lang}.dub.{fmt}"
        label = ["-metadata", "comment=AI-generated dubbing (OpenStudio AI)", "-metadata", "ai_generated=true"] if ai else []
        codec = ["-c:a", "libmp3lame", "-b:a", "192k"] if fmt == "mp3" else ["-c:a", "pcm_s16le"]
        tail = f"loudnorm=I=-16:TP=-1.5:LRA=11,atrim=0:{duration:.3f},asetpts=N/SR/TB[out]"
        if bg:
            gain = float(o["backgroundGain"])
            graph = ("[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[v1][v2];"
                     f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={gain}dB[bg];"
                     "[bg][v1]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300[bgd];"
                     "[bgd][v2]amix=inputs=2:normalize=0:duration=longest[m];[m]" + tail)
            inputs = ["-i", str(voice_wav), "-i", str(bg)]
        else:
            graph = "[0:a]aformat=sample_rates=48000:channel_layouts=stereo," + tail.replace("[out]", "[out]")
            inputs = ["-i", str(voice_wav)]
        ctx.progress("dub-mix", 62, "Trộn và chuẩn hoá âm lượng")
        run_ffmpeg([*inputs, "-filter_complex", graph, "-map", "[out]", "-ar", "48000", *codec, *label, str(audio_out)], duration, base,
                   on_progress=lambda p: ctx.progress("dub-mix", 62 + 18 * p / 100, "Trộn và chuẩn hoá âm lượng"), cancelled=ctx.cancelled)

        video_out = None
        if src.get("hasVideo"):
            video_out = exports / f"{stem}.{lang}.dub.mp4"
            ctx.progress("dub-mux", 82, "Ghép tiếng vào video")
            run_ffmpeg(["-i", str(src_path), "-i", str(audio_out), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
                        "-b:a", "192k", "-movflags", "+faststart", *label, str(video_out)], duration, base,
                       on_progress=lambda p: ctx.progress("dub-mux", 82 + 16 * p / 100, "Ghép tiếng vào video"), cancelled=ctx.cancelled)

        cues = [C.make_cue(pl["start"], pl["end"], it["text"]) for it, pl in zip(plan["items"], places) if not pl["skipped"]]
        srt = exports / f"{stem}.{lang}.dub.srt"
        srt.write_text(C.to_srt(C.normalize(cues)), encoding="utf-8-sig")
        stats = self.stats(plan["items"])
        stats["pushed"] = sum(1 for pl in places if pl["pushed"] > 0)
        result = {"audio": f"exports/{audio_out.name}", "video": f"exports/{video_out.name}" if video_out else None,
                  "subtitles": f"exports/{srt.name}", "stats": stats, "background": bool(bg), "duration": duration}
        self.commit(pid, "_set-result", {"result": result})
        ctx.progress("done", 100, "Hoàn tất")
        return result
