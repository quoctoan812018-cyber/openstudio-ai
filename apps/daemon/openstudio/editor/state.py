"""State machine công cụ Chỉnh sửa video: dòng thời gian một track hình + chữ + ảnh/video chèn + nhạc nền.

Mô hình cố ý đơn giản (đủ cho cắt/ghép/chữ/ảnh chèn/nhạc/chuyển cảnh/tốc độ): các đoạn (`segments`) nối tiếp nhau trên track chính;
chữ (`texts`) và lớp chèn (`overlays`) đặt theo giây trên dòng thời gian KẾT QUẢ; nhạc nền chạy suốt dòng thời gian."""
from __future__ import annotations

import copy
import re
import uuid

from ..errors import ApiError

TOOL = "editor"
ASPECTS = {"16:9": (16, 9), "9:16": (9, 16), "1:1": (1, 1)}
TRANSITIONS = ("none", "fade", "dissolve", "wipeleft", "wiperight", "slideleft", "slideright")
POSITIONS = ("top", "center", "bottom")
DEFAULT_SETTINGS = {"aspect": "16:9", "quality": 720, "fps": 25, "fit": "pad"}
DEFAULT_MUSIC = {"asset": None, "volumeDb": -18.0, "duck": True, "fadeOut": 2.0}
MAX_SEGMENTS, MAX_TEXTS, MAX_OVERLAYS = 200, 200, 50
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def initial_state() -> dict:
    return {"settings": dict(DEFAULT_SETTINGS), "segments": [], "texts": [], "overlays": [], "music": dict(DEFAULT_MUSIC),
            "result": None, "preview": None}


def _bad(msg: str) -> ApiError:
    return ApiError(400, "VALIDATION_FAILED", msg)


def _id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:6]


