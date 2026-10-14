"""State machine công cụ Phụ đề & Dịch: reducer cho mọi lệnh (UI, Agent và job dùng chung)."""
from __future__ import annotations

import copy
import re

from ..errors import ApiError
from .cues import normalize, validate

TOOL = "subtitles"
LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
DEFAULT_OPTIONS = {"tone": "neutral", "polish": True, "market": None, "maxChars": 84}
ALLOWED_OPTIONS = {"tone", "polish", "market", "maxChars"}


def initial_state() -> dict:
    return {"source": None, "sourceLang": None, "tracks": {}, "glossary": [], "options": dict(DEFAULT_OPTIONS)}


def _bad(msg: str) -> ApiError:
    return ApiError(400, "VALIDATION_FAILED", msg)


def _clean_cues(raw) -> list[dict]:
    if not isinstance(raw, list):
        raise _bad("cues phải là mảng")
    cues = []
    for c in raw:
        try:
            cues.append({"start": float(c["start"]), "end": float(c["end"]), "text": str(c["text"])})
        except (KeyError, TypeError, ValueError):
            raise _bad("Mỗi cue cần start, end (số) và text")
    cues = normalize(cues)
    problems = validate(cues)
    if problems:  # normalize đã sửa chồng lấn; còn lỗi nghĩa là dữ liệu hỏng
        raise _bad("Cue không hợp lệ: " + "; ".join(problems[:3]))
    return cues


def reducer(state: dict, type: str, payload: dict) -> dict:
    s = copy.deepcopy(state) or initial_state()
    for k, v in initial_state().items():
        s.setdefault(k, v)

    if type == "set-source":
        src = payload.get("source")
        if not isinstance(src, dict) or not src.get("path"):
            raise _bad("payload.source cần có path")
        return {**initial_state(), "source": src, "glossary": s["glossary"], "options": s["options"]}

    if type == "set-track":
        lang, kind = payload.get("lang"), payload.get("kind", "translation")
        if not isinstance(lang, str) or not LANG_RE.match(lang):
            raise _bad("Mã ngôn ngữ không hợp lệ")
        if kind not in ("transcript", "translation"):
            raise _bad("kind phải là transcript hoặc translation")
        if s["source"] is None:
            raise _bad("Chưa có nguồn")
        track = {"kind": kind, "cues": _clean_cues(payload.get("cues")), "stale": False,
                 "meta": payload.get("meta") if isinstance(payload.get("meta"), dict) else {}}
        if kind == "transcript":
            s["sourceLang"] = lang
            for other, t in s["tracks"].items():  # bản gốc đổi → bản dịch cũ không còn khớp
                if other != lang and t.get("kind") == "translation":
                    t["stale"] = True
        elif not s["sourceLang"]:
            raise _bad("Cần có bản gốc (transcript) trước khi lưu bản dịch")
        s["tracks"][lang] = track
        return s

    if type == "delete-track":
        s["tracks"].pop(str(payload.get("lang")), None)
        if s["sourceLang"] not in s["tracks"]:
            s["sourceLang"] = None
        return s

    if type == "set-glossary":
        g = payload.get("glossary")
        if not isinstance(g, list) or len(g) > 500:
            raise _bad("glossary phải là mảng (tối đa 500 mục)")
        s["glossary"] = [{"src": str(x.get("src", "")).strip(), "dst": str(x.get("dst", "")).strip()}
                         for x in g if isinstance(x, dict) and str(x.get("src", "")).strip()]
        return s

    if type == "set-options":
        opts = payload.get("options")
        if not isinstance(opts, dict) or set(opts) - ALLOWED_OPTIONS:
            raise _bad("options không hợp lệ")
        s["options"].update(opts)
        return s

    raise _bad(f"Lệnh không hỗ trợ: {type}")
