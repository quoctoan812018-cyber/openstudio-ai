"""Danh mục engine TTS: ngôn ngữ, khả năng nhân bản, mô hình cần tải, danh sách giọng có sẵn."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

# id engine → thông tin
ENGINES: dict[str, dict] = {
    "vieneu": {
        "name": "VieNeu-TTS v3 Turbo", "model": "vieneu-tts-v3-turbo", "languages": ["vi", "en"], "clone": True,
        "sample_rate": 48000, "native_speed": False, "online": False,
    },
    "kokoro": {
        "name": "Kokoro-82M", "model": "kokoro-82m-onnx", "languages": ["en", "ja", "zh", "es", "fr", "hi", "it", "pt"],
        "clone": False, "sample_rate": 24000, "native_speed": True, "online": False,
    },
    # engine giả cho kiểm thử, không bao giờ xuất hiện trong danh sách thật
    "fake": {"name": "Fake", "model": None, "languages": ["vi", "en", "ja", "zh"], "clone": True, "sample_rate": 24000,
             "native_speed": False, "online": False, "hidden": True},
}

# Ngôn ngữ → engine mặc định. Tiếng Việt: VieNeu. Còn lại: Kokoro nếu hỗ trợ.
DEFAULT_ENGINE = {"vi": "vieneu", "en": "kokoro", "ja": "kokoro", "zh": "kokoro", "es": "kokoro", "fr": "kokoro",
                  "hi": "kokoro", "it": "kokoro", "pt": "kokoro"}

KOKORO_LANG = {"en": "en-us", "ja": "ja", "zh": "cmn", "es": "es", "fr": "fr-fr", "hi": "hi", "it": "it", "pt": "pt-br"}
KOKORO_PREFIX_LANG = {"a": "en", "b": "en", "j": "ja", "z": "zh", "e": "es", "f": "fr", "h": "hi", "i": "it", "p": "pt"}
KOKORO_DEFAULT_VOICE = {"en": "af_heart", "ja": "jf_alpha", "zh": "zf_xiaobei", "es": "ef_dora", "fr": "ff_siwis",
                        "hi": "hf_alpha", "it": "if_sara", "pt": "pf_dora"}
# Danh sách giọng Kokoro v1.0 (xem VOICES.md của model). Tên giọng là giọng tổng hợp của mô hình, không phải người thật.
KOKORO_VOICES = [
    "af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky", "am_adam", "am_michael", "bf_emma", "bf_isabella",
    "bm_george", "bm_lewis", "jf_alpha", "jm_kumo", "zf_xiaobei", "zm_yunxi", "ef_dora", "em_alex", "ff_siwis",
    "hf_alpha", "hm_omega", "if_sara", "im_nicola", "pf_dora", "pm_alex",
]


def engine_for(lang: str) -> str | None:
    return DEFAULT_ENGINE.get(lang.split("-")[0].lower())


def kokoro_voice_lang(voice: str) -> str:
    return KOKORO_PREFIX_LANG.get(voice[:1], "en")


@lru_cache(maxsize=1)
def vieneu_presets() -> list[dict]:
    """Giọng có sẵn của VieNeu, đọc từ file đi kèm gói (không cần nạp mô hình)."""
    try:
        import vieneu
        data = json.loads((Path(vieneu.__file__).parent / "assets" / "voices_v3_turbo.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    out = []
    for name, v in data.get("presets", {}).items():
        out.append({"id": f"vieneu:{name}", "name": name, "engine": "vieneu", "lang": "vi", "description": v.get("description", ""),
                    "gender": v.get("gender", ""), "kind": "preset"})
    return out


def preset_voices(lang: str | None = None) -> list[dict]:
    voices = list(vieneu_presets())
    for v in KOKORO_VOICES:
        voices.append({"id": f"kokoro:{v}", "name": v, "engine": "kokoro", "lang": kokoro_voice_lang(v),
                       "description": "Giọng tổng hợp của Kokoro", "gender": "female" if v[1] == "f" else "male", "kind": "preset"})
    return [v for v in voices if lang is None or v["lang"] == lang.split("-")[0] or (v["engine"] == "vieneu" and lang == "en")]
