"""State machine công cụ "Tóm tắt & Highlight" (highlights)."""
from __future__ import annotations

import copy
import re

from ..errors import ApiError

TOOL = "highlights"
DEFAULTS = {"count": 3, "minLen": 20.0, "maxLen": 60.0, "layout": "vertical", "fit": "crop", "subtitleLang": None,
            "hookOverlay": True, "useLlm": True, "narrationLang": None, "voice": None}
CLIP_ID = re.compile(r"^c\d{3,4}$")


def initial_state() -> dict:
    return {"options": dict(DEFAULTS), "analysis": None, "clips": [], "results": {}, "summary": None}


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
        merged = {**s["options"], **o}
        if not (1 <= int(merged["count"]) <= 10):
            raise _bad("count phải trong khoảng 1–10")
        if not (5 <= float(merged["minLen"]) < float(merged["maxLen"]) <= 180):
            raise _bad("Cần 5 ≤ minLen < maxLen ≤ 180 giây")
        if merged["layout"] not in ("vertical", "horizontal") or merged["fit"] not in ("crop", "pad"):
            raise _bad("layout/fit không hợp lệ")
        s["options"] = merged
        return s

    if type == "set-clip":
        clip = next((c for c in s["clips"] if c["id"] == payload.get("id")), None)
        if not clip:
            raise ApiError(404, "CLIP_NOT_FOUND", "Không có clip này")
        for k in ("title", "hook"):
            if k in payload:
                clip[k] = str(payload[k]).strip()[:160]
        if "selected" in payload:
            clip["selected"] = bool(payload["selected"])
        if "start" in payload or "end" in payload:
            a, b = float(payload.get("start", clip["start"])), float(payload.get("end", clip["end"]))
            if a < 0 or not (3.0 <= b - a <= 180.0):
                raise _bad("Clip phải dài 3–180 giây")
            clip["start"], clip["end"] = round(a, 3), round(b, 3)
            s["results"].pop(clip["id"], None)  # khung cắt đổi → file đã xuất không còn khớp
        if "title" in payload or "hook" in payload:
            s["results"].pop(clip["id"], None)
        return s

    if type == "add-clip":
        a, b = float(payload.get("start", -1)), float(payload.get("end", -1))
        if a < 0 or not (3.0 <= b - a <= 180.0):
            raise _bad("Clip phải dài 3–180 giây")
        n = max([int(c["id"][1:]) for c in s["clips"]] + [0]) + 1
        s["clips"].append({"id": f"c{n:03d}", "start": round(a, 3), "end": round(b, 3), "title": str(payload.get("title", "")).strip()[:160],
                           "hook": str(payload.get("hook", "")).strip()[:160], "score": None, "reason": "Thêm thủ công", "selected": True,
                           "manual": True})
        s["clips"].sort(key=lambda c: c["start"])
        return s

    if type == "remove-clip":
        s["clips"] = [c for c in s["clips"] if c["id"] != payload.get("id")]
        s["results"].pop(payload.get("id"), None)
        return s

    if type == "_set-analysis":
        s["analysis"], s["clips"], s["results"], s["summary"] = payload["analysis"], payload["clips"], {}, None
        return s

    if type == "_set-result":
        cid = payload.get("id")
        if not isinstance(cid, str) or not CLIP_ID.match(cid):
            raise _bad("id clip không hợp lệ")
        s["results"][cid] = payload.get("path")
        return s

    if type == "_set-summary":
        s["summary"] = payload.get("summary")
        return s

    raise _bad(f"Lệnh không hỗ trợ: {type}")
