"""State machine Thumbnail & ảnh bìa (không dùng AI sinh ảnh): ảnh/khung hình video/nền gradient + chữ tiêu đề tiếng Việt + logo."""
from __future__ import annotations

import copy
import re
import uuid

from ..errors import ApiError

TOOL = "thumbnail"
ASPECTS = {"16:9": (1280, 720), "9:16": (1080, 1920), "1:1": (1080, 1080)}
LAYOUTS = ("banner", "center", "left", "top")
PALETTES = {"navy": {"title": "#FFFFFF", "box": "#0B1B3A"}, "sun": {"title": "#111111", "box": "#FFD21F"}, "fire": {"title": "#FFFFFF", "box": "#D7263D"},
            "mint": {"title": "#0B3D2E", "box": "#B8F2D2"}, "ink": {"title": "#FFE14A", "box": "#000000"}}
BACKGROUND_KINDS = ("gradient", "asset", "frame")
DEFAULT_BRIEF = {"title": "", "subtitle": "", "aspect": "16:9", "layouts": ["banner", "center", "left", "top"], "palettes": ["navy", "sun", "fire", "ink"],
                 "background": {"kind": "gradient", "asset": None, "at": 1.0, "dim": 0.35}, "brand": {"asset": None, "position": "br", "width": 0.14}, "count": 4}
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def initial_state() -> dict:
    return {"brief": copy.deepcopy(DEFAULT_BRIEF), "variants": [], "selected": None}


def _bad(msg: str) -> ApiError:
    return ApiError(400, "VALIDATION_FAILED", msg)


def validate_brief(b: dict) -> dict:
    for k, lim in (("title", 90), ("subtitle", 140)):
        if not isinstance(b.get(k), str) or len(b[k]) > lim:
            raise _bad(f"{k} tối đa {lim} ký tự")
    if b["aspect"] not in ASPECTS:
        raise _bad("aspect phải là 16:9, 9:16 hoặc 1:1")
    if not isinstance(b["layouts"], list) or not b["layouts"] or any(x not in LAYOUTS for x in b["layouts"]):
        raise _bad("layouts: " + ", ".join(LAYOUTS))
    if not isinstance(b["palettes"], list) or not b["palettes"] or any(x not in PALETTES for x in b["palettes"]):
        raise _bad("palettes: " + ", ".join(PALETTES))
    if not isinstance(b["count"], int) or isinstance(b["count"], bool) or not (1 <= b["count"] <= 8):
        raise _bad("count phải từ 1 đến 8")
    bg = b["background"]
    if not isinstance(bg, dict) or bg.get("kind") not in BACKGROUND_KINDS:
        raise _bad("background.kind: " + ", ".join(BACKGROUND_KINDS))
    if bg["kind"] != "gradient" and not bg.get("asset"):
        raise _bad("Nền ảnh/khung hình cần chọn tài nguyên")
    if not isinstance(bg.get("at", 0), (int, float)) or bg["at"] < 0 or not isinstance(bg.get("dim", 0), (int, float)) or not (0 <= bg["dim"] <= 0.8):
        raise _bad("background.at ≥ 0 và dim trong 0–0,8")
    br = b["brand"]
    if not isinstance(br, dict) or br.get("position") not in ("tl", "tr", "bl", "br") or not (0.04 <= float(br.get("width", 0.14)) <= 0.4):
        raise _bad("brand.position: tl/tr/bl/br; width 0,04–0,4")
    return b


def reducer(state: dict, type: str, payload: dict) -> dict:
    s = copy.deepcopy(state) or initial_state()
    for k, v in initial_state().items():
        s.setdefault(k, v)

    if type == "set-brief":
        o = payload.get("brief")
        if not isinstance(o, dict) or set(o) - set(DEFAULT_BRIEF):
            raise _bad("brief không hợp lệ")
        m = {**s["brief"], **o}
        for k in ("background", "brand"):
            if k in o and isinstance(o[k], dict):
                m[k] = {**s["brief"][k], **o[k]}
        s["brief"] = validate_brief(m)
        return s

    if type == "apply-template":
        t = payload.get("template")
        if not isinstance(t, dict) or not isinstance(t.get("brief"), dict):
            raise _bad("template không hợp lệ")
        allowed = {k: v for k, v in t["brief"].items() if k in ("aspect", "layouts", "palettes", "count")}
        s["brief"] = validate_brief({**s["brief"], **allowed})
        return s

    if type == "_set-variants":
        s["variants"], s["selected"] = payload["variants"], None
        return s

    if type == "select":
        if not any(v["id"] == payload.get("id") for v in s["variants"]):
            raise ApiError(404, "VARIANT_NOT_FOUND", "Không có biến thể này")
        s["selected"] = payload["id"]
        return s

    raise _bad(f"Lệnh không hỗ trợ: {type}")


def new_variant_id() -> str:
    return "v" + uuid.uuid4().hex[:6]
