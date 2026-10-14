"""State machine công cụ Podcast."""
from __future__ import annotations

import copy

from ..errors import ApiError

TOOL = "podcast"
DEFAULT_BRIEF = {"topic": "", "sourceText": "", "sourceName": None, "language": "vi", "minutes": 3, "style": "thân thiện, dễ hiểu",
                 "hosts": [{"name": "Minh", "voice": None}, {"name": "Lan", "voice": None}]}
DEFAULT_MUSIC = {"intro": None, "outro": None, "bed": None, "bedGain": -22.0}
DEFAULT_OPTIONS = {"format": "mp3", "video": True, "layout": "horizontal", "gap": 0.35, "speed": 1.0}
MAX_SOURCE = 200_000


def initial_state() -> dict:
    return {"brief": copy.deepcopy(DEFAULT_BRIEF), "script": None, "music": dict(DEFAULT_MUSIC), "options": dict(DEFAULT_OPTIONS), "result": None}


def _bad(msg: str) -> ApiError:
    return ApiError(400, "VALIDATION_FAILED", msg)


def validate_script(script: object, hosts: list[str]) -> dict:
    if not isinstance(script, dict) or not isinstance(script.get("sections"), list) or not script["sections"]:
        raise _bad("Kịch bản cần có ít nhất một chương")
    names = {h.lower(): h for h in hosts}
    out_sections, turns_n = [], 0
    for sec in script["sections"]:
        title = str(sec.get("title", "")).strip()[:120] if isinstance(sec, dict) else ""
        if not title or not isinstance(sec.get("turns"), list):
            raise _bad("Mỗi chương cần có tiêu đề và danh sách lượt nói")
        turns = []
        for t in sec["turns"]:
            sp, text = str(t.get("speaker", "")).strip(), str(t.get("text", "")).strip()
            if sp.lower() not in names:
                raise _bad(f"Người nói '{sp}' không nằm trong danh sách người dẫn")
            if not text or len(text) > 1500:
                raise _bad("Mỗi lượt nói phải dài 1–1500 ký tự")
            turns.append({"speaker": names[sp.lower()], "text": text})
        turns_n += len(turns)
        if turns:
            out_sections.append({"title": title, "turns": turns})
    if not out_sections or turns_n > 800:
        raise _bad("Kịch bản rỗng hoặc quá dài (tối đa 800 lượt nói)")
    return {"title": str(script.get("title", "")).strip()[:160], "summary": str(script.get("summary", "")).strip()[:1500],
            "takeaways": [str(x).strip()[:300] for x in (script.get("takeaways") or [])][:10], "sections": out_sections}


def reducer(state: dict, type: str, payload: dict) -> dict:
    s = copy.deepcopy(state) or initial_state()
    for k, v in initial_state().items():
        s.setdefault(k, v)

    if type == "set-brief":
        b = payload.get("brief")
        if not isinstance(b, dict) or set(b) - set(DEFAULT_BRIEF):
            raise _bad("brief không hợp lệ")
        merged = {**s["brief"], **b}
        if not isinstance(merged["topic"], str) or len(merged["topic"]) > 2000:
            raise _bad("Chủ đề tối đa 2000 ký tự")
        if not isinstance(merged["sourceText"], str) or len(merged["sourceText"]) > MAX_SOURCE:
            raise _bad(f"Tài liệu nguồn tối đa {MAX_SOURCE} ký tự")
        if not (1 <= int(merged["minutes"]) <= 30):
            raise _bad("Thời lượng 1–30 phút")
        hosts = merged["hosts"]
        names = [str(h.get("name", "")).strip() for h in hosts] if isinstance(hosts, list) else []
        if not (2 <= len(names) <= 3) or any(not n or len(n) > 30 for n in names) or len({n.lower() for n in names}) != len(names):
            raise _bad("Cần 2–3 người dẫn, tên khác nhau, mỗi tên tối đa 30 ký tự")
        merged["hosts"] = [{"name": n, "voice": (h.get("voice") or None)} for n, h in zip(names, hosts)]
        merged["language"] = str(merged["language"])[:8]
        merged["style"] = str(merged["style"])[:200]
        if merged != s["brief"] and s["script"]:
            s["script"] = s["script"]  # giữ kịch bản cũ; người dùng tự quyết định tạo lại
        s["brief"] = merged
        return s

    if type == "set-script":
        s["script"] = validate_script(payload.get("script"), [h["name"] for h in s["brief"]["hosts"]])
        s["result"] = None
        return s

    if type == "set-music":
        m = payload.get("music")
        if not isinstance(m, dict) or set(m) - set(DEFAULT_MUSIC):
            raise _bad("music không hợp lệ")
        merged = {**s["music"], **m}
        if not (-40.0 <= float(merged["bedGain"]) <= -6.0):
            raise _bad("bedGain phải trong khoảng -40…-6 dB")
        for k in ("intro", "outro", "bed"):
            if merged[k] is not None and not isinstance(merged[k], str):
                raise _bad("Nhạc phải là id hoặc null")
        s["music"] = merged
        return s

    if type == "set-options":
        o = payload.get("options")
        if not isinstance(o, dict) or set(o) - set(DEFAULT_OPTIONS):
            raise _bad("options không hợp lệ")
        merged = {**s["options"], **o}
        if merged["format"] not in ("mp3", "wav") or merged["layout"] not in ("horizontal", "vertical"):
            raise _bad("format/layout không hợp lệ")
        if not (0.0 <= float(merged["gap"]) <= 2.0) or not (0.7 <= float(merged["speed"]) <= 1.5):
            raise _bad("gap 0–2s, speed 0.7–1.5")
        s["options"] = merged
        return s

    if type == "_set-script":
        s["script"], s["result"] = payload["script"], None
        return s

    if type == "_set-result":
        s["result"] = payload.get("result")
        return s

    raise _bad(f"Lệnh không hỗ trợ: {type}")
