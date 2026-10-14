"""Tóm tắt & Highlight: chọn đoạn hay (heuristic + LLM + đổi cảnh) → duyệt → xuất clip 9:16 có phụ đề/tiêu đề;
tuỳ chọn video tóm tắt có giọng đọc thuật lại."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..config import Settings
from ..errors import ApiError
from ..jobs import JobContext, JobRunner
from ..media import run_ffmpeg
from ..repo import Repo
from ..security import redact, safe_join
from ..subtitles import cues as C
from ..subtitles.llm import LLMClient, lang_name, strip_foreign_script
from ..subtitles.service import SubtitleService, safe_filename
from ..tts import audio as A
from ..tts.service import TTSService, ai_label_enabled
from ..workers.runner import run_process
from . import windows as W
from .state import DEFAULTS, TOOL, reducer

LLM_MAX_WINDOWS = 20
LLM_BATCH = 3

SCORE_SCHEMA = {
    "type": "object",
    "properties": {"windows": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "integer"}, "score": {"type": "number"}, "title": {"type": "string"}, "hook": {"type": "string"},
        "reason": {"type": "string"}}, "required": ["id", "score", "title", "hook", "reason"]}}},
    "required": ["windows"],
}
NARRATION_SCHEMA = {"type": "object", "properties": {"narration": {"type": "string"}}, "required": ["narration"]}


def excerpt(text: str, n: int = 700) -> str:
    return text if len(text) <= n else text[: n * 2 // 3] + " … " + text[-n // 3:]


def first_words(text: str, n: int) -> str:
    return " ".join(text.split()[:n]).strip(" ,;:-")


class HighlightsService:
    def __init__(self, settings: Settings, repo: Repo, runner: JobRunner, subs: SubtitleService, tts: TTSService, llm: LLMClient):
        self.s, self.repo, self.runner, self.subs, self.tts, self.llm = settings, repo, runner, subs, tts, llm
        repo.reducers[TOOL] = reducer
        runner.register("highlights.analyze", self._job_analyze)
        runner.register("highlights.export", self._job_export)
        runner.register("highlights.summary", self._job_summary)

    # ---- tiện ích ----
    def state(self, pid: str) -> dict:
        st = self.repo.get_state(pid, TOOL)["state"]
        return st or {"options": {}, "analysis": None, "clips": [], "results": {}, "summary": None}

    def opts(self, pid: str) -> dict:
        return {**DEFAULTS, **self.state(pid).get("options", {})}

    def commit(self, pid: str, type: str, payload: dict) -> dict:
        return self.repo.apply_command(pid, TOOL, type, payload, None, author="job")

    def pdir(self, pid: str) -> Path:
        d = self.s.projects_dir / pid
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _need_transcript(self, pid: str) -> tuple[dict, str, list[dict]]:
        st = self.subs.state(pid)
        if not st.get("source"):
            raise ApiError(409, "SOURCE_REQUIRED", "Chưa có video nguồn (làm ở công cụ Phụ đề & Dịch trước)")
        lang = st.get("sourceLang")
        if not lang or lang not in st.get("tracks", {}):
            raise ApiError(409, "TRANSCRIPT_REQUIRED", "Cần có transcript — hãy chạy bước nhận dạng giọng nói ở công cụ Phụ đề & Dịch")
        return st, lang, st["tracks"][lang]["cues"]

    # ---- tạo job ----
    def start_analyze(self, pid: str) -> dict:
        st, _, cues = self._need_transcript(pid)
        o = self.opts(pid)
        if not W.build_windows(cues, min_len=float(o["minLen"]), max_len=float(o["maxLen"]), duration=float(st["source"]["duration"])):
            raise ApiError(422, "TOO_SHORT", "Nguồn quá ngắn hoặc transcript quá ít so với độ dài clip yêu cầu — giảm minLen/maxLen")
        return self.runner.submit("highlights.analyze", {}, pid, TOOL)

    def start_export(self, pid: str, ids: list[str] | None) -> dict:
        st, _, _ = self._need_transcript(pid)
        chosen = [c for c in self.state(pid)["clips"] if c.get("selected") and (not ids or c["id"] in ids)]
        if not chosen:
            raise ApiError(409, "NO_CLIPS", "Chưa có clip nào được chọn")
        return self.runner.submit("highlights.export", {"ids": ids}, pid, TOOL)

    def start_summary(self, pid: str) -> dict:
        st, _, _ = self._need_transcript(pid)
        if not st["source"].get("hasVideo"):
            raise ApiError(409, "VIDEO_REQUIRED", "Video tóm tắt cần nguồn có hình")
        if not any(c.get("selected") for c in self.state(pid)["clips"]):
            raise ApiError(409, "NO_CLIPS", "Chưa có clip nào được chọn")
        o = self.opts(pid)
        lang = o["narrationLang"] or st["sourceLang"]
        self.tts.model_paths(self.tts.resolve_voice(o["voice"] or self.tts.default_voice(lang, 0)).engine)
        return self.runner.submit("highlights.summary", {}, pid, TOOL)

    # ---- phân cảnh bằng ffmpeg ----
    def detect_scenes(self, ctx: JobContext, src: Path, threshold: float = 0.3) -> list[float]:
        ff = shutil.which("ffmpeg")
        if not ff:
            raise ApiError(424, "TOOL_MISSING", "Không tìm thấy ffmpeg")
        times: list[float] = []

        def on_line(line: str) -> None:
            m = re.search(r"pts_time:([0-9.]+)", line)
            if m:
                times.append(float(m.group(1)))

        cmd = [ff, "-v", "error", "-i", str(src), "-an", "-vf", f"scale=320:-2,select='gt(scene,{threshold})',metadata=print:file=-", "-f", "null", "-"]
        code, tail = run_process(cmd, on_line=on_line, cancelled=ctx.cancelled)
        if code != 0:
            raise ApiError(422, "SCENE_DETECT_FAILED", "Phân cảnh lỗi: " + redact(tail[-300:]))
        return sorted(set(round(t, 2) for t in times))

    # ---- LLM chấm điểm ----
    def llm_scores(self, ctx: JobContext, wins: list[dict], lang: str) -> dict[int, dict]:
        system = (
            "You are a short-video editor choosing the best clips from a long video's transcript for TikTok, YouTube Shorts and Reels. "
            "For each candidate window, rate from 0 to 10 how good it is as a STANDALONE short clip: a strong hook in the first sentence, "
            "one clear idea, something surprising, useful or emotional, and a satisfying ending. Give low scores to greetings, intros, "
            "outros, sponsor reads and filler. Write a catchy title (max 60 characters) and a hook line (max 90 characters) in the SAME "
            f"language as the transcript ({lang_name(lang)}). Keep `reason` under 15 words. "
            'Reply with ONLY JSON {"windows":[{"id":<id>,"score":<0-10>,"title":"...","hook":"...","reason":"..."}]}, one object per input window.'
        )
        out: dict[int, dict] = {}
        for k in range(0, len(wins), LLM_BATCH):
            ctx.check_cancel()
            part = wins[k: k + LLM_BATCH]
            user = "Candidate windows:\n" + "\n".join(
                f'- id={w["id"]} ({w["end"] - w["start"]:.0f}s): {excerpt(w["text"])}' for w in part)
            res = self.llm.json_object(system, user, SCORE_SCHEMA, max_tokens=700)
            for item in (res or {}).get("windows", []):
                try:
                    wid = int(item["id"])
                    if any(w["id"] == wid for w in part):
                        out[wid] = {"score": max(0.0, min(10.0, float(item["score"]))), "title": str(item["title"]).strip()[:80],
                                    "hook": str(item["hook"]).strip()[:120], "reason": str(item["reason"]).strip()[:200]}
                except (KeyError, TypeError, ValueError):
                    continue
            ctx.progress("score", 22 + 70 * min(k + LLM_BATCH, len(wins)) / len(wins), "LLM chấm điểm đoạn", min(k + LLM_BATCH, len(wins)), 0, len(wins))
        return out

    # ---- job: phân tích ----
    def _job_analyze(self, ctx: JobContext) -> dict:
        pid = ctx.project_id
        base = self.pdir(pid)
        st, lang, cues = self._need_transcript(pid)
        src = st["source"]
        o = self.opts(pid)
        scenes: list[float] = []
        if src.get("hasVideo"):
            ctx.progress("scenes", 3, "Phát hiện đổi cảnh")
            scenes = self.detect_scenes(ctx, safe_join(base, src["path"]))
        ctx.progress("windows", 20, "Dựng đoạn ứng viên")
        wins = W.build_windows(cues, min_len=float(o["minLen"]), max_len=float(o["maxLen"]), scenes=scenes, duration=float(src["duration"]))
        if not wins:
            raise ApiError(422, "TOO_SHORT", "Không dựng được đoạn ứng viên nào")
        for w in wins:
            w["heuristic"] = W.heuristic_score(w["text"], w["end"] - w["start"])
        llm_ok = False
        scored: dict[int, dict] = {}
        if o["useLlm"]:
            try:
                self.llm.require()
                llm_ok = True
            except ApiError:
                llm_ok = False
        if llm_ok:
            top = sorted(wins, key=lambda w: -w["heuristic"])[:LLM_MAX_WINDOWS]
            scored = self.llm_scores(ctx, sorted(top, key=lambda w: w["start"]), lang)
        for w in wins:
            llm = scored.get(w["id"])
            w["llm"] = llm["score"] if llm else None
            w["score"] = round(0.7 * llm["score"] + 0.3 * w["heuristic"], 2) if llm else w["heuristic"]
            w["title"] = (llm or {}).get("title") or first_words(w["text"], 8)
            w["hook"] = (llm or {}).get("hook") or first_words(w["text"], 14)
            w["reason"] = (llm or {}).get("reason") or "Điểm heuristic (không có LLM chấm)"
        # khi có LLM: chỉ những đoạn đã được LLM chấm mới đủ tư cách (tránh đoạn chưa chấm điểm "thắng" nhờ heuristic cao hơn)
        pool = [w for w in wins if w["llm"] is not None] if scored else wins
        picked = W.select_clips(pool, int(o["count"]))
        if len(picked) < int(o["count"]):  # đoạn đã được LLM chấm không đủ chỗ → bù bằng đoạn chưa chấm (điểm heuristic), tránh trùng đoạn đã chọn
            picked = W.select_clips([w for w in wins if w not in pool], int(o["count"]), chosen=picked)
        clips = [{"id": f"c{i + 1:03d}", "start": w["start"], "end": w["end"], "title": w["title"], "hook": w["hook"], "score": w["score"],
                  "heuristic": w["heuristic"], "llm": w["llm"], "reason": w["reason"], "selected": True, "manual": False,
                  "text": excerpt(w["text"], 320)} for i, w in enumerate(picked)]
        analysis = {"windows": len(wins), "scored": len(scored), "llm": bool(scored), "scenes": len(scenes), "lang": lang,
                    "fromRevision": st.get("revisionId")}
        self.commit(pid, "_set-analysis", {"analysis": analysis, "clips": clips})
        ctx.progress("done", 100, "Hoàn tất")
        return {"clips": len(clips), **analysis}

    # ---- dựng khung hình ----
    @staticmethod
    def frame(layout: str, fit: str, src: dict) -> tuple[int, int, str]:
        if layout == "vertical":
            w, h = 1080, 1920
            vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
                  if fit == "pad" else f"scale=-2:{h},crop={w}:{h}")
        else:
            w, h = (src.get("width") or 1920) // 2 * 2, (src.get("height") or 1080) // 2 * 2
            vf = f"scale={w}:{h}"
        return w, h, vf

    def track_cues(self, st: dict, lang: str | None) -> list[dict]:
        tracks = st["tracks"]
        return tracks[lang]["cues"] if lang in tracks else tracks[st["sourceLang"]]["cues"]

    # ---- job: xuất clip ----
    def _job_export(self, ctx: JobContext) -> dict:
        pid = ctx.project_id
        base = self.pdir(pid)
        st, _, _ = self._need_transcript(pid)
        hs, o = self.state(pid), self.opts(pid)
        src = st["source"]
        ids = ctx.params.get("ids")
        clips = [c for c in hs["clips"] if c.get("selected") and (not ids or c["id"] in ids)]
        cues = self.track_cues(st, o["subtitleLang"])
        out_dir = base / "exports" / "clips"
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(safe_filename(Path(src["filename"]).stem)).stem
        w, h, vf = self.frame(o["layout"], o["fit"], src)
        vertical = o["layout"] == "vertical"
        label = ["-metadata", "comment=AI-assisted clip (OpenStudio AI)"] if ai_label_enabled(self.s) else []
        done: list[str] = []
        for i, c in enumerate(clips):
            ctx.check_cancel()
            dur = c["end"] - c["start"]
            ass_name = f"{stem}.{c['id']}.ass"
            (out_dir / ass_name).write_text(C.to_ass(
                W.clip_cues(cues, c["start"], c["end"]), width=w, height=h, margin_v=round(h * (0.12 if vertical else 0.06)),
                wrap_chars=28 if vertical else 42, hook=(c.get("hook") or c.get("title")) if o["hookOverlay"] else None), encoding="utf-8")
            name = f"{stem}.{c['id']}.{o['layout']}.mp4"
            src_in = ["-ss", f"{c['start']:.3f}", "-t", f"{dur:.3f}", "-i", str(safe_join(base, src["path"]))]
            inputs = src_in if src.get("hasVideo") else ["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r=25:d={dur:.3f}", *src_in]
            maps = [] if src.get("hasVideo") else ["-map", "0:v", "-map", "1:a", "-shortest"]
            lo, span = 100 * i / len(clips), 100 / len(clips)
            run_ffmpeg([*inputs, *maps, "-vf", f"{vf},subtitles={ass_name}", "-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", *label, name], dur, out_dir,
                       on_progress=lambda p, lo=lo, span=span, i=i: ctx.progress("clip", lo + span * p / 100, f"Xuất clip {i + 1}/{len(clips)}", i, 0, len(clips)),
                       cancelled=ctx.cancelled)
            self.commit(pid, "_set-result", {"id": c["id"], "path": f"exports/clips/{name}"})
            done.append(f"exports/clips/{name}")
        ctx.progress("done", 100, "Hoàn tất")
        return {"files": done}

    # ---- job: video tóm tắt có giọng đọc ----
    def _narration(self, clip: dict, text: str, lang: str, seconds: float, llm_ok: bool) -> tuple[str, bool]:
        max_words = max(6, int(seconds * 2.4))
        if llm_ok:
            system = (f"You write the narration for a summary video. Write 1-2 sentences in {lang_name(lang)} that tell a viewer what happens "
                      f"in this clip, at most {max_words} words, natural spoken style, no hashtags, no quotes. "
                      'Reply with ONLY JSON {"narration": "..."}.')
            res = self.llm.json_object(system, f"Clip title: {clip.get('title', '')}\nTranscript: {excerpt(text, 600)}", NARRATION_SCHEMA, max_tokens=250)
            n = strip_foreign_script(str((res or {}).get("narration", "")), lang).strip()
            if n:
                return " ".join(n.split()[: max_words * 2]), True
        return first_words(text, max_words), False

    def _job_summary(self, ctx: JobContext) -> dict:
        pid = ctx.project_id
        base = self.pdir(pid)
        st, src_lang, _ = self._need_transcript(pid)
        hs, o = self.state(pid), self.opts(pid)
        src = st["source"]
        clips = sorted([c for c in hs["clips"] if c.get("selected")], key=lambda c: c["start"])
        lang = o["narrationLang"] or src_lang
        cues = st["tracks"][src_lang]["cues"]
        work = base / "work" / "summary"
        work.mkdir(parents=True, exist_ok=True)
        llm_ok = True
        try:
            self.llm.require()
        except ApiError:
            llm_ok = False
        ctx.progress("narration", 3, "Viết lời dẫn")
        narr: list[dict] = []
        for i, c in enumerate(clips):
            ctx.check_cancel()
            text = " ".join(x["text"] for x in W.clip_cues(cues, c["start"], c["end"]))
            n, by_llm = self._narration(c, text, lang, c["end"] - c["start"], llm_ok)
            narr.append({"clip": c, "text": n, "llm": by_llm})
            ctx.progress("narration", 3 + 12 * (i + 1) / len(clips), "Viết lời dẫn", i + 1, 0, len(clips))
        voice = self.tts.resolve_voice(o["voice"] or self.tts.default_voice(lang, 0))
        items = [{"id": f"n{i:03d}", "text": n["text"], "voice": voice.voice, "ref_audio": voice.ref_audio, "speed": 1.0, "lang": lang,
                  "out": str(work / f"narr_{i:03d}.wav")} for i, n in enumerate(narr)]
        res = self.tts.synth_batch(ctx, voice.engine, items, 16, 55, "narration-tts")
        errors = res.pop("_errors")
        if errors:
            raise ApiError(422, "TTS_FAILED", "Không đọc được lời dẫn: " + "; ".join(list(errors.values())[:2]))
        segs, t = [], 0.0
        for i, n in enumerate(narr):
            data = A.trim_silence(A.read_mono(Path(res[f"n{i:03d}"]["out"])), A.MIX_SR)
            wav = work / f"narr_{i:03d}.trim.wav"
            A.write_wav(wav, data)
            d = len(data) / A.MIX_SR
            length = n["clip"]["end"] - n["clip"]["start"]
            seg = max(length, d + 0.5)  # lời dẫn dài hơn clip → giữ khung hình cuối (không cắt lời, không chồng lời)
            segs.append({"clip": n["clip"], "text": n["text"], "wav": wav, "dur": d, "len": length, "seg": seg, "start": t})
            t += seg
        total = t
        w, h, vf = self.frame(o["layout"], o["fit"], src)
        ass_cues = [C.make_cue(s["start"] + 0.15, s["start"] + 0.15 + s["dur"], s["text"]) for s in segs]
        out_dir = base / "exports" / "summary"
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(safe_filename(Path(src["filename"]).stem)).stem
        ass_name = f"{stem}.summary.ass"
        (out_dir / ass_name).write_text(C.to_ass(ass_cues, width=w, height=h, margin_v=round(h * (0.12 if o["layout"] == "vertical" else 0.06)),
                                                 wrap_chars=28 if o["layout"] == "vertical" else 42), encoding="utf-8")
        inputs, parts, concat = [], [], ""
        for i, s in enumerate(segs):
            inputs += ["-ss", f"{s['clip']['start']:.3f}", "-t", f"{s['len']:.3f}", "-i", str(safe_join(base, src["path"])), "-i", str(s["wav"])]
            pad = max(0.0, s["seg"] - s["len"])
            parts.append(f"[{2 * i}:v]{vf},setsar=1,fps=25,tpad=stop_mode=clone:stop_duration={pad:.3f}[v{i}]")
            parts.append(f"[{2 * i}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=0.18,apad=whole_dur={s['seg']:.3f}[o{i}]")
            parts.append(f"[{2 * i + 1}:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay=150:all=1,apad=whole_dur={s['seg']:.3f}[n{i}]")
            parts.append(f"[o{i}][n{i}]amix=inputs=2:normalize=0:duration=first[a{i}]")
            concat += f"[v{i}][a{i}]"
        graph = ";".join(parts) + f";{concat}concat=n={len(segs)}:v=1:a=1[vc][ac];[vc]subtitles={ass_name}[v];[ac]loudnorm=I=-16:TP=-1.5:LRA=11[a]"
        out_name = f"{stem}.summary.{o['layout']}.mp4"
        label = ["-metadata", "comment=AI-generated narration (OpenStudio AI)"] if ai_label_enabled(self.s) else []
        ctx.progress("summary", 57, "Ghép video tóm tắt")
        run_ffmpeg([*inputs, "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", *label, out_name], total, out_dir,
                   on_progress=lambda p: ctx.progress("summary", 57 + 42 * p / 100, "Ghép video tóm tắt"), cancelled=ctx.cancelled)
        script = out_dir / f"{stem}.summary.txt"
        script.write_text("\n\n".join(f"[{s['start']:.1f}s] {s['text']}" for s in segs), encoding="utf-8")
        summary = {"path": f"exports/summary/{out_name}", "script": f"exports/summary/{script.name}", "duration": round(total, 2),
                   "narrations": [{"clipId": s["clip"]["id"], "text": s["text"], "start": round(s["start"], 2), "dur": round(s["dur"], 2),
                                   "llm": n["llm"]} for s, n in zip(segs, narr)], "voice": voice.id if hasattr(voice, "id") else None,
                   "lang": lang}
        self.commit(pid, "_set-summary", {"summary": summary})
        ctx.progress("done", 100, "Hoàn tất")
        return summary
