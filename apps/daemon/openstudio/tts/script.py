"""Phân tích kịch bản đọc: nhiều người nói ([Người A]), ngắt nghỉ ([nghỉ 1s]), thẻ cảm xúc của VieNeu ([cười])."""
from __future__ import annotations

import re
from dataclasses import dataclass

# Thẻ cảm xúc/âm thanh mà VieNeu hiểu — giữ nguyên trong văn bản, KHÔNG phải tên người nói.
EMOTION_TAGS = {"cười", "thở dài", "hắng giọng", "ho", "khóc", "thì thầm"}
PAUSE_WORDS = ("nghỉ", "pause", "im lặng", "silence")
DEFAULT_SPEAKER = "default"

_PAUSE = re.compile(r"\[\s*(?:" + "|".join(PAUSE_WORDS) + r")\s+([0-9]+(?:[.,][0-9]+)?)\s*(ms|s|giây)?\s*\]", re.I)
_LINE_TAG = re.compile(r"^\s*\[([^\]\n]{1,40})\]\s*(.*)$")
MAX_PAUSE = 10.0


@dataclass
class Segment:
    speaker: str
    text: str = ""
    pause_after: float = 0.0  # giây, do người dùng chỉ định ([nghỉ 1s]); 0 = dùng khoảng nghỉ mặc định

    @property
    def is_pause(self) -> bool:
        return not self.text.strip()


def _pause_seconds(value: str, unit: str | None) -> float:
    v = float(value.replace(",", "."))
    if (unit or "s").lower() == "ms":
        v /= 1000
    return min(max(v, 0.0), MAX_PAUSE)


def _is_speaker_tag(tag: str) -> bool:
    t = tag.strip().lower()
    return t not in EMOTION_TAGS and not any(re.match(rf"^{w}\b", t) for w in PAUSE_WORDS)


def parse_script(text: str) -> list[Segment]:
    """Mỗi dòng không rỗng là một đoạn. Dòng bắt đầu bằng [Tên] đổi người nói cho tới thẻ tiếp theo.
    Thẻ [nghỉ Ns] đứng riêng một dòng → ngắt nghỉ sau đoạn trước; đứng giữa dòng → tách đoạn."""
    segs: list[Segment] = []
    speaker = DEFAULT_SPEAKER
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = _LINE_TAG.match(line)
        if m and _is_speaker_tag(m.group(1)):
            speaker, line = m.group(1).strip(), m.group(2).strip()
        pos = 0
        for pm in _PAUSE.finditer(line):
            chunk = line[pos:pm.start()].strip()
            secs = _pause_seconds(pm.group(1), pm.group(2))
            if chunk:
                segs.append(Segment(speaker, chunk, secs))
            elif segs:
                segs[-1].pause_after += secs
            else:
                segs.append(Segment(speaker, "", secs))
            pos = pm.end()
        tail = line[pos:].strip()
        if tail:
            segs.append(Segment(speaker, tail))
    return segs


def speakers_of(segs: list[Segment]) -> list[str]:
    seen: list[str] = []
    for s in segs:
        if s.text.strip() and s.speaker not in seen:
            seen.append(s.speaker)
    return seen
