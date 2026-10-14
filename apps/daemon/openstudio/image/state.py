"""State machine công cụ Tạo ảnh (AI, cục bộ): prompt (+ ảnh tham chiếu) → vài biến thể."""
from __future__ import annotations

import copy
import uuid

from ..errors import ApiError

TOOL = "image"
ASPECTS = {"1:1": (1, 1), "16:9": (16, 9), "9:16": (9, 16), "4:3": (4, 3), "3:4": (3, 4)}
QUALITY = {"draft": 512, "standard": 768, "high": 1024}      # cạnh dài (px). CPU: càng lớn càng chậm (xấp xỉ bình phương)
DEFAULT_BRIEF = {"prompt": "", "aspect": "1:1", "quality": "draft", "count": 1, "seed": None, "refAsset": None, "translate": True, "language": "vi"}
MAX_PROMPT = 1500


def initial_state() -> dict:
    return {"brief": copy.deepcopy(DEFAULT_BRIEF), "results": [], "last": None}


def _bad(msg: str) -> ApiError:
    return ApiError(400, "VALIDATION_FAILED", msg)


def dims(aspect: str, quality: str) -> tuple[int, int]:
    """Kích thước ảnh: cạnh dài theo chất lượng, bội số của 16 (yêu cầu của FLUX)."""
    a, b = ASPECTS[aspect]
    long_edge = QUALITY[quality]
    w, h = (long_edge, long_edge * b / a) if a >= b else (long_edge * a / b, long_edge)
    return max(256, round(w / 16) * 16), max(256, round(h / 16) * 16)


def reducer(state: dict, type: str, payload: dict) -> dict:
    s = copy.deepcopy(state) or initial_state()
    for k, v in initial_state().items():
        s.setdefault(k, v)

    if type == "set-brief":
        o = payload.get("brief")
        if not isinstance(o, dict) or set(o) - set(DEFAULT_BRIEF):
            raise _bad("brief không hợp lệ")
        m = {**s["brief"], **o}
        if not isinstance(m["prompt"], str) or len(m["prompt"]) > MAX_PROMPT:
            raise _bad(f"prompt tối đa {MAX_PROMPT} ký tự")
        if m["aspect"] not in ASPECTS or m["quality"] not in QUALITY:
            raise _bad("aspect: " + ", ".join(ASPECTS) + " · quality: draft/standard/high")
        if not isinstance(m["count"], int) or isinstance(m["count"], bool) or not (1 <= m["count"] <= 4):
            raise _bad("count phải từ 1 đến 4 (mỗi ảnh tốn nhiều phút trên CPU)")
        if m["seed"] is not None and (not isinstance(m["seed"], int) or isinstance(m["seed"], bool) or not (0 <= m["seed"] < 2**31)):
            raise _bad("seed phải là số nguyên ≥ 0 hoặc null")
        m["translate"] = bool(m["translate"])
        s["brief"] = m
        return s

    if type == "apply-template":
        t = payload.get("template")
        if not isinstance(t, dict) or not isinstance(t.get("brief"), dict):
            raise _bad("template không hợp lệ")
        return reducer(s, "set-brief", {"brief": {k: v for k, v in t["brief"].items() if k in ("aspect", "quality", "count", "translate")}})

    if type == "_add-results":
        s["results"] = [*payload["results"], *s["results"]][:60]
        s["last"] = payload.get("last")
        return s

    if type == "remove-result":
        n = len(s["results"])
        s["results"] = [r for r in s["results"] if r["id"] != payload.get("id")]
        if len(s["results"]) == n:
            raise ApiError(404, "RESULT_NOT_FOUND", "Không có ảnh này")
        return s

    raise _bad(f"Lệnh không hỗ trợ: {type}")


def new_id() -> str:
    return "i" + uuid.uuid4().hex[:7]
