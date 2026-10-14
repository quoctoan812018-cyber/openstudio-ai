"""Dịch vụ "Giọng đọc": chọn giọng, chạy engine TTS ở tiến trình con, ghép đoạn, chuẩn hoá và xuất file."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..errors import ApiError
from ..jobs import JobContext, JobRunner
from ..models import ModelManager
from ..repo import Repo
from ..security import redact
from ..workers.runner import run_process
from . import audio as A
from .engines import ENGINES, KOKORO_DEFAULT_VOICE, engine_for, preset_voices
from .script import DEFAULT_SPEAKER, parse_script, speakers_of
from .state import TOOL, reducer
from .voices import ConsentStore, VoiceLibrary

DEFAULT_VI_VOICES = ["Mai Anh", "Hải Đăng", "Trúc Ly", "Thiện Minh"]
KOKORO_ALT = {"en": ["af_heart", "am_adam", "bf_emma"], "ja": ["jf_alpha", "jm_kumo"], "zh": ["zf_xiaobei", "zm_yunxi"],
              "es": ["ef_dora", "em_alex"], "fr": ["ff_siwis"], "hi": ["hf_alpha", "hm_omega"], "it": ["if_sara", "im_nicola"],
              "pt": ["pf_dora", "pm_alex"]}


@dataclass
class ResolvedVoice:
    id: str
    engine: str
    voice: str
    ref_audio: str | None = None


def ai_label_enabled(settings: Settings) -> bool:
    try:
        return bool(json.loads(settings.settings_file.read_text(encoding="utf-8")).get("ai_label_metadata", True))
    except (OSError, ValueError):
        return True


class TTSService:
    def __init__(self, settings: Settings, repo: Repo, runner: JobRunner, models: ModelManager, hw: dict,
                 voices: VoiceLibrary, consents: ConsentStore):
        self.s, self.repo, self.runner, self.models, self.hw = settings, repo, runner, models, hw
        self.voices, self.consents = voices, consents
        repo.reducers[TOOL] = reducer
        runner.register("tts.synthesize", self._job_synthesize)
        runner.register("tts.preview", self._job_preview)

    # ---- engine & mô hình ----
    def engine_status(self) -> list[dict]:
        installed = {m["id"] for m in self.models.list() if m["status"] == "installed"}
        out = []
        for eid, e in ENGINES.items():
            if e.get("hidden") and not self.s.dev_fake_tts:
                continue
            out.append({"id": eid, "name": e["name"], "languages": e["languages"], "clone": e["clone"], "model": e["model"],
                        "available": e["model"] is None or e["model"] in installed})
        return out

    def model_paths(self, engine: str) -> dict:
        if engine == "fake":
            if not self.s.dev_fake_tts:
                raise ApiError(400, "VALIDATION_FAILED", "Engine không tồn tại")
            return {}
        mid = ENGINES[engine]["model"]
        if not any(m["id"] == mid and m["status"] == "installed" for m in self.models.list()):
            raise ApiError(424, "MODEL_MISSING", f"Cần tải mô hình '{mid}' trước", {"modelId": mid})
        base = self.s.models_dir
        if engine == "vieneu":
            return {"vieneu_root": str(base / "tts/vieneu-v3-turbo"), "vieneu_codec": str(base / "tts/vieneu-v3-turbo/codec")}
        return {"kokoro_model": str(base / "tts/kokoro-82m-onnx/kokoro-v1.0.onnx"),
                "kokoro_voices": str(base / "tts/kokoro-82m-onnx/voices-v1.0.bin")}

    # ---- giọng ----
    def resolve_voice(self, voice_id: str) -> ResolvedVoice:
        kind, _, name = voice_id.partition(":")
        if kind == "clone":
            meta, ref = self.voices.resolve(name)
            return ResolvedVoice(voice_id, meta["engine"], meta["name"], str(ref))
        if kind in ENGINES and name:
            return ResolvedVoice(voice_id, kind, name)
        raise ApiError(400, "VALIDATION_FAILED", f"Giọng không hợp lệ: {voice_id}")

    def default_voice(self, lang: str, index: int) -> str:
        lang = lang.split("-")[0]
        if self.s.dev_fake_tts and lang == "xx":
            return f"fake:v{index}"
        eng = engine_for(lang)
        if eng == "vieneu":
            names = {v["name"] for v in preset_voices("vi") if v["engine"] == "vieneu"}
            pick = [n for n in DEFAULT_VI_VOICES if n in names] or sorted(names)
            if not pick:
                raise ApiError(424, "NO_VOICE", "Không có giọng tiếng Việt có sẵn")
            return f"vieneu:{pick[index % len(pick)]}"
        if eng == "kokoro":
            alts = KOKORO_ALT.get(lang) or [KOKORO_DEFAULT_VOICE[lang]]
            return f"kokoro:{alts[index % len(alts)]}"
        raise ApiError(400, "UNSUPPORTED_LANGUAGE", f"Chưa có engine đọc cho ngôn ngữ '{lang}'")

    # ---- chạy engine ----
    def synth_batch(self, ctx: JobContext, engine: str, items: list[dict], lo: float, hi: float, phase: str = "tts") -> dict[str, dict]:
        """items: [{id,text,voice,ref_audio,speed,out}] → {id: {duration,sr,out}}; id lỗi nằm ở results["_errors"]."""
        if not items:
            return {}
        args = {"engine": engine, "paths": self.model_paths(engine), "items": items}
        results: dict[str, dict] = {"_errors": {}}

        def on_line(line: str) -> None:
            try:
                m = json.loads(line)
            except ValueError:
                return
            if m.get("type") == "progress":
                ctx.progress(phase, lo + (hi - lo) * m["percent"] / 100, "Tổng hợp giọng nói", len(results) - 1, len(results["_errors"]), len(items))
            elif m.get("type") == "item":
                it = next(x for x in items if x["id"] == m["id"])
                results[m["id"]] = {"duration": m["duration"], "sr": m["sr"], "out": it["out"]}
            elif m.get("type") == "item_error":
                results["_errors"][m["id"]] = m["message"]

        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2]), "PYTHONIOENCODING": "utf-8"}
        code, tail = run_process([sys.executable, "-m", "openstudio.workers.tts_worker", json.dumps(args, ensure_ascii=False)],
                                 env=env, on_line=on_line, cancelled=ctx.cancelled)
        if code != 0:
            raise ApiError(422, "TTS_FAILED", "Engine TTS lỗi: " + redact(tail[-400:]))
        return results

    # ---- tạo job ----
    def _state(self, pid: str) -> dict:
        st = self.repo.get_state(pid, TOOL)["state"]
        return st or {"text": "", "language": "vi", "voices": {}, "options": {}, "result": None}

    def plan_voices(self, state: dict) -> tuple[list, dict[str, ResolvedVoice]]:
        segs = parse_script(state.get("text", ""))
        speakers = speakers_of(segs)
        if not speakers:
            raise ApiError(400, "VALIDATION_FAILED", "Kịch bản trống")
        lang = state.get("language", "vi")
        resolved: dict[str, ResolvedVoice] = {}
        for i, sp in enumerate(speakers):
            vid = state.get("voices", {}).get(sp) or (state.get("voices", {}).get(DEFAULT_SPEAKER) if len(speakers) == 1 else None) \
                or self.default_voice(lang, i)
            resolved[sp] = self.resolve_voice(vid)
        return segs, resolved

    def start_synthesize(self, pid: str) -> dict:
        state = self._state(pid)
        _, resolved = self.plan_voices(state)
        for r in resolved.values():
            self.model_paths(r.engine)  # 424 sớm nếu thiếu mô hình
        return self.runner.submit("tts.synthesize", {}, pid, TOOL)

    def start_preview(self, pid: str, voice: str, text: str, lang: str) -> dict:
        self.repo.get_project(pid)
        r = self.resolve_voice(voice)
        self.model_paths(r.engine)
        if not text.strip() or len(text) > 400:
            raise ApiError(400, "VALIDATION_FAILED", "Câu thử giọng phải dài 1–400 ký tự")
        return self.runner.submit("tts.preview", {"voice": voice, "text": text, "lang": lang}, pid, TOOL)

    def _item(self, idx: int, text: str, r: ResolvedVoice, speed: float, out: Path) -> dict:
        native = ENGINES[r.engine]["native_speed"]
        return {"id": f"s{idx:04d}", "text": text, "voice": r.voice, "ref_audio": r.ref_audio, "speed": speed if native else 1.0,
                "lang": None, "out": str(out)}

    def _job_preview(self, ctx: JobContext) -> dict:
        pid, p = ctx.project_id, ctx.params
        base = self.s.projects_dir / pid
        r = self.resolve_voice(p["voice"])
        out = base / "work" / "tts" / f"preview_{ctx.job_id}.wav"
        res = self.synth_batch(ctx, r.engine, [self._item(0, p["text"], r, 1.0, out)], 0, 95, "preview")
        if "s0000" not in res:
            raise ApiError(422, "TTS_FAILED", res["_errors"].get("s0000", "Không tạo được giọng thử"))
        exp = base / "exports" / f"preview_{ctx.job_id}.wav"
        A.export_audio(out, exp, loudnorm=False, ai_label=ai_label_enabled(self.s))
        return {"path": f"exports/{exp.name}", "duration": res["s0000"]["duration"]}

    def _job_synthesize(self, ctx: JobContext) -> dict:
        pid = ctx.project_id
        base = self.s.projects_dir / pid
        state = self._state(pid)
        opts = {"speed": 1.0, "format": "wav", "gap": 0.3, "loudnorm": True, **state.get("options", {})}
        segs, resolved = self.plan_voices(state)
        work = base / "work" / "tts" / ctx.job_id
        work.mkdir(parents=True, exist_ok=True)

        spoken = [(i, s) for i, s in enumerate(segs) if s.text.strip()]
        by_engine: dict[str, list[dict]] = {}
        for i, s in spoken:
            r = resolved[s.speaker]
            by_engine.setdefault(r.engine, []).append(self._item(i, s.text, r, float(opts["speed"]), work / f"seg_{i:04d}.wav"))
        results: dict[str, dict] = {}
        errors: dict[str, str] = {}
        engines = list(by_engine)
        for k, eng in enumerate(engines):
            lo, hi = 90 * k / len(engines), 90 * (k + 1) / len(engines)
            res = self.synth_batch(ctx, eng, by_engine[eng], lo, hi)
            errors.update(res.pop("_errors"))
            results.update(res)
        if not results:
            raise ApiError(422, "TTS_FAILED", "Không đoạn nào đọc được: " + "; ".join(list(errors.values())[:2]))

        ctx.progress("assemble", 92, "Ghép và chuẩn hoá")
        clips: list[tuple] = []
        meta: list[dict] = []
        prev_speaker = None
        for i, s in enumerate(segs):
            if not s.text.strip():
                if clips:  # đoạn chỉ có [nghỉ] → cộng vào khoảng lặng sau đoạn trước
                    clips[-1] = (clips[-1][0], clips[-1][1] + s.pause_after)
                continue
            key = f"s{i:04d}"
            if key not in results:
                continue
            r = resolved[s.speaker]
            data = A.read_mono(Path(results[key]["out"]))
            if not ENGINES[r.engine]["native_speed"] and abs(float(opts["speed"]) - 1.0) > 0.01:
                tmp = Path(results[key]["out"]).with_suffix(".t.wav")
                A.change_tempo(Path(results[key]["out"]), tmp, float(opts["speed"]))
                data = A.read_mono(tmp)
            data = A.fade(A.trim_silence(data, A.MIX_SR), A.MIX_SR)
            gap = s.pause_after if s.pause_after > 0 else (float(opts["gap"]) + (0.15 if prev_speaker not in (None, s.speaker) else 0.0))
            clips.append((data, gap))
            meta.append({"index": i, "speaker": s.speaker, "text": s.text, "voice": r.id})
            prev_speaker = s.speaker
        wave, spans = A.concat_with_gaps(clips)
        for m, (a, b) in zip(meta, spans):
            m["start"], m["end"] = a, b
        raw = work / "mix.wav"
        A.write_wav(raw, wave)
        name = f"giong-doc-{ctx.job_id[-6:]}.{opts['format']}"
        out = base / "exports" / name
        A.export_audio(raw, out, loudnorm=bool(opts["loudnorm"]), ai_label=ai_label_enabled(self.s))
        result = {"path": f"exports/{name}", "duration": round(len(wave) / A.MIX_SR, 2), "segments": meta,
                  "failed": [{"id": k, "message": v} for k, v in errors.items()]}
        self.repo.apply_command(pid, TOOL, "_set-result", {"result": result}, None, author="job")
        ctx.progress("done", 100, "Hoàn tất")
        return result
