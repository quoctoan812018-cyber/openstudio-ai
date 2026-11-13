"""State machine công cụ Tạo video: ẢNH → VIDEO CHUYỂN ĐỘNG bằng FFmpeg (zoom/lia máy kiểu Ken Burns, hoặc đứng yên)
và lớp hạt vẽ bằng code (cánh hoa rơi). Không phải AI sinh video."""
from __future__ import annotations

import copy

from ..errors import ApiError

TOOL = "video"
PRESETS = ("still", "zoom-in", "zoom-out", "pan-left", "pan-right", "pan-up", "pan-down")
ASPECTS = ("16:9", "9:16", "1:1")
OVERLAYS = ("none", "petals")
DEFAULT_BRIEF = {"asset": None, "duration": 6.0, "preset": "zoom-in", "aspect": "16:9", "quality": 720, "fps": 25, "audio": None, "strength": 0.25,
                 "overlay": "none", "overlayDensity": 1.5, "overlayOrigin": None, "overlayFloor": None, "overlaySeed": 1}


def initial_state() -> dict:
    return {"brief": copy.deepcopy(DEFAULT_BRIEF), "result": None}


def _bad(msg: str) -> ApiError:
    return ApiError(400, "VALIDATION_FAILED", msg)


def _frac(v) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float)) and 0.0 <= v <= 1.0


def _check_overlay(m: dict) -> None:
    if m["overlay"] not in OVERLAYS:
        raise _bad("overlay: " + ", ".join(OVERLAYS))
    d = m["overlayDensity"]
    if isinstance(d, bool) or not isinstance(d, (int, float)) or not (0.1 <= d <= 10.0):
        raise _bad("overlayDensity phải trong khoảng 0.1–10 (cánh/giây)")
    o = m["overlayOrigin"]
    if o is not None and not (isinstance(o, list) and len(o) == 2 and all(_frac(v) for v in o)):
        raise _bad("overlayOrigin là null (rơi từ mép trên) hoặc [x, y] theo tỉ lệ 0–1")
    if m["overlayFloor"] is not None and not _frac(m["overlayFloor"]):
        raise _bad("overlayFloor là null (rơi ra khỏi khung) hoặc tỉ lệ chiều cao 0–1")
    if m["overlayFloor"] is not None and o is not None and m["overlayFloor"] <= o[1]:
        raise _bad("overlayFloor phải nằm dưới overlayOrigin")
    if isinstance(m["overlaySeed"], bool) or not isinstance(m["overlaySeed"], int) or not (0 <= m["overlaySeed"] < 2**31):
        raise _bad("overlaySeed phải là số nguyên ≥ 0")


def reducer(state: dict, type: str, payload: dict) -> dict:
    s = copy.deepcopy(state) or initial_state()
    for k, v in initial_state().items():
        s.setdefault(k, v)

    if type == "set-brief":
        o = payload.get("brief")
        if not isinstance(o, dict) or set(o) - set(DEFAULT_BRIEF):
            raise _bad("brief không hợp lệ")
        m = {**s["brief"], **o}
        if m["preset"] not in PRESETS or m["aspect"] not in ASPECTS or m["quality"] not in (480, 720, 1080) or m["fps"] not in (24, 25, 30):
            raise _bad("preset: " + ", ".join(PRESETS) + " · aspect: 16:9/9:16/1:1 · quality: 480/720/1080 · fps: 24/25/30")
        for k, lo, hi in (("duration", 1.0, 60.0), ("strength", 0.05, 0.6)):
            if isinstance(m[k], bool) or not isinstance(m[k], (int, float)) or not (lo <= m[k] <= hi):
                raise _bad(f"{k} phải trong khoảng {lo}–{hi}")
        _check_overlay(m)
        s["brief"], s["result"] = m, None
        return s

    if type == "_set-result":
        s["result"] = payload["result"]
        return s

    raise _bad(f"Lệnh không hỗ trợ: {type}")
