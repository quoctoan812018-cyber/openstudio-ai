"""Tiến trình con TTS. Nạp mô hình MỘT lần rồi đọc nhiều đoạn.

Đối số: một chuỗi JSON {"engine", "paths": {...}, "items": [{"id","text","lang","voice","speed","ref_audio","out"}]}.
stdout: các dòng JSON {"type":"item","id","duration","sr"} | {"type":"item_error","id","message"} | {"type":"progress","percent"} | {"type":"done"}.
"""
from __future__ import annotations

import json
import math
import os
import zlib
import sys

import numpy as np
import soundfile as sf


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


class FakeEngine:
    """Sóng sin dài theo số từ (cho test): ~0.35s/từ, chia theo `speed`."""
    sample_rate = 24000

    def __init__(self, paths: dict):
        pass

    def synth(self, it: dict) -> tuple[np.ndarray, int]:
        words = max(1, len(it["text"].split()))
        secs = 0.35 * words / max(0.5, float(it.get("speed") or 1.0))
        t = np.arange(int(secs * self.sample_rate)) / self.sample_rate
        freq = 220 + (zlib.crc32((it.get("voice") or "").encode()) % 200)  # ổn định giữa các lần chạy
        return (0.3 * np.sin(2 * math.pi * freq * t)).astype(np.float32), self.sample_rate


class KokoroEngine:
    sample_rate = 24000

    def __init__(self, paths: dict):
        from kokoro_onnx import Kokoro
        self.k = Kokoro(paths["kokoro_model"], paths["kokoro_voices"])

    def synth(self, it: dict) -> tuple[np.ndarray, int]:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from openstudio.tts.engines import KOKORO_LANG, kokoro_voice_lang
        voice = it["voice"]
        lang = KOKORO_LANG.get(kokoro_voice_lang(voice), "en-us")
        samples, sr = self.k.create(it["text"], voice=voice, speed=float(it.get("speed") or 1.0), lang=lang)
        return np.asarray(samples, dtype=np.float32), int(sr)


class VieNeuEngine:
    sample_rate = 48000

    def __init__(self, paths: dict):
        import vieneu._v3_turbo_engine.onnx_runtime_lite as lite
        from vieneu import Vieneu

        root, codec = paths["vieneu_root"], paths["vieneu_codec"]
        orig = lite.OnnxV3LiteEngine.__init__

        def patched(self, *a, **kw):  # codec nằm ở thư mục cục bộ, không tải từ HF
            kw.setdefault("codec_dir", codec)
            return orig(self, *a, **kw)

        lite.OnnxV3LiteEngine.__init__ = patched
        self.tts = Vieneu(mode="v3turbo", backbone_repo=root, backend="onnx", onnx_dir=os.path.join(root, "onnx_update"),
                          threads=int(paths.get("threads", 0)))
        self.presets = {n for _, n in self.tts.list_preset_voices()}

    def synth(self, it: dict) -> tuple[np.ndarray, int]:
        text = it["text"]
        if it.get("ref_audio"):
            audio = self.tts.infer(text, ref_audio=it["ref_audio"], denoise=True)
        else:
            voice = (it.get("voice") or "").split(":", 1)[-1]
            audio = self.tts.infer(text, voice=voice if voice in self.presets else None)
        return np.asarray(audio, dtype=np.float32), self.sample_rate


ENGINES = {"fake": FakeEngine, "kokoro": KokoroEngine, "vieneu": VieNeuEngine}


def main() -> None:
    args = json.loads(sys.argv[1])
    os.environ.setdefault("HF_HUB_OFFLINE", "1")  # mọi mô hình đã nằm ở máy
    eng = ENGINES[args["engine"]](args.get("paths", {}))
    items = args["items"]
    emit({"type": "progress", "percent": 2})
    for i, it in enumerate(items):
        try:
            audio, sr = eng.synth(it)
            os.makedirs(os.path.dirname(it["out"]), exist_ok=True)
            sf.write(it["out"], audio, sr, subtype="PCM_16")
            emit({"type": "item", "id": it["id"], "duration": len(audio) / sr, "sr": sr})
        except Exception as e:  # noqa: BLE001 — một đoạn lỗi không làm hỏng cả lô
            emit({"type": "item_error", "id": it["id"], "message": f"{type(e).__name__}: {e}"[:300]})
        emit({"type": "progress", "percent": 2 + 97 * (i + 1) / len(items)})
    emit({"type": "done"})


if __name__ == "__main__":
    main()
