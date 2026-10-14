"""Cue phụ đề: chuẩn hoá, ngắt dòng, đọc/ghi SRT · VTT · ASS."""
from __future__ import annotations

import re
from typing import Any

Cue = dict[str, Any]  # {"start": float, "end": float, "text": str}

MIN_DURATION = 0.7
MIN_GAP = 0.02


def make_cue(start: float, end: float, text: str) -> Cue:
    return {"start": round(float(start), 3), "end": round(float(end), 3), "text": text.strip()}


def normalize(cues: list[Cue], min_duration: float = MIN_DURATION) -> list[Cue]:
    """Sắp xếp, bỏ cue rỗng, kéo dài cue quá ngắn nếu còn chỗ, và đảm bảo KHÔNG chồng nhau."""
    out = sorted((make_cue(c["start"], c["end"], c["text"]) for c in cues if str(c.get("text", "")).strip()),
                 key=lambda c: (c["start"], c["end"]))
    for i, c in enumerate(out):
        c["start"] = max(0.0, c["start"])
        nxt = out[i + 1]["start"] if i + 1 < len(out) else None
        if c["end"] - c["start"] < min_duration:
            c["end"] = c["start"] + min_duration
        if nxt is not None and c["end"] > nxt - MIN_GAP:
            c["end"] = max(c["start"] + 0.2, nxt - MIN_GAP)
            if c["end"] > nxt:  # cue sau bắt đầu quá sát → đẩy cue sau
                out[i + 1]["start"] = c["end"] + MIN_GAP
        c["end"] = round(c["end"], 3)
    # bước cuối: bảo đảm start sau ≥ end trước
    for i in range(1, len(out)):
        if out[i]["start"] < out[i - 1]["end"]:
            out[i]["start"] = out[i - 1]["end"]
        if out[i]["end"] <= out[i]["start"]:
            out[i]["end"] = round(out[i]["start"] + 0.2, 3)
    return out


def validate(cues: list[Cue]) -> list[str]:
    """Trả về danh sách lỗi (rỗng = hợp lệ): chồng thời gian, thời gian âm, end<=start, thứ tự."""
    problems: list[str] = []
    for i, c in enumerate(cues):
        if c["start"] < 0:
            problems.append(f"#{i + 1}: thời gian âm")
        if c["end"] <= c["start"]:
            problems.append(f"#{i + 1}: end ≤ start")
        if i and c["start"] < cues[i - 1]["end"] - 1e-6:
            problems.append(f"#{i + 1}: chồng lên cue trước")
    return problems


