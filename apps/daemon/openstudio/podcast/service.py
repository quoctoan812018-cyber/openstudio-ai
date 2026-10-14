"""Podcast: chủ đề/tài liệu → kịch bản 2–3 người (LLM) → giọng nhiều người → nhạc mở/kết + nhạc nền ducking → loudnorm
→ MP3/WAV có chương + video sóng âm có phụ đề + show notes."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..config import Settings
from ..errors import ApiError
from ..jobs import JobContext, JobRunner
from ..media import run_ffmpeg
from ..repo import Repo
from ..subtitles import cues as C
from ..subtitles.llm import LLMClient
from ..tts import audio as A
from ..tts.service import TTSService, ai_label_enabled
from . import music as M
from . import notes as N
from .script import generate_script
from .state import TOOL, reducer

LEAD_OVERLAP = 1.2   # giọng bắt đầu khi nhạc mở còn 1.2s
OUTRO_OVERLAP = 1.0  # nhạc kết vào khi giọng còn 1s


class PodcastService:
    def __init__(self, settings: Settings, repo: Repo, runner: JobRunner, tts: TTSService, llm: LLMClient, music: M.MusicLibrary):
        self.s, self.repo, self.runner, self.tts, self.llm, self.music = settings, repo, runner, tts, llm, music
        repo.reducers[TOOL] = reducer
        runner.register("podcast.script", self._job_script)
        runner.register("podcast.produce", self._job_produce)

    def state(self, pid: str) -> dict:
        from .state import initial_state
        st = self.repo.get_state(pid, TOOL)["state"]
        return {**initial_state(), **st} if st else initial_state()

    def commit(self, pid: str, type: str, payload: dict) -> dict:
        return self.repo.apply_command(pid, TOOL, type, payload, None, author="job")

    def pdir(self, pid: str) -> Path:
        d = self.s.projects_dir / pid
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ---- tạo job ----
    def start_script(self, pid: str) -> dict:
        b = self.state(pid)["brief"]
        if not b["topic"].strip() and not b["sourceText"].strip():
            raise ApiError(409, "BRIEF_REQUIRED", "Hãy nhập chủ đề hoặc dán tài liệu nguồn")
        self.llm.require()
        return self.runner.submit("podcast.script", {}, pid, TOOL)

    def host_voices(self, st: dict) -> dict[str, str]:
        lang = st["brief"]["language"]
        return {h["name"]: h["voice"] or self.tts.default_voice(lang, i) for i, h in enumerate(st["brief"]["hosts"])}

    def start_produce(self, pid: str) -> dict:
        st = self.state(pid)
        if not st["script"]:
            raise ApiError(409, "SCRIPT_REQUIRED", "Chưa có kịch bản — hãy tạo hoặc dán kịch bản trước")
        for vid in set(self.host_voices(st).values()):
            self.tts.model_paths(self.tts.resolve_voice(vid).engine)
        for k in ("intro", "outro", "bed"):  # id nhạc phải còn tồn tại
            ch = st["music"].get(k)
            if ch and ch != M.BUILTIN and not any(m["id"] == ch for m in self.music.list()):
                raise ApiError(404, "MUSIC_NOT_FOUND", f"Bài nhạc '{ch}' không còn trong thư viện")
        return self.runner.submit("podcast.produce", {}, pid, TOOL)

    # ---- job: viết kịch bản ----
    def _job_script(self, ctx: JobContext) -> dict:
        pid = ctx.project_id
        brief = self.state(pid)["brief"]

        def prog(i: int, n: int, title: str) -> None:
            ctx.check_cancel()
            ctx.progress("script", 5 + 90 * i / n, f"Viết chương {min(i + 1, n)}/{n}: {title}" if title else "Hoàn tất", i, 0, n)

        ctx.progress("outline", 2, "Lập dàn ý")
        script = generate_script(self.llm, brief, prog)
        self.commit(pid, "_set-script", {"script": script})
        ctx.progress("done", 100, "Hoàn tất")
        return {"title": script["title"], "sections": len(script["sections"]), "turns": sum(len(s["turns"]) for s in script["sections"])}

    # ---- job: sản xuất ----
    def _job_produce(self, ctx: JobContext) -> dict:
        pid = ctx.project_id
        base = self.pdir(pid)
        st = self.state(pid)
        script, brief, mus, opts = st["script"], st["brief"], st["music"], st["options"]
        voices = self.host_voices(st)
        resolved = {name: self.tts.resolve_voice(v) for name, v in voices.items()}
        work = base / "work" / "podcast"
        work.mkdir(parents=True, exist_ok=True)

        turns = [(si, t) for si, sec in enumerate(script["sections"]) for t in sec["turns"]]
        by_engine: dict[str, list[dict]] = {}
        for i, (_, t) in enumerate(turns):
            r = resolved[t["speaker"]]
            by_engine.setdefault(r.engine, []).append({"id": f"t{i:04d}", "text": t["text"], "voice": r.voice, "ref_audio": r.ref_audio,
                                                       "speed": float(opts["speed"]) if A and r.engine == "kokoro" else 1.0, "lang": brief["language"],
                                                       "out": str(work / f"turn_{i:04d}.wav")})
        results: dict[str, dict] = {}
        errors: dict[str, str] = {}
        engines = list(by_engine)
        for k, eng in enumerate(engines):
            res = self.tts.synth_batch(ctx, eng, by_engine[eng], 90 * k / len(engines) * 0.6, 90 * (k + 1) / len(engines) * 0.6, "podcast-tts")
            errors.update(res.pop("_errors"))
            results.update(res)
        missing = [f"t{i:04d}" for i in range(len(turns)) if f"t{i:04d}" not in results]
        if missing:
            raise ApiError(422, "TTS_FAILED", f"Không đọc được {len(missing)}/{len(turns)} lượt nói: " + "; ".join(list(errors.values())[:2]))

        ctx.progress("assemble", 58, "Ghép lời thoại")
        clips: list[tuple[np.ndarray, float]] = []
        spans_meta: list[dict] = []
        prev_speaker = None
        for i, (si, t) in enumerate(turns):
            r = resolved[t["speaker"]]
            path = Path(results[f"t{i:04d}"]["out"])
            if r.engine != "kokoro" and abs(float(opts["speed"]) - 1.0) > 0.01:
                tmp = path.with_suffix(".t.wav")
                A.change_tempo(path, tmp, float(opts["speed"]))
                path = tmp
            data = A.fade(A.trim_silence(A.read_mono(path), A.MIX_SR), A.MIX_SR)
            gap = float(opts["gap"]) + (0.12 if prev_speaker not in (None, t["speaker"]) else 0.0)
            clips.append((data, gap))
            spans_meta.append({"section": si, "speaker": t["speaker"], "text": t["text"]})
            prev_speaker = t["speaker"]
        # khoảng nghỉ dài hơn giữa các chương
        for i in range(len(clips) - 1):
            if spans_meta[i]["section"] != spans_meta[i + 1]["section"]:
                clips[i] = (clips[i][0], max(clips[i][1], 0.9))
        speech, spans = A.concat_with_gaps(clips)
        speech_dur = len(speech) / A.MIX_SR

        # ---- dòng thời gian có nhạc ----
        intro = self.music.resolve(mus.get("intro"), "intro")
        outro = self.music.resolve(mus.get("outro"), "outro")
        lead = max(0.0, len(intro) / A.MIX_SR - LEAD_OVERLAP) if intro is not None else 0.4
        speech_end = lead + speech_dur
        outro_start = speech_end - OUTRO_OVERLAP if outro is not None else speech_end
        total = outro_start + len(outro) / A.MIX_SR if outro is not None else speech_end + 0.8
        n = int(total * A.MIX_SR) + 1
        voice = np.zeros(n, dtype=np.float32)
        s0 = int(lead * A.MIX_SR)
        voice[s0: s0 + len(speech)] = speech
        mix = voice.copy()
        bed = self.music.resolve(mus.get("bed"), "bed", total)
        if bed is not None:
            bed = M.fade_io(M.loop_to(bed, total), 2.0, 3.0)[:n]
            gain = 10 ** (float(mus["bedGain"]) / 20)
            duck = M.duck_envelope(voice, depth_db=-12.0)
            bed_layer = np.zeros(n, dtype=np.float32)
            bed_layer[: len(bed)] = bed * gain * duck[: len(bed)]
            mix += bed_layer
        if intro is not None:
            mix[: len(intro)] += M.fade_io(intro, 0.0, 1.5)[: n]
        if outro is not None:
            o0 = int(outro_start * A.MIX_SR)
            piece = M.fade_io(outro, 0.5, 2.0)
            mix[o0: o0 + len(piece)] += piece[: n - o0]
        mix_wav = work / "mix.wav"
        A.write_wav(mix_wav, mix)
        ctx.progress("export", 66, "Chuẩn hoá và xuất file")

        # ---- chương ----
        chapters = []
        first_turn: dict[int, float] = {}
        for (a, _b), meta in zip(spans, spans_meta):
            first_turn.setdefault(meta["section"], a)
        for si, sec in enumerate(script["sections"]):
            chapters.append({"title": sec["title"], "start": 0.0 if si == 0 else round(max(0.0, lead + first_turn[si] - 0.3), 2)})
        title = script.get("title") or "Podcast"
        slug = N.slugify(title)
        out_dir = base / "exports" / "podcast"
        out_dir.mkdir(parents=True, exist_ok=True)
        fmt = opts["format"]
        audio_out = out_dir / f"{slug}.{fmt}"
        label = ai_label_enabled(self.s)
        meta = work / "chapters.ffmeta"
        meta.write_text(N.ffmetadata(chapters, total, title, "AI-generated podcast (OpenStudio AI)" if label else None), encoding="utf-8")
        codec = ["-c:a", "libmp3lame", "-b:a", "192k", "-id3v2_version", "3"] if fmt == "mp3" else ["-c:a", "pcm_s16le"]
        run_ffmpeg(["-i", str(mix_wav), "-i", str(meta), "-map_metadata", "1", "-map_chapters", "1", "-map", "0:a",
                    "-af", f"loudnorm=I=-16:TP=-1.5:LRA=11,atrim=0:{total:.3f}", "-ar", "48000", "-ac", "2", *codec, str(audio_out)],
                   total, base, on_progress=lambda p: ctx.progress("export", 66 + 10 * p / 100, "Chuẩn hoá và xuất file"), cancelled=ctx.cancelled)

        # ---- video sóng âm + phụ đề ----
        video_out = None
        if opts["video"]:
            vertical = opts["layout"] == "vertical"
            w, h = (1080, 1920) if vertical else (1280, 720)
            cues = [C.make_cue(lead + a, lead + b, f"{m['speaker']}: {m['text']}") for (a, b), m in zip(spans, spans_meta)]
            ass_name = f"{slug}.ass"
            (out_dir / ass_name).write_text(C.to_ass(
                cues, width=w, height=h, wrap_chars=26 if vertical else 40, margin_v=round(h * (0.12 if vertical else 0.07)),
                size=round(h * (0.036 if vertical else 0.048)), hook=title, hook_seconds=total), encoding="utf-8")
            wh = round(h * 0.22)
            y = round(h * (0.34 if vertical else 0.36))
            video_out = out_dir / f"{slug}.{opts['layout']}.mp4"
            graph = (f"[1:a]aformat=channel_layouts=mono,showwaves=s={w}x{wh}:mode=cline:colors=0x60a5fa:rate=25:scale=sqrt,format=rgba[w];"
                     f"[0:v][w]overlay=0:{y}:format=auto,format=yuv420p,subtitles={ass_name}[v]")
            run_ffmpeg(["-f", "lavfi", "-i", f"color=c=0x0f172a:s={w}x{h}:r=25", "-i", str(audio_out), "-filter_complex", graph, "-map", "[v]",
                        "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                        "-shortest", "-movflags", "+faststart", video_out.name], total, out_dir,
                       on_progress=lambda p: ctx.progress("video", 78 + 18 * p / 100, "Dựng video sóng âm"), cancelled=ctx.cancelled)

        # ---- show notes + chương ----
        notes_path = out_dir / f"{slug}.md"
        notes_path.write_text(N.show_notes(script, chapters, total, [h["name"] for h in brief["hosts"]], brief.get("sourceName")), encoding="utf-8")
        chapters_path = out_dir / f"{slug}.chapters.txt"
        chapters_path.write_text(N.chapters_txt(chapters), encoding="utf-8")
        rel = lambda p: p.relative_to(base).as_posix()
        result = {"audio": rel(audio_out), "video": rel(video_out) if video_out else None, "notes": rel(notes_path), "chapters": rel(chapters_path),
                  "duration": round(total, 2), "chapterList": chapters, "lead": round(lead, 2), "turns": len(turns),
                  "music": {k: mus.get(k) for k in ("intro", "outro", "bed")},
                  "timeline": [{**m, "start": round(lead + a, 2), "end": round(lead + b, 2)} for (a, b), m in zip(spans, spans_meta)]}
        self.commit(pid, "_set-result", {"result": result})
        ctx.progress("done", 100, "Hoàn tất")
        return result
