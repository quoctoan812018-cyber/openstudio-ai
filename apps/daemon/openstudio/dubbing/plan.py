"""Lập kế hoạch lồng tiếng: gộp cue thành câu, tính khung thời gian, quyết định tăng tốc/rút gọn, tính vị trí đặt giọng."""
from __future__ import annotations

from ..subtitles.cues import Cue

STRONG = (".", "?", "!", "…", "。", "？", "！")
HARD_MAX_SPEED = 1.6  # trần tuyệt đối khi đã hết cách rút gọn


def build_items(target: list[Cue], source: list[Cue] | None, *, total: float | None = None, min_gap: float = 0.08,
                slack: float = 0.8, join_gap: float = 0.6, max_group: float = 14.0, max_chars: int = 220) -> list[dict]:
    """Gộp các cue liền nhau chưa kết thúc câu thành một "câu lồng tiếng" (đọc liền mạch tự nhiên hơn)."""
    groups: list[list[Cue]] = []
    for c in sorted(target, key=lambda c: c["start"]):
        if not c["text"].strip():
            continue
        g = groups[-1] if groups else None
        if (g and not g[-1]["text"].rstrip().endswith(STRONG) and c["start"] - g[-1]["end"] < join_gap
                and c["end"] - g[0]["start"] <= max_group and sum(len(x["text"]) + 1 for x in g) + len(c["text"]) <= max_chars):
            g.append(c)
        else:
            groups.append([c])
    items: list[dict] = []
    for i, g in enumerate(groups):
        start, end = g[0]["start"], g[-1]["end"]
        nxt = groups[i + 1][0]["start"] if i + 1 < len(groups) else (total if total is not None else end + slack + min_gap)
        cap = min(nxt - min_gap, end + slack)
        cap = max(cap, end)
        src = ""
        if source:
            src = " ".join(s["text"] for s in source if start - 0.05 <= (s["start"] + s["end"]) / 2 <= end + 0.05)
        items.append({"id": f"d{i + 1:04d}", "start": round(start, 3), "end": round(end, 3), "slot": round(max(cap - start, 0.3), 3),
                      "srcText": src, "text": " ".join(c["text"].strip() for c in g), "voice": None, "status": "pending",
                      "speed": 1.0, "duration": None, "finalDuration": None, "audio": None, "shortened": False, "note": None})
    return items


def fit_decision(duration: float, slot: float, max_speed: float) -> tuple[float, str]:
    """Trả về (tempo cần áp dụng, trạng thái). tempo>1 = nhanh hơn."""
    if duration <= slot * 1.02:
        return 1.0, "ok"
    tempo = duration / slot
    if tempo <= max_speed:
        return round(tempo, 4), "sped"
    return round(min(tempo, HARD_MAX_SPEED), 4), "too_long"


def target_chars(text: str, duration: float, slot: float, max_speed: float) -> int:
    """Số ký tự mục tiêu để câu rút gọn đọc vừa khung ở tốc độ tối đa cho phép (chừa 5%)."""
    return max(8, int(len(text) * (slot * max_speed * 0.95) / max(duration, 0.01)))


def compute_starts(items: list[dict], min_gap: float = 0.08, max_push: float = 1.0) -> list[dict]:
    """Vị trí đặt từng đoạn giọng. Đoạn trước dài lấn sang thì đẩy đoạn sau lùi (tối đa max_push) để không chồng tiếng."""
    out, cur_end = [], float("-inf")
    for it in items:
        dur = it.get("finalDuration")
        if not it.get("audio") or dur is None:
            out.append({"id": it["id"], "start": it["start"], "end": it["start"], "pushed": 0.0, "skipped": True})
            continue
        start = max(it["start"], cur_end + min_gap)
        push = min(start - it["start"], max_push)
        start = it["start"] + push
        end = start + dur
        out.append({"id": it["id"], "start": round(start, 3), "end": round(end, 3), "pushed": round(push, 3), "skipped": False})
        cur_end = end
    return out