def _num(v: object, lo: float, hi: float, name: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not (lo <= float(v) <= hi):
        raise _bad(f"{name} phải là số trong khoảng {lo}–{hi}")
    return float(v)


def seg_duration(s: dict) -> float:
    """Độ dài đoạn trên dòng thời gian kết quả."""
    return (s["out"] - s["in"]) / s["speed"] if s["kind"] == "video" else s["duration"]


def timeline_duration(segments: list[dict]) -> float:
    total = 0.0
    for i, s in enumerate(segments):
        d = seg_duration(s)
        t = s["transition"]["duration"] if i > 0 and s["transition"]["type"] != "none" else 0.0
        total += d - t
    return max(0.0, total)


def clamp_transitions(segments: list[dict]) -> None:
    """Chuyển cảnh không được dài hơn nửa đoạn ngắn hơn trong cặp."""
    for i, s in enumerate(segments):
        if i == 0 or s["transition"]["type"] == "none":
            s["transition"] = {"type": "none" if i == 0 else s["transition"]["type"], "duration": 0.0 if i == 0 else s["transition"]["duration"]}
            continue
        cap = round(min(seg_duration(segments[i - 1]), seg_duration(s)) / 2, 3)
        s["transition"]["duration"] = round(min(s["transition"]["duration"], cap), 3)
        if s["transition"]["duration"] < 0.05:
            s["transition"] = {"type": "none", "duration": 0.0}


def _transition(t: object) -> dict:
    if t is None:
        return {"type": "none", "duration": 0.0}
    if not isinstance(t, dict) or t.get("type") not in TRANSITIONS:
        raise _bad("Chuyển cảnh phải là một trong: " + ", ".join(TRANSITIONS))
    if t["type"] == "none":
        return {"type": "none", "duration": 0.0}
    return {"type": t["type"], "duration": _num(t.get("duration", 0.5), 0.1, 3.0, "Thời lượng chuyển cảnh")}


def _check_range(seg: dict) -> None:
    if seg["kind"] == "video":
        if not (0 <= seg["in"] < seg["out"] <= seg["srcDuration"] + 0.05):
            raise _bad(f"Đoạn phải thoả 0 ≤ in < out ≤ {seg['srcDuration']:.2f}s")
        seg["out"] = min(seg["out"], seg["srcDuration"])
        if seg_duration(seg) < 0.2:
            raise _bad("Đoạn quá ngắn (tối thiểu 0,2 giây sau khi áp tốc độ)")


def _check_text(t: dict) -> dict:
    text = str(t.get("text", "")).strip()
    if not text or len(text) > 500:
        raise _bad("Chữ phải dài 1–500 ký tự")
    start, end = _num(t.get("start"), 0, 86400, "start"), _num(t.get("end"), 0, 86400, "end")
    if end <= start:
        raise _bad("end phải lớn hơn start")
    pos = t.get("position", "bottom")
    if pos not in POSITIONS:
        raise _bad("position phải là top, center hoặc bottom")
    color = t.get("color", "#FFFFFF")
    if not isinstance(color, str) or not COLOR.match(color):
        raise _bad("Màu phải dạng #RRGGBB")
    return {"text": text, "start": start, "end": end, "position": pos, "size": _num(t.get("size", 5.0), 2, 15, "size"), "color": color.upper(),
            "bold": bool(t.get("bold", True))}


def _check_overlay(o: dict) -> dict:
    start, end = _num(o.get("start"), 0, 86400, "start"), _num(o.get("end"), 0, 86400, "end")
    if end <= start:
        raise _bad("end phải lớn hơn start")
    return {"start": start, "end": end, "x": _num(o.get("x", 0.05), 0, 1, "x"), "y": _num(o.get("y", 0.05), 0, 1, "y"),
            "width": _num(o.get("width", 0.25), 0.02, 1, "width")}


def reducer(state: dict, type: str, payload: dict) -> dict:
    s = copy.deepcopy(state) or initial_state()
    for k, v in initial_state().items():
        s.setdefault(k, v)

    def seg(sid: object) -> dict:
        found = next((x for x in s["segments"] if x["id"] == sid), None)
        if not found:
            raise ApiError(404, "SEGMENT_NOT_FOUND", "Không có đoạn này")
        return found

    def touched() -> dict:
        clamp_transitions(s["segments"])
        s["result"], s["preview"] = None, None
        return s

    if type == "set-settings":
        o = payload.get("settings")
        if not isinstance(o, dict) or set(o) - set(DEFAULT_SETTINGS):
            raise _bad("settings không hợp lệ")
        m = {**s["settings"], **o}
        if m["aspect"] not in ASPECTS or m["quality"] not in (480, 720, 1080) or m["fps"] not in (24, 25, 30) or m["fit"] not in ("pad", "crop"):
            raise _bad("aspect: 16:9/9:16/1:1 · quality: 480/720/1080 · fps: 24/25/30 · fit: pad/crop")
        s["settings"] = m
        return touched()

    if type == "_add-segment":                                    # do service dựng từ tài nguyên đã dò
        if len(s["segments"]) >= MAX_SEGMENTS:
            raise _bad(f"Tối đa {MAX_SEGMENTS} đoạn")
        p = payload
        item = {"id": _id("s"), "asset": p["asset"], "kind": p["kind"], "name": p.get("name", ""), "srcDuration": float(p["srcDuration"]),
                "hasAudio": bool(p["hasAudio"]), "in": float(p.get("in", 0.0)), "out": float(p.get("out") or p["srcDuration"]),
                "duration": float(p.get("duration", 5.0)), "speed": 1.0, "volume": 100, "transition": _transition(p.get("transition"))}
        if item["kind"] == "image":
            item["duration"] = _num(item["duration"], 0.5, 600, "duration")
        else:
            _check_range(item)
        idx = payload.get("index")
        s["segments"].insert(idx if isinstance(idx, int) and 0 <= idx <= len(s["segments"]) else len(s["segments"]), item)
        return touched()

    if type == "update-segment":
        x = seg(payload.get("id"))
        for k in ("in", "out", "duration", "speed", "volume", "transition"):
            if k not in payload:
                continue
            if k in ("in", "out"):
                if x["kind"] != "video":
                    raise _bad("Ảnh không có in/out; dùng duration")
                x[k] = _num(payload[k], 0, 86400, k)
            elif k == "duration":
                if x["kind"] != "image":
                    raise _bad("Video dùng in/out")
                x[k] = _num(payload[k], 0.5, 600, k)
            elif k == "speed":
                if x["kind"] != "video":
                    raise _bad("Chỉ video mới đổi tốc độ")
                x[k] = _num(payload[k], 0.25, 4.0, "speed")
            elif k == "volume":
                x[k] = int(_num(payload[k], 0, 200, "volume"))
            else:
                x[k] = _transition(payload[k])
        _check_range(x)
        return touched()

    if type == "remove-segment":
        x = seg(payload.get("id"))
        s["segments"].remove(x)
        return touched()

    if type == "move-segment":
        x = seg(payload.get("id"))
        idx = payload.get("index")
        if not isinstance(idx, int) or not (0 <= idx < len(s["segments"])):
            raise _bad("index không hợp lệ")
        s["segments"].remove(x)
        s["segments"].insert(idx, x)
        return touched()

    if type == "split-segment":
        x = seg(payload.get("id"))
        if x["kind"] != "video":
            raise _bad("Chỉ cắt đôi được đoạn video")
        at = _num(payload.get("at"), 0, 86400, "at")            # giây TRÊN NGUỒN
        if not (x["in"] + 0.2 * x["speed"] <= at <= x["out"] - 0.2 * x["speed"]):
            raise _bad("Điểm cắt phải nằm trong đoạn, cách hai đầu ≥ 0,2 giây")
        i = s["segments"].index(x)
        second = {**copy.deepcopy(x), "id": _id("s"), "in": at, "transition": {"type": "none", "duration": 0.0}}
        x["out"] = at
        s["segments"].insert(i + 1, second)
        return touched()

    if type == "add-text":
        if len(s["texts"]) >= MAX_TEXTS:
            raise _bad(f"Tối đa {MAX_TEXTS} chữ")
        s["texts"].append({"id": _id("t"), **_check_text(payload)})
        s["result"], s["preview"] = None, None
        return s

    if type == "update-text":
        t = next((x for x in s["texts"] if x["id"] == payload.get("id")), None)
        if not t:
            raise ApiError(404, "TEXT_NOT_FOUND", "Không có chữ này")
        t.update(_check_text({**t, **{k: v for k, v in payload.items() if k != "id"}}))
        s["result"], s["preview"] = None, None
        return s

    if type == "remove-text":
        n = len(s["texts"])
        s["texts"] = [x for x in s["texts"] if x["id"] != payload.get("id")]
        if len(s["texts"]) == n:
            raise ApiError(404, "TEXT_NOT_FOUND", "Không có chữ này")
        s["result"], s["preview"] = None, None
        return s

    if type == "_add-overlay":
        if len(s["overlays"]) >= MAX_OVERLAYS:
            raise _bad(f"Tối đa {MAX_OVERLAYS} lớp chèn")
        s["overlays"].append({"id": _id("o"), "asset": payload["asset"], "kind": payload["kind"], "name": payload.get("name", ""), **_check_overlay(payload)})
        s["result"], s["preview"] = None, None
        return s

    if type == "update-overlay":
        o = next((x for x in s["overlays"] if x["id"] == payload.get("id")), None)
        if not o:
            raise ApiError(404, "OVERLAY_NOT_FOUND", "Không có lớp chèn này")
        o.update(_check_overlay({**o, **{k: v for k, v in payload.items() if k != "id"}}))
        s["result"], s["preview"] = None, None
        return s

    if type == "remove-overlay":
        n = len(s["overlays"])
        s["overlays"] = [x for x in s["overlays"] if x["id"] != payload.get("id")]
        if len(s["overlays"]) == n:
            raise ApiError(404, "OVERLAY_NOT_FOUND", "Không có lớp chèn này")
        s["result"], s["preview"] = None, None
        return s

    if type == "_set-music":
        s["music"] = {**s["music"], "asset": payload.get("asset"), "name": payload.get("name", "")}
        s["result"], s["preview"] = None, None
        return s

    if type == "set-music":
        m = {**s["music"]}
        if "volumeDb" in payload:
            m["volumeDb"] = _num(payload["volumeDb"], -60, 6, "volumeDb")
        if "duck" in payload:
            m["duck"] = bool(payload["duck"])
        if "fadeOut" in payload:
            m["fadeOut"] = _num(payload["fadeOut"], 0, 10, "fadeOut")
        if payload.get("remove"):
            m["asset"], m["name"] = None, ""
        s["music"] = m
        s["result"], s["preview"] = None, None
        return s

    if type == "apply-template":
        t = payload.get("template")
        if not isinstance(t, dict):
            raise _bad("template không hợp lệ")
        if isinstance(t.get("settings"), dict):
            s = reducer(s, "set-settings", {"settings": {k: v for k, v in t["settings"].items() if k in DEFAULT_SETTINGS}})
        if isinstance(t.get("music"), dict):
            s["music"] = {**s["music"], **{k: v for k, v in t["music"].items() if k in ("volumeDb", "duck", "fadeOut")}}
        return touched()

    if type == "_set-result":
        key = "preview" if payload.get("preview") else "result"
        s[key] = payload.get("file")
        return s

    raise _bad(f"Lệnh không hỗ trợ: {type}")
