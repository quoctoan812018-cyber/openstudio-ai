"""State machine công cụ "Lồng tiếng" (dubbing). Đọc nguồn + bản dịch từ công cụ phụ đề trong cùng project."""
from __future__ import annotations

import copy
import re

from ..errors import ApiError

TOOL = "dubbing"
LANG_RE = re.compile(r"^[a-z]{2,3}$")
DEFAULTS = {"targetLang": None, "voice": None, "maxSpeed": 1.3, "keepBackground": True, "backgroundGain": -4.0,
            "format": "wav", "minGap": 0.08}


def initial_state() -> dict:
    return {"options": dict(DEFAULTS), "plan": None, "result": None}


def _bad(msg: str) -> ApiError:
    return ApiError(400, "VALIDATION_FAILED", msg)


def reducer(state: dict, type: str, payload: dict) -> dict:
    s = copy.deepcopy(state) or initial_state()
    for k, v in initial_state().items():
        s.setdefault(k, v)

    if type == "set-options":
        o = payload.get("options")
        if not isinstance(o, dict) or set(o) - set(DEFAULTS):
            raise _bad("options không hợp lệ")
        if "targetLang" in o and o["targetLang"] is not None and not LANG_RE.match(str(o["targetLang"])):
            raise _bad("targetLang không hợp lệ")
        if "maxSpeed" in o and not (1.0 <= float(o["maxSpeed"]) <= 1.6):
            raise _bad("maxSpeed phải trong khoảng 1.0–1.6")
        if "backgroundGain" in o and not (-24.0 <= float(o["backgroundGain"]) <= 6.0):
            raise _bad("backgroundGain phải trong khoảng -24…6 dB")
        if "format" in o and o["format"] not in ("wav", "mp3"):
            raise _bad("format phải là wav hoặc mp3")
        if "minGap" in o and not (0.0 <= float(o["minGap"]) <= 1.0):
            raise _bad("minGap phải trong khoảng 0–1 giây")
        s["options"].update(o)
        return s

    if type == "set-item":  # người dùng sửa câu/giọng của một câu → chỉ câu đó bị tổng hợp lại
        if not s["plan"]:
            raise _bad("Chưa có kế hoạch lồng tiếng")
        it = next((x for x in s["plan"]["items"] if x["id"] == payload.get("id")), None)
        if not it:
            raise ApiError(404, "ITEM_NOT_FOUND", "Không có câu này")
        if "text" in payload:
            text = str(payload["text"]).strip()
            if not text or len(text) > 600:
                raise _bad("Câu phải dài 1–600 ký tự")
            it["text"] = text
        if "voice" in payload:
            it["voice"] = str(payload["voice"]) if payload["voice"] else None
        it.update(status="pending", audio=None, duration=None, finalDuration=None, speed=1.0, note=None, shortened=False)
        s["result"] = None
        return s

    if type == "_set-plan":
        s["plan"], s["result"] = payload.get("plan"), None
        return s

    if type == "_set-result":
        s["result"] = payload.get("result")
        return s

    raise _bad(f"Lệnh không hỗ trợ: {type}")
