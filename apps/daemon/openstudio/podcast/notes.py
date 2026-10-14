"""Chương (chapters), show notes, metadata chương cho ffmpeg."""
from __future__ import annotations

import re
import unicodedata


def clock(t: float) -> str:
    s = int(round(t))
    return f"{s // 3600}:{s // 60 % 60:02}:{s % 60:02}" if s >= 3600 else f"{s // 60:02}:{s % 60:02}"


def slugify(text: str, fallback: str = "podcast") -> str:
    t = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:60] or fallback


def chapters_txt(chapters: list[dict]) -> str:
    """Định dạng mô tả YouTube: dòng đầu phải là 00:00."""
    return "\n".join(f"{clock(c['start'])} {c['title']}" for c in chapters) + "\n"


def ffmetadata(chapters: list[dict], total: float, title: str, comment: str | None = None) -> str:
    def esc(s: str) -> str:
        return re.sub(r"([=;#\\\n])", r"\\\1", s)
    lines = [";FFMETADATA1", f"title={esc(title)}"]
    if comment:
        lines.append(f"comment={esc(comment)}")
    for i, c in enumerate(chapters):
        end = chapters[i + 1]["start"] if i + 1 < len(chapters) else total
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(c['start'] * 1000)}", f"END={int(max(end, c['start'] + 1) * 1000)}", f"title={esc(c['title'])}"]
    return "\n".join(lines) + "\n"


def show_notes(script: dict, chapters: list[dict], duration: float, hosts: list[str], source_name: str | None) -> str:
    out = [f"# {script.get('title') or 'Podcast'}", ""]
    if script.get("summary"):
        out += [script["summary"], ""]
    out += [f"**Thời lượng:** {clock(duration)} · **Người dẫn:** {', '.join(hosts)}", "", "## Chương", ""]
    out += [f"- `{clock(c['start'])}` {c['title']}" for c in chapters]
    if script.get("takeaways"):
        out += ["", "## Ý chính", ""] + [f"- {t}" for t in script["takeaways"]]
    if source_name:
        out += ["", "## Nguồn", "", f"- {source_name}"]
    out += ["", "## Kịch bản", ""]
    for sec in script.get("sections", []):
        out += [f"### {sec['title']}", ""] + [f"**{t['speaker']}:** {t['text']}" for t in sec["turns"]] + [""]
    out += ["---", "_Nội dung giọng nói được tạo bởi AI (OpenStudio AI)._"]
    return "\n".join(out) + "\n"
