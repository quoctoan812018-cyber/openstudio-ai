"""State machine công cụ "Giọng đọc" (tts)."""
from __future__ import annotations

import copy

from ..errors import ApiError

TOOL = "tts"
DEFAULTS = {"speed": 1.0, "format": "wav", "gap": 0.3, "loudnorm": True}
ALLOWED_OPTIONS = set(DEFAULTS)
MAX_SCRIPT_CHARS = 100_000


def initial_state() -> dict:
    return {"text": "", "language": "vi", "voices": {}, "options": dict(DEFAULTS), "result": None}


def _bad(msg: str) -> ApiError:
    return ApiError(400, "VALIDATION_FAILED", msg)


def reducer(state: dict, type: str, payload: dict) -> dict:
    s = copy.deepcopy(state) or initial_state()
    for k, v in initial_state().items():
        s.setdefault(k, v)

    if type == "set-script":
        text = payload.get("text")
        if not isinstance(text, str) or len(text) > MAX_SCRIPT_CHARS:
            raise _bad(f"Kịch bản phải là văn bản (tối đa {MAX_SCRIPT_CHARS} ký tự)")
        s["text"] = text
        if payload.get("language"):
            s["language"] = str(payload["language"])[:8]
        return s

    if type == "set-voices":
        v = payload.get("voices")
        if not isinstance(v, dict) or not all(isinstance(k, str) and isinstance(x, str) for k, x in v.items()):
            raise _bad("voices phải là {tên người nói: id giọng}")
        s["voices"] = {k: x for k, x in v.items() if x}
        return s

    if type == "set-options":
        o = payload.get("options")
        if not isinstance(o, dict) or set(o) - ALLOWED_OPTIONS:
            raise _bad("options không hợp lệ")
        if "speed" in o and not (0.5 <= float(o["speed"]) <= 2.0):
            raise _bad("speed phải trong khoảng 0.5–2.0")
        if "format" in o and o["format"] not in ("wav", "mp3"):
            raise _bad("format phải là wav hoặc mp3")
        if "gap" in o and not (0.0 <= float(o["gap"]) <= 3.0):
            raise _bad("gap phải trong khoảng 0–3 giây")
        s["options"].update(o)
        return s

    if type == "_set-result":  # chỉ job nội bộ được dùng (API công khai chặn tiền tố "_")
        s["result"] = payload.get("result")
        return s

    raise _bad(f"Lệnh không hỗ trợ: {type}")
