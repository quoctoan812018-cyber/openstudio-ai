"""Tìm đoạn hay: dựng cửa sổ ứng viên từ transcript, chấm điểm (heuristic + LLM), chọn N đoạn không chồng nhau."""
from __future__ import annotations

import re

from ..subtitles.cues import Cue

STRONG = (".", "?", "!", "…", "。", "？", "！")
MAX_WINDOWS = 120

HOOK_WORDS = (
    "bí mật", "tại sao", "vì sao", "đừng", "sai lầm", "bất ngờ", "điều quan trọng", "quan trọng nhất", "thật ra", "sự thật",
    "mẹo", "cách để", "không ai", "ít người", "nổi tiếng", "đầu tiên", "lớn nhất", "đặc biệt",
    "secret", "why", "mistake", "never", "truth", "surprising", "most important", "how to", "nobody", "biggest", "first",
)
FILLER_START = (
    "xin chào", "chào các bạn", "chào mừng", "hôm nay chúng ta", "cảm ơn", "hẹn gặp lại", "đăng ký", "theo dõi kênh",
    "hello", "hi everyone", "welcome", "thanks for watching", "subscribe", "see you",
)


def to_sentences(cues: list[Cue]) -> list[Cue]:
    """Gộp cue liền nhau thành câu (kết thúc bằng dấu chấm/hỏi/than hoặc có khoảng lặng ≥ 0.8s)."""
    out: list[Cue] = []
    cur: Cue | None = None
    for c in sorted(cues, key=lambda c: c["start"]):
        if not c["text"].strip():
            continue
        if cur is None:
            cur = dict(c)
        elif c["start"] - cur["end"] < 0.8 and not cur["text"].rstrip().endswith(STRONG):
            cur["end"], cur["text"] = c["end"], f"{cur['text'].rstrip()} {c['text'].strip()}"
        else:
            out.append(cur)
            cur = dict(c)
    if cur:
        out.append(cur)
    return out


def snap(t: float, points: list[float], tol: float) -> float:
    near = [p for p in points if abs(p - t) <= tol]
    return min(near, key=lambda p: abs(p - t)) if near else t


def build_windows(cues: list[Cue], *, min_len: float, max_len: float, scenes: list[float] | None = None,
                  duration: float | None = None) -> list[dict]:
    """Cửa sổ ứng viên bắt đầu/kết thúc đúng biên câu. Biên được dời ra ngoài tới mốc đổi cảnh gần nhất (≤1.5s)
    nhưng chỉ khi khoảng dời không chứa lời nói (không cắt cụt câu)."""
    sents = to_sentences(cues)
    if not sents:
        return []
    target = (min_len + max_len) / 2
    stride = max(1, len(sents) // 60)
    raw: dict[tuple[int, int], tuple[float, float]] = {}
    for i in range(0, len(sents), stride):
        for goal in (min_len, target):
            j = i
            while j < len(sents) - 1 and sents[j]["end"] - sents[i]["start"] < goal:
                j += 1
            dur = sents[j]["end"] - sents[i]["start"]
            if min_len * 0.9 <= dur <= max_len:
                raw[(i, j)] = (sents[i]["start"], sents[j]["end"])
    windows = []
    for (i, j), (a, b) in sorted(raw.items(), key=lambda kv: kv[1])[:MAX_WINDOWS * 3]:
        start, end = a, b
        if scenes:
            prev_end = sents[i - 1]["end"] if i > 0 else 0.0
            next_start = sents[j + 1]["start"] if j + 1 < len(sents) else (duration if duration else b + 1.5)
            s2 = snap(a, [p for p in scenes if p <= a and p >= prev_end], 1.5)
            e2 = snap(b, [p for p in scenes if p >= b and p <= next_start], 1.5)
            if e2 - s2 <= max_len:
                start, end = s2, e2
        text = " ".join(s["text"].strip() for s in sents[i: j + 1])
        windows.append({"id": len(windows), "start": round(start, 3), "end": round(end, 3), "text": text, "sentences": j - i + 1})
    if len(windows) > MAX_WINDOWS:  # video rất dài: giữ đều theo thời gian
        step = len(windows) / MAX_WINDOWS
        windows = [windows[int(k * step)] for k in range(MAX_WINDOWS)]
        for k, w in enumerate(windows):
            w["id"] = k
    return windows


def heuristic_score(text: str, dur: float) -> float:
    """Điểm 0–10 không cần LLM: mật độ lời nói, câu hỏi/cảm thán, con số, từ khoá gây tò mò; trừ điểm mở đầu/kết thúc sáo rỗng."""
    t = text.lower()
    words = len(re.findall(r"\w+", t))
    wps = words / max(dur, 1.0)
    score = 3.0
    score += 2.0 if 1.6 <= wps <= 3.8 else (0.5 if wps >= 1.0 else -1.0)
    score += min(2.0, 0.7 * (t.count("?") + t.count("!")))
    score += min(1.0, 0.35 * len(re.findall(r"\d+", t)))
    score += min(2.0, 1.0 * sum(1 for w in HOOK_WORDS if w in t))
    head = t[:90]
    if any(f in head for f in FILLER_START):
        score -= 2.5
    if any(f in t[-120:] for f in ("hẹn gặp lại", "cảm ơn các bạn", "thanks for watching", "see you")):
        score -= 1.5
    return round(max(0.0, min(10.0, score)), 2)


def select_clips(windows: list[dict], count: int, min_gap: float = 3.0, chosen: list[dict] | None = None) -> list[dict]:
    """Chọn tham lam theo điểm giảm dần, không chồng nhau và cách nhau ≥ min_gap; trả về theo thứ tự thời gian.
    `chosen`: các đoạn đã chọn trước (đoạn mới phải tránh chúng và chúng được tính vào `count`)."""
    out = list(chosen or [])
    for w in sorted(windows, key=lambda w: (-w["score"], w["start"])):
        if len(out) >= count:
            break
        if all(w["end"] + min_gap <= c["start"] or w["start"] >= c["end"] + min_gap for c in out):
            out.append(w)
    return sorted(out, key=lambda w: w["start"])


def clip_cues(cues: list[Cue], start: float, end: float) -> list[Cue]:
    """Phụ đề của một clip: cue giao với [start,end], cắt ở biên và dời gốc về 0."""
    out = []
    for c in cues:
        a, b = max(c["start"], start), min(c["end"], end)
        if b - a >= 0.15 and c["text"].strip():
            out.append({"start": round(a - start, 3), "end": round(b - start, 3), "text": c["text"]})
    return out
