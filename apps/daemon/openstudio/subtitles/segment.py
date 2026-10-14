"""Từ có mốc thời gian (Whisper) → cue phụ đề tự nhiên, không chồng, không mất từ."""
from __future__ import annotations

from .cues import Cue, make_cue, normalize

STRONG = (".", "?", "!", "…", "。", "？", "！")
SOFT = (",", ";", ":", "，", "；", "：", "—", "-")


def words_to_cues(words: list[dict], *, max_chars: int = 84, max_duration: float = 7.0, gap_break: float = 0.7,
                  min_chars_before_soft: int = 24) -> list[Cue]:
    """words: [{"start","end","word"}]. Quy tắc:
    - ngắt tại dấu kết câu; hoặc khoảng lặng ≥ gap_break
    - nếu vượt max_chars/max_duration thì ngắt tại dấu phẩy gần nhất (nếu đủ dài), không thì tại từ hiện tại.
    Không bao giờ bỏ từ nào."""
    cues: list[Cue] = []
    buf: list[dict] = []

    def text_of(ws: list[dict]) -> str:
        return " ".join(w["word"].strip() for w in ws if w["word"].strip())

    def flush(ws: list[dict]) -> None:
        t = text_of(ws)
        if t:
            cues.append(make_cue(ws[0]["start"], ws[-1]["end"], t))

    for w in words:
        if not w["word"].strip():
            continue
        if buf and w["start"] - buf[-1]["end"] >= gap_break:
            flush(buf)
            buf = []
        buf.append(w)
        too_long = len(text_of(buf)) > max_chars or buf[-1]["end"] - buf[0]["start"] > max_duration
        if too_long and len(buf) > 1:
            # tìm điểm ngắt mềm gần cuối nhất, đủ dài để không tạo cue vụn
            cut = None
            for i in range(len(buf) - 2, -1, -1):
                if buf[i]["word"].strip().endswith(SOFT + STRONG) and len(text_of(buf[: i + 1])) >= min_chars_before_soft:
                    cut = i + 1
                    break
            if cut is None:
                cut = len(buf) - 1
            flush(buf[:cut])
            buf = buf[cut:]
        elif buf[-1]["word"].strip().endswith(STRONG):
            flush(buf)
            buf = []
    if buf:
        flush(buf)
    return normalize(cues)
