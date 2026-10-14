"""Viết kịch bản hội thoại podcast bằng LLM cục bộ: dàn ý (chương) rồi từng chương lượt nói."""
from __future__ import annotations

import re
from typing import Callable

from ..errors import ApiError
from ..subtitles.llm import LLMClient, lang_name, strip_foreign_script
from .state import validate_script

WORDS_PER_MIN = {"vi": 220}  # tiếng Việt đếm theo âm tiết ~3.7/giây khi TTS đọc; ngôn ngữ khác ~150 từ/phút
# qwen3:4b viết ngắn hơn yêu cầu ~35% (đo thật: xin 440 từ, ra 277) → xin nhiều hơn để tập podcast gần đúng thời lượng
LLM_UNDERSHOOT = 1.35
OUTLINE_SCHEMA = {"type": "object", "properties": {
    "title": {"type": "string"}, "summary": {"type": "string"}, "takeaways": {"type": "array", "items": {"type": "string"}},
    "sections": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}, "points": {"type": "array", "items": {"type": "string"}}},
                                             "required": ["title", "points"]}}},
    "required": ["title", "summary", "takeaways", "sections"]}
TURNS_SCHEMA = {"type": "object", "properties": {"turns": {"type": "array", "items": {"type": "object", "properties": {
    "speaker": {"type": "string"}, "text": {"type": "string"}}, "required": ["speaker", "text"]}}}, "required": ["turns"]}


def n_sections(minutes: int) -> int:
    return max(2, min(6, round(minutes / 1.5)))


def words_for(lang: str, minutes: float) -> int:
    return int(minutes * WORDS_PER_MIN.get(lang.split("-")[0], 150))


def source_excerpt(text: str, limit: int = 6000) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(text) <= limit:
        return text
    a, b, c = limit * 5 // 12, limit // 4, limit // 3
    mid = len(text) // 2
    return f"{text[:a]}\n[…]\n{text[mid - b // 2: mid + b // 2]}\n[…]\n{text[-c:]}"


def clean_turn(text: str, hosts: list[str] | None = None) -> str:
    """Bỏ định dạng markdown và tiền tố "Tên:" (nếu LLM lặp lại tên người nói trong lời)."""
    t = re.sub(r"[*_`#>]+", "", text)
    t = re.sub(r"\s+", " ", t).strip()
    for h in hosts or []:
        t = re.sub(rf"^\(?{re.escape(h)}\)?\s*:\s*", "", t, flags=re.I)
    return t


def generate_script(llm: LLMClient, brief: dict, on_progress: Callable[[int, int, str], None] | None = None) -> dict:
    lang = brief["language"]
    hosts = [h["name"] for h in brief["hosts"]]
    names = ", ".join(hosts)
    minutes = int(brief["minutes"])
    n = n_sections(minutes)
    material = source_excerpt(brief["sourceText"]) if brief.get("sourceText", "").strip() else ""
    topic = brief["topic"].strip() or "(derive the topic from the source material)"
    system = (
        f"You are a podcast producer. Plan an engaging conversational podcast episode in {lang_name(lang)} with {len(hosts)} hosts ({names}), "
        f"about {minutes} minutes long, split into exactly {n} sections. Style: {brief['style']}. "
        "Give a catchy episode title, a 2-3 sentence summary, 3-5 key takeaways and, for each section, a short title and 2-4 talking points. "
        'Reply with ONLY JSON {"title","summary","takeaways":[...],"sections":[{"title","points":[...]}]}.'
    )
    user = f"Topic: {topic}\n" + (f"Source material (stay faithful to it, do not invent facts):\n{material}\n" if material else "")
    outline = None
    for _ in range(2):
        outline = llm.json_object(system, user, OUTLINE_SCHEMA, max_tokens=1200)
        if outline and len(outline.get("sections", [])) >= 1 and str(outline.get("title", "")).strip():
            break
        outline = None
    if not outline:
        raise ApiError(422, "SCRIPT_FAILED", "LLM không lập được dàn ý cho tập podcast. Thử đổi chủ đề hoặc mô hình.")
    sections = outline["sections"][:n]
    words = words_for(lang, minutes) // len(sections)
    result_sections: list[dict] = []
    for i, sec in enumerate(sections):
        if on_progress:
            on_progress(i, len(sections), str(sec["title"]))
        role = ("This is the FIRST section: open with a warm greeting, introduce the hosts and the topic. " if i == 0 else "") + \
               ("This is the LAST section: wrap up with a short recap and a friendly goodbye. " if i == len(sections) - 1 else "")
        tsys = (
            f"You write dialogue for a podcast hosted by {names}. Write natural spoken conversation in {lang_name(lang)}: short turns "
            "(1-3 sentences each), hosts react to each other, ask questions and build on each other's points. No stage directions, no emojis, "
            "no markdown, write numbers the way they are spoken. "
            f"Target about {int(words * LLM_UNDERSHOOT)} words in total for this section. {role}"
            f"Use ONLY these speaker names exactly: {names}. "
            'Reply with ONLY JSON {"turns":[{"speaker":"...","text":"..."}]}.'
        )
        prev = ""
        if result_sections:
            last = result_sections[-1]["turns"][-3:]
            prev = "Previous turns (continue naturally, do not repeat):\n" + "\n".join(f"{t['speaker']}: {t['text']}" for t in last) + "\n"
        tuser = (f"Episode: {outline['title']}\nAll sections: " + " | ".join(str(s["title"]) for s in sections) + "\n"
                 f"Current section: {sec['title']}\nTalking points: " + "; ".join(map(str, sec.get("points", []))) + "\n" + prev
                 + (f"Source material (stay faithful to it):\n{source_excerpt(brief['sourceText'], 3000)}\n" if material else ""))
        turns: list[dict] = []
        for _ in range(2):
            res = llm.json_object(tsys, tuser, TURNS_SCHEMA, max_tokens=min(3000, int(words * 3) + 200))
            turns = []
            for t in (res or {}).get("turns", []):
                text = strip_foreign_script(clean_turn(str(t.get("text", "")), hosts), lang)
                sp = next((h for h in hosts if h.lower() == str(t.get("speaker", "")).strip().lower()), None)
                if text:
                    turns.append({"speaker": sp or hosts[len(turns) % len(hosts)], "text": text[:1200]})
            if len(turns) >= 2:
                break
        if len(turns) < 2:
            raise ApiError(422, "SCRIPT_FAILED", f"LLM không viết được lời thoại cho chương '{sec['title']}'.")
        result_sections.append({"title": str(sec["title"]).strip(), "turns": turns})
    if on_progress:
        on_progress(len(sections), len(sections), "")
    return validate_script({"title": outline["title"], "summary": outline["summary"], "takeaways": outline.get("takeaways", []),
                            "sections": result_sections}, hosts)