def wrap_lines(text: str, width: int = 42, max_lines: int = 2) -> str:
    """Ngắt dòng cân bằng theo từ. Quá nhiều dòng thì dồn phần dư vào dòng cuối."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= width:
        return text
    words = text.split(" ")
    if max_lines == 2:
        best, best_diff = None, 10**9
        for i in range(1, len(words)):
            a, b = " ".join(words[:i]), " ".join(words[i:])
            if len(a) <= width and len(b) <= width and abs(len(a) - len(b)) < best_diff:
                best, best_diff = (a, b), abs(len(a) - len(b))
        if best:
            return "\n".join(best)
    lines: list[str] = []
    cur = ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width and len(lines) < max_lines - 1:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    return "\n".join(lines)


# ---------- thời gian ----------
def _split(t: float) -> tuple[int, int, int, int]:
    ms = int(round(max(0.0, t) * 1000))
    return ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000


def fmt_srt(t: float) -> str:
    h, m, s, ms = _split(t)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def fmt_vtt(t: float) -> str:
    h, m, s, ms = _split(t)
    return f"{h:02}:{m:02}:{s:02}.{ms:03}"


def fmt_ass(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}"


_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")


def parse_ts(s: str) -> float:
    m = _TS.fullmatch(s.strip())
    if not m:
        raise ValueError(f"Thời gian không hợp lệ: {s!r}")
    h, mi, se, ms = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(se) + int(ms.ljust(3, "0")) / 1000


# ---------- định dạng ----------
def _text(c: Cue, width: int, wrap: bool) -> str:
    return wrap_lines(c["text"], width) if wrap else c["text"]


def to_srt(cues: list[Cue], width: int = 42, wrap: bool = True) -> str:
    return "".join(
        f"{i}\n{fmt_srt(c['start'])} --> {fmt_srt(c['end'])}\n{_text(c, width, wrap)}\n\n"
        for i, c in enumerate(cues, 1))


def to_vtt(cues: list[Cue], width: int = 42, wrap: bool = True) -> str:
    return "WEBVTT\n\n" + "".join(
        f"{fmt_vtt(c['start'])} --> {fmt_vtt(c['end'])}\n{_text(c, width, wrap)}\n\n" for c in cues)


def parse_subtitle(text: str) -> list[Cue]:
    """Đọc SRT hoặc VTT."""
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for block in re.split(r"\n{2,}", text.strip()):
        lines = [l for l in block.split("\n")]
        idx = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if idx is None:
            continue
        a, _, b = lines[idx].partition("-->")
        try:
            start, end = parse_ts(a), parse_ts(b.strip().split(" ")[0])
        except ValueError:
            continue
        body = " ".join(l.strip() for l in lines[idx + 1:] if l.strip())
        if body:
            cues.append(make_cue(start, end, body))
    return cues


def ass_escape(text: str) -> str:
    return text.replace("\\", "＼").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def to_ass(cues: list[Cue], second: list[Cue] | None = None, *, width: int = 1920, height: int = 1080,
           font: str = "Arial", size: int | None = None, margin_v: int | None = None, wrap_chars: int = 42,
           order: str = "primary-top", hook: str | None = None, hook_seconds: float = 3.5,
           hook_align: int = 8, hook_fade: bool = True) -> str:
    """ASS. `second` (cùng số cue, cùng thời gian) → phụ đề song ngữ, hai style khác nhau."""
    # khung dọc hẹp (1080 rộng): chữ 5% chiều cao (96px) làm libass tự ngắt thêm dòng → dùng 3.6% (≈69px) cho ~26 ký tự/dòng
    size = size or round(height * (0.036 if height > width else 0.05))
    size2 = round(size * 0.78)
    margin_v = margin_v if margin_v is not None else round(height * 0.06)
    head = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {width}\nPlayResY: {height}\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,"
        f"{max(2, size // 16)},0,2,{round(width * 0.04)},{round(width * 0.04)},{margin_v},1\n"
        f"Style: Second,{font},{size2},&H0000E5FF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,"
        f"{max(2, size2 // 16)},0,2,{round(width * 0.04)},{round(width * 0.04)},{margin_v},1\n"
        f"Style: Hook,{font},{round(size * 1.1)},&H0000E5FF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,"
        f"{max(4, size // 12)},{max(2, size // 24)},8,{round(width * 0.06)},{round(width * 0.06)},{round(height * 0.08)},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    for i, c in enumerate(cues):
        main = ass_escape(wrap_lines(c["text"], wrap_chars))
        text = main
        if second is not None and i < len(second):
            sec = ass_escape(wrap_lines(second[i]["text"], wrap_chars))
            top, bottom = (main, sec) if order == "primary-top" else (sec, main)
            top_style, bottom_style = ("Default", "Second") if order == "primary-top" else ("Second", "Default")
            text = f"{{\\r{top_style}}}{top}\\N{{\\r{bottom_style}}}{bottom}"
        lines.append(f"Dialogue: 0,{fmt_ass(c['start'])},{fmt_ass(c['end'])},Default,,0,0,0,,{text}")
    if hook and hook.strip():  # tiêu đề giật tít ở đầu clip (3.5s đầu), căn giữa phía trên
        tag = f"{{\\an{hook_align}" + ("\\fad(150,300)" if hook_fade else "") + "}"
        lines.append(f"Dialogue: 1,{fmt_ass(0)},{fmt_ass(hook_seconds)},Hook,,0,0,0,,{tag}"
                     + ass_escape(wrap_lines(hook.strip(), max(14, wrap_chars - 6), max_lines=3)))
    return head + "\n".join(lines) + "\n"
