"""LLM cục bộ (Ollama, API tương thích OpenAI): sửa lỗi phụ đề và dịch theo lô, giữ số lượng cue + thuật ngữ."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

import httpx

from ..errors import ApiError
from .cues import Cue, make_cue

LANGS = {
    "vi": "Vietnamese", "en": "English", "zh": "Simplified Chinese", "ja": "Japanese", "ko": "Korean",
    "fr": "French", "de": "German", "es": "Spanish", "pt": "Portuguese", "ru": "Russian", "th": "Thai",
    "id": "Indonesian", "ms": "Malay", "it": "Italian", "tr": "Turkish", "ar": "Arabic", "hi": "Hindi",
}
TONES = {
    "neutral": "natural, neutral register",
    "formal": "formal and polite register (suitable for business, news, official content)",
    "casual": "casual, friendly, conversational register (suitable for vlogs and social media)",
}
_THINK = re.compile(r"<think>.*?</think>", re.S)


_CJK = re.compile("[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯]+")
CJK_LANGS = {"zh", "ja", "ko"}


def strip_foreign_script(text: str, lang: str) -> str:
    """LLM nhỏ (qwen3) thỉnh thoảng chèn chữ Hán/Nhật/Hàn vào câu tiếng khác (vd "người Pháp引入 cây này").
    Bỏ các ký tự đó khi ngôn ngữ đích không dùng chữ CJK, rồi gọn khoảng trắng."""
    if lang.split("-")[0].lower() in CJK_LANGS:
        return text
    return re.sub(r"\s{2,}", " ", _CJK.sub("", text)).strip()


def lang_name(code: str) -> str:
    return LANGS.get(code.split("-")[0].lower(), code)


LINES_SCHEMA = {"type": "object", "properties": {"lines": {"type": "array", "items": {"type": "string"}}},
                "required": ["lines"]}


@dataclass
class LLMClient:
    base_url: str
    model: str
    timeout: float = 600.0
    client_factory: Callable[[], httpx.Client] | None = None
    num_ctx: int = 8192       # Ollama tự chọn 4096 khi không có VRAM → prompt của Agent (tool + skill + lịch sử) sẽ bị cắt cụt; ép 8192
    provider: str = "ollama"  # "ollama": API gốc /api/chat (tắt thinking, ép JSON bằng grammar) · "openai": /chat/completions
    stats: dict = field(default_factory=lambda: {"calls": 0, "fallbacks": 0, "glossary_misses": 0})

    def _client(self) -> httpx.Client:
        return self.client_factory() if self.client_factory else httpx.Client(timeout=self.timeout)

    def status(self) -> dict:
        try:
            with self._client() as c:
                r = c.get(f"{self.base_url}/models", timeout=5)
                r.raise_for_status()
                ids = [m["id"] for m in r.json().get("data", [])]
            return {"available": True, "model": self.model, "model_installed": self.model in ids, "models": ids}
        except Exception as e:  # noqa: BLE001
            return {"available": False, "model": self.model, "model_installed": False, "models": [], "error": str(e)[:200]}

    def unload(self) -> None:
        """Nhả mô hình khỏi RAM (Ollama keep_alive=0) trước các job nặng RAM khác; lỗi thì bỏ qua."""
        if self.provider != "ollama":
            return
        try:
            with self._client() as c:
                c.post(f"{self.base_url.removesuffix('/v1')}/api/generate", json={"model": self.model, "keep_alive": 0}, timeout=10)
        except Exception:  # noqa: BLE001, S110
            pass

    def require(self) -> None:
        s = self.status()
        if not s["available"]:
            raise ApiError(424, "LLM_UNAVAILABLE", "Không kết nối được LLM cục bộ (Ollama). Hãy chạy `ollama serve`.")
        if not s["model_installed"]:
            raise ApiError(424, "LLM_MODEL_MISSING", f"Ollama chưa có mô hình '{self.model}'. Chạy: ollama pull {self.model}",
                           {"model": self.model})

    def chat(self, system: str, user: str, max_tokens: int = 1500, schema: dict | None = None) -> str:
        """Trả về chuỗi JSON dạng {"lines": [...]}. Ollama: ép bằng grammar + think=false (qwen3 hay suy luận dài,
        không ép thì một lô nhỏ cũng có thể sinh hàng nghìn token)."""
        self.stats["calls"] += 1
        messages = [{"role": "system", "content": system + "\n/no_think"}, {"role": "user", "content": user}]
        with self._client() as c:
            if self.provider == "ollama":
                root = self.base_url.removesuffix("/v1")
                r = c.post(f"{root}/api/chat", timeout=self.timeout, json={
                    "model": self.model, "stream": False, "think": False, "format": schema or LINES_SCHEMA, "messages": messages,
                    "options": {"temperature": 0.2, "num_predict": max_tokens, "num_ctx": self.num_ctx}})
                r.raise_for_status()
                content = r.json()["message"]["content"] or ""
            else:
                r = c.post(f"{self.base_url}/chat/completions", timeout=self.timeout, json={
                    "model": self.model, "stream": False, "temperature": 0.2, "max_tokens": max_tokens,
                    "response_format": {"type": "json_schema", "json_schema": {"name": "result", "schema": schema or LINES_SCHEMA, "strict": True}},
                    "messages": messages})
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"] or ""
        return _THINK.sub("", content).strip()

    def json_object(self, system: str, user: str, schema: dict, max_tokens: int = 1500, retries: int = 1) -> dict | None:
        """Gọi LLM ép theo JSON schema và trả về dict; None nếu hỏng sau `retries` lần thử lại."""
        for _ in range(retries + 1):
            try:
                obj = json.loads(self.chat(system, user, max_tokens, schema))
            except (httpx.HTTPError, KeyError, ValueError):
                continue
            if isinstance(obj, dict):
                return obj
        return None


def extract_json_array(text: str) -> list | None:
    """Nhận {"lines":[...]} (chuẩn) hoặc mảng JSON trần nằm lẫn trong văn bản."""
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and isinstance(obj.get("lines"), list):
            return obj["lines"]
    except ValueError:
        pass
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start: end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def _glossary_block(glossary: list[dict] | None) -> str:
    rows = [g for g in (glossary or []) if g.get("src") and g.get("dst")]
    if not rows:
        return ""
    return "Glossary (use EXACTLY these translations when the source term appears):\n" + "\n".join(
        f'- "{g["src"]}" => "{g["dst"]}"' for g in rows) + "\n"


def _ask_batch(llm: LLMClient, system: str, items: list[str], user_prefix: str) -> list[str] | None:
    user = (user_prefix + '\nOutput a JSON object {"lines": [...]} with exactly ' + str(len(items)) + " strings.\n"
            "Input JSON array (" + str(len(items)) + " items):\n" + json.dumps(items, ensure_ascii=False))
    try:
        arr = extract_json_array(llm.chat(system, user))
    except (httpx.HTTPError, KeyError, ValueError):
        return None
    if arr is None or len(arr) != len(items) or not all(isinstance(x, str) for x in arr):
        return None
    return arr


def _batched(llm: LLMClient, system: str, items: list[str], make_prefix: Callable[[int, int], str],
             fallback: Callable[[str], str]) -> list[str]:
    """Hỏi theo lô; lỗi/lệch số lượng thì chia đôi lô, tới từng dòng; vẫn lỗi thì dùng fallback (giữ nguyên)."""
    def go(lo: int, hi: int) -> list[str]:
        chunk = items[lo:hi]
        res = _ask_batch(llm, system, chunk, make_prefix(lo, hi))
        if res is not None:
            return res
        if len(chunk) == 1:
            llm.stats["fallbacks"] += 1
            return [fallback(chunk[0])]
        mid = (lo + hi) // 2
        return go(lo, mid) + go(mid, hi)
    return go(0, len(items))


def polish_cues(llm: LLMClient, cues: list[Cue], *, language: str, glossary: list[dict] | None = None,
                batch: int = 20, on_progress: Callable[[int, int], None] | None = None) -> list[Cue]:
    """Sửa chính tả, dấu thanh, dấu câu, viết hoa, áp dụng thuật ngữ. KHÔNG đổi thời gian, KHÔNG đổi số cue."""
    system = (
        f"You are a subtitle proofreader for {lang_name(language)} speech transcripts. "
        "Fix spelling, diacritics, punctuation and capitalization. Write numbers and proper nouns correctly. "
        "Apply the glossary spellings. Do NOT paraphrase, add, remove or merge content. "
        'Reply with ONLY a JSON object {"lines": [...]}: one string per input item, same length and order.\n'
        + _glossary_block(glossary)
    )
    texts = [c["text"] for c in cues]
    out: list[str] = []
    for lo in range(0, len(texts), batch):
        part = texts[lo: lo + batch]
        fixed = _batched(llm, system, part, lambda _lo, _hi: "Proofread these subtitle lines.", lambda s: s)
        for orig, new in zip(part, fixed):
            ratio = len(new) / max(1, len(orig))
            new = strip_foreign_script(new, language)
            out.append(new.strip() if new.strip() and 0.6 <= ratio <= 1.6 else orig)  # chặn LLM viết lại tuỳ tiện
        if on_progress:
            on_progress(min(lo + batch, len(texts)), len(texts))
    return [make_cue(c["start"], c["end"], t) for c, t in zip(cues, out)]


def translate_cues(llm: LLMClient, cues: list[Cue], *, source: str, target: str, tone: str = "neutral",
                   market: str | None = None, glossary: list[dict] | None = None, batch: int = 16,
                   on_progress: Callable[[int, int], None] | None = None) -> list[Cue]:
    """Dịch từng cue, giữ nguyên thời gian và số cue. Có ngữ cảnh (các dòng đã dịch trước đó)."""
    src_n, dst_n = lang_name(source), lang_name(target)
    system = (
        f"You are a professional subtitle translator from {src_n} to {dst_n}. "
        f"Use a {TONES.get(tone, TONES['neutral'])}. "
        + (f"Localize for the {market} market (idioms, units, currency, forms of address). " if market else "")
        + "Subtitles must be concise and natural to read aloud; keep each translation roughly the same length as the "
          "source line. Translate each input line independently into the matching output line; never merge or split "
          "lines. Keep names, brands and numbers correct. "
          'Reply with ONLY a JSON object {"lines": [...]}: one string per input item, same length and order.\n'
        + _glossary_block(glossary)
    )
    texts = [c["text"] for c in cues]
    translated: list[str] = []
    for lo in range(0, len(texts), batch):
        part = texts[lo: lo + batch]
        ctx = ""
        if translated:
            prev = list(zip(texts[max(0, lo - 3): lo], translated[-3:]))
            ctx = "Context (previous lines, already translated, do NOT include in output):\n" + "\n".join(
                f"{a} => {b}" for a, b in prev) + "\n"
        res = _batched(llm, system, part, lambda _lo, _hi, ctx=ctx: ctx + f"Translate these lines to {dst_n}.", lambda s: s)
        translated.extend(strip_foreign_script(r, target) or s for r, s in zip(res, part))
        if on_progress:
            on_progress(min(lo + batch, len(texts)), len(texts))
    for g in glossary or []:
        if g.get("src") and g.get("dst"):
            llm.stats["glossary_misses"] += sum(
                1 for s, t in zip(texts, translated) if g["src"].lower() in s.lower() and g["dst"].lower() not in t.lower())
    return [make_cue(c["start"], c["end"], t) for c, t in zip(cues, translated)]


def shorten_lines(llm: LLMClient, lines: list[dict], *, language: str, glossary: list[dict] | None = None,
                  batch: int = 8) -> list[str]:
    """Rút gọn câu để vừa khung thời gian lồng tiếng. lines: [{"text", "max_chars"}]. Câu nào LLM không rút gọn được
    (lỗi, dài hơn bản gốc, vượt quá 115% giới hạn) thì giữ nguyên bản gốc."""
    system = (
        f"You shorten {lang_name(language)} sentences so they can be spoken within a limited time (dubbing). "
        "The user message lists a character limit for each line. Rewrite each line more concisely so it stays within its limit. Keep the meaning, names, numbers and tone; drop filler words and redundant clauses; "
        "never add new information. "
        'Reply with ONLY JSON {"lines": [...]}: one rewritten string per input item, same length and order.\n'
        + _glossary_block(glossary)
    )
    texts = [x["text"] for x in lines]
    out: list[str] = []
    for lo in range(0, len(texts), batch):
        part = texts[lo: lo + batch]

        def prefix(l: int, h: int, base: int = lo) -> str:
            lim = "; ".join(f"line {k + 1}: at most {lines[base + l + k]['max_chars']} characters" for k in range(h - l))
            return "Shorten these lines. Limits: " + lim + "."

        res = _batched(llm, system, part, prefix, lambda s: s)
        for spec, new in zip(lines[lo: lo + batch], res):
            n = strip_foreign_script(new, language).strip()
            ok = n and len(n) < len(spec["text"]) and len(n) <= spec["max_chars"] * 1.15
            out.append(n if ok else spec["text"])
    return out
