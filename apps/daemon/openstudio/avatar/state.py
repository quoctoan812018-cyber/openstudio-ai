"""State machine công cụ Avatar AI nói."""
from __future__ import annotations

import copy
import re

from ..errors import ApiError

TOOL = "avatar"
ASPECTS = ("16:9", "9:16", "1:1")
DEFAULT_BRIEF = {"avatar": None, "audio": None, "aspect": "16:9", "background": {"kind": "blur", "color": "#101828", "asset": None},
                 "frame": "rounded", "border": True, "subtitleLang": None, "engine": "puppet"}
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def initial_state() -> dict:
    return {"brief": copy.deepcopy(DEFAULT_BRIEF), "result": None}


def _bad(msg: str) -> ApiError:
    return ApiError(400, "VALIDATION_FAILED", msg)


def reducer(state: dict, type: str, payload: dict) -> dict:
    s = copy.deepcopy(state) or initial_state()
    for k, v in initial_state().items():
        s.setdefault(k, v)

    if type == "set-brief":
        o = payload.get("brief")
        if not isinstance(o, dict) or set(o) - set(DEFAULT_BRIEF):
            raise _bad("brief không hợp lệ")
        m = {**s["brief"], **o}
        if "background" in o and isinstance(o["background"], dict):
            m["background"] = {**s["brief"]["background"], **o["background"]}
        bg = m["background"]
        if m["aspect"] not in ASPECTS or m["frame"] not in ("none", "rounded", "circle") or m["engine"] != "puppet":
            raise _bad("aspect: 16:9/9:16/1:1 · frame: none/rounded/circle · engine: puppet (lip-sync AI cần GPU, chưa có)")
        if bg.get("kind") not in ("blur", "color", "image") or not isinstance(bg.get("color"), str) or not COLOR.match(bg["color"]):
            raise _bad("background.kind: blur/color/image; color dạng #RRGGBB")
        if bg["kind"] == "image" and not bg.get("asset"):
            raise _bad("Nền ảnh cần chọn một ảnh trong kho tài nguyên")
        if m["subtitleLang"] is not None and not re.fullmatch(r"[a-z]{2,3}", str(m["subtitleLang"])):
            raise _bad("subtitleLang phải là mã ngôn ngữ (vd. vi) hoặc null")
        m["border"] = bool(m["border"])
        s["brief"] = m
        s["result"] = None
        return s

    if type == "apply-template":
        t = payload.get("template")
        if not isinstance(t, dict) or not isinstance(t.get("brief"), dict):
            raise _bad("template không hợp lệ")
        return reducer(s, "set-brief", {"brief": {k: v for k, v in t["brief"].items() if k in ("aspect", "frame", "border")}})

    if type == "_set-result":
        s["result"] = payload["result"]
        return s

    raise _bad(f"Lệnh không hỗ trợ: {type}")
