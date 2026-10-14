"""Công cụ cho Agent. Mỗi tool là một lớp mỏng gọi ĐÚNG các service mà giao diện web đang dùng
(`repo.apply_command(... author="agent")`, `start_*`) → UI và Agent cùng một nguồn sự thật (state machine), không có đường riêng."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, ValidationError

from ..errors import ApiError

Lang = Field(pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$", description="mã ngôn ngữ ISO, ví dụ vi, en, ja")
APPROVAL_RENDER = "render"      # xuất file media nặng (burn-in, trộn, xuất clip…)
APPROVAL_DOWNLOAD = "download"  # tải mô hình hàng trăm MB–GB: không bao giờ tự duyệt


@dataclass
class Services:
    settings: Any
    repo: Any
    runner: Any
    models: Any
    subs: Any
    tts: Any
    dub: Any
    hl: Any
    pod: Any
    music: Any
    llm: Any
    camp: Any = None
    thumb: Any = None
    editor: Any = None
    avatar: Any = None
    assets: Any = None


@dataclass
class AgentCtx:
    pid: str
    thread_id: str
    services: Services
    cancelled: Callable[[], bool]


# ---------- tham số (phẳng, để ép JSON schema cho LLM nhỏ) ----------
class NoArgs(BaseModel):
    pass


class GetState(BaseModel):
    tool: Literal["subtitles", "tts", "dubbing", "highlights", "podcast", "campaign", "thumbnail", "editor", "avatar"] = Field(description="công cụ cần xem trạng thái")


class FetchUrl(BaseModel):
    url: str = Field(pattern=r"^https?://\S+$", max_length=2000, description="liên kết video http(s) để tải")


class Transcribe(BaseModel):
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$", description="ngôn ngữ nói, bỏ trống để tự phát hiện")
    polish: bool | None = Field(default=None, description="LLM sửa chính tả sau khi nhận dạng")


class Translate(BaseModel):
    targets: list[str] = Field(min_length=1, max_length=8, description="danh sách mã ngôn ngữ đích, ví dụ [\"en\", \"ja\"]")
    tone: Literal["neutral", "formal", "casual"] | None = None
    market: str | None = Field(default=None, max_length=40, description="thị trường để bản địa hoá, ví dụ en-US")


class Glossary(BaseModel):
    entries: list[str] = Field(min_length=1, max_length=100, description="mỗi mục dạng \"thuật ngữ gốc = bản dịch\"")


class ExportSubs(BaseModel):
    lang: str = Lang
    format: Literal["srt", "vtt", "ass"] = "srt"
    second: str | None = Field(default=None, description="ngôn ngữ thứ hai cho phụ đề song ngữ")


class BurnSubs(BaseModel):
    lang: str = Lang
    second: str | None = None
    layout: Literal["horizontal", "vertical"] = "horizontal"
    fit: Literal["pad", "crop"] = "pad"


class DubSetup(BaseModel):
    target_lang: str = Field(pattern=r"^[a-z]{2,3}$", description="ngôn ngữ lồng tiếng (đã có bản dịch)")
    voice: str | None = Field(default=None, description="id giọng, ví dụ kokoro:af_heart; bỏ trống để tự chọn")
    keep_background: bool | None = None
    max_speed: float | None = Field(default=None, ge=1.0, le=1.6)


class HlSetup(BaseModel):
    count: int | None = Field(default=None, ge=1, le=10, description="số clip cần")
    min_len: float | None = Field(default=None, ge=5, le=170)
    max_len: float | None = Field(default=None, ge=6, le=180)
    layout: Literal["vertical", "horizontal"] | None = None
    subtitle_lang: str | None = None
    hook_overlay: bool | None = None


class HlExport(BaseModel):
    ids: list[str] | None = Field(default=None, description="id clip cần xuất; bỏ trống = mọi clip đã chọn")


class PodBrief(BaseModel):
    topic: str = Field(min_length=3, max_length=2000)
    minutes: int | None = Field(default=None, ge=1, le=30)
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")
    hosts: list[str] | None = Field(default=None, min_length=2, max_length=3, description="tên 2–3 người dẫn")
    style: str | None = Field(default=None, max_length=200)


class CampBrief(BaseModel):
    goal: str = Field(min_length=3, max_length=2000, description="mục tiêu chiến dịch")
    product: str | None = Field(default=None, max_length=400)
    facts: str | None = Field(default=None, max_length=4000, description="sự thật được phép dùng (không bịa thêm)")
    markets: list[str] = Field(min_length=1, max_length=8, description="mã thị trường: vn, us, jp, kr, cn, tw, ...")
    platforms: list[str] = Field(min_length=1, max_length=3, description="youtube, tiktok, facebook")
    days: Literal[7, 14, 30] = 7
    price_vnd: int | None = Field(default=None, gt=0)
    fx: dict[str, float] | None = Field(default=None, description="tỷ giá do người dùng cung cấp: {USD: VND mỗi 1 USD}")


class CampAssets(BaseModel):
    force: bool = Field(default=False, description="tạo lại cả bài đã có tài sản")


class ThumbMake(BaseModel):
    title: str = Field(min_length=2, max_length=90, description="tiêu đề lớn trên thumbnail")
    subtitle: str | None = Field(default=None, max_length=140)
    aspect: Literal["16:9", "9:16", "1:1"] = "16:9"
    count: int = Field(default=3, ge=1, le=6)
    background_asset: str | None = Field(default=None, description="id tài nguyên ảnh/video làm nền (không có → nền gradient)")


class EditorRender(BaseModel):
    preview: bool = Field(default=False, description="true = xem trước nhanh độ phân giải thấp")


class AvatarMake(BaseModel):
    avatar_id: str = Field(description="id avatar trong thư viện (av_…)")
    audio_asset: str = Field(description="id tài nguyên audio/video có giọng nói")
    aspect: Literal["16:9", "9:16", "1:1"] = "16:9"


class PodProduce(BaseModel):
    music: bool = Field(default=True, description="dùng nhạc mở/kết/nền có sẵn")
    video: bool = Field(default=True, description="dựng video sóng âm + phụ đề")


class Speak(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    language: str = Field(default="vi", pattern=r"^[a-z]{2,3}$")
    voice: str | None = None


class VoicesArgs(BaseModel):
    language: str = Field(pattern=r"^[a-z]{2,3}$")


class DownloadModel(BaseModel):
    model_id: str = Field(min_length=2, max_length=80, description="id mô hình trong registry")


class DraftText(BaseModel):
    title: str = Field(min_length=2, max_length=80, description="tên ngắn của bản nháp (dùng đặt tên file)")
    instruction: str = Field(min_length=5, max_length=1500, description="yêu cầu viết, nêu rõ định dạng mong muốn")
    language: str = Field(default="vi", pattern=r"^[a-z]{2,3}$")


class AskUser(BaseModel):
    question: str = Field(min_length=3, max_length=500, description="câu hỏi ngắn gửi người dùng")


@dataclass
class ToolSpec:
    name: str
    description: str
    params: type[BaseModel] | None
    handler: Callable[[Any, AgentCtx], dict]
    approval: str | None = None
    schema_override: dict | None = None            # tool ngoài (MCP): schema thô
    parser: Callable[[dict], dict] | None = None   # tool ngoài: tự kiểm tra tham số

    def schema(self) -> dict:
        s = self.schema_override if self.schema_override is not None else (self.params or NoArgs).model_json_schema()
        return _strip(s)

    def parse(self, args: dict) -> Any:
        if self.parser:
            return self.parser(args)
        try:
            return (self.params or NoArgs).model_validate(args or {})
        except ValidationError as e:
            msgs = "; ".join(f"{'.'.join(map(str, x['loc'])) or 'args'}: {x['msg']}" for x in e.errors()[:4])
            raise ApiError(400, "BAD_ARGS", f"Tham số không hợp lệ cho {self.name}: {msgs}")

    def signature(self) -> str:
        props = self.schema().get("properties", {})
        req = set(self.schema().get("required", []))
        parts = [f"{k}{'' if k in req else '?'}: {_typ(v)}" for k, v in props.items()]
        return f"{self.name}({', '.join(parts)})"


def _strip(node: Any) -> Any:
    """Bỏ `title`/`default` thừa của Pydantic để schema gọn và tương thích bộ chuyển schema→grammar của Ollama."""
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in node.items() if k not in ("title",)}
    if isinstance(node, list):
        return [_strip(v) for v in node]
    return node


def _typ(v: dict) -> str:
    if "enum" in v:
        return "|".join(map(str, v["enum"]))
    if "anyOf" in v:
        return "|".join(sorted({_typ(x) for x in v["anyOf"] if x.get("type") != "null"})) or "any"
    t = v.get("type", "any")
    if t == "array":
        return f"[{_typ(v.get('items', {}))}]"
    return str(t)


# ---------- rút gọn trạng thái / kết quả cho LLM (observation phải nhỏ) ----------
def shrink(obj: Any, limit: int = 1400) -> Any:
    def go(x: Any, depth: int = 0) -> Any:
        if isinstance(x, dict):
            return {k: go(v, depth + 1) for k, v in list(x.items())[:24]}
        if isinstance(x, list):
            return [go(v, depth + 1) for v in x[:8]] + ([f"… +{len(x) - 8}"] if len(x) > 8 else [])
        if isinstance(x, str):
            return x if len(x) <= 160 else x[:157] + "…"
        return x
    out = go(obj)
    text = json.dumps(out, ensure_ascii=False)
    return out if len(text) <= limit else {"truncated": text[: limit - 20] + "…"}


FILE_KEYS = ("path", "audio", "video", "subtitles", "notes", "chapters", "script")


def collect_files(obj: Any) -> list[str]:
    found: list[str] = []

    def go(x: Any) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                if k in FILE_KEYS and isinstance(v, str) and "/" in v:
                    found.append(v)
                elif k == "files" and isinstance(v, list):
                    found.extend(str(f) for f in v)
                else:
                    go(v)
        elif isinstance(x, list):
            for v in x:
                go(v)
    go(obj)
    return list(dict.fromkeys(found))[:12]


def summarize_state(tool: str, st: dict) -> dict:
    if tool == "subtitles":
        src = st.get("source") or {}
        return {"source": {k: src.get(k) for k in ("filename", "duration", "hasVideo")} if src else None, "sourceLang": st.get("sourceLang"),
                "tracks": {l: {"kind": t["kind"], "cues": len(t["cues"]), "stale": t.get("stale", False)} for l, t in (st.get("tracks") or {}).items()},
                "glossary": len(st.get("glossary") or []), "options": st.get("options")}
    if tool == "dubbing":
        plan = st.get("plan")
        items = (plan or {}).get("items", [])
        return {"options": st.get("options"), "plan": {"items": len(items), "targetLang": plan["targetLang"],
                                                       "status": {s: sum(1 for i in items if i["status"] == s) for s in {i["status"] for i in items}}} if plan else None,
                "result": st.get("result")}
    if tool == "highlights":
        return {"options": st.get("options"), "analysis": st.get("analysis"),
                "clips": [{k: c[k] for k in ("id", "start", "end", "title", "selected", "score")} for c in st.get("clips", [])],
                "exported": list(st.get("results") or {}), "summary": (st.get("summary") or {}).get("path")}
    if tool == "podcast":
        sc = st.get("script")
        return {"brief": {k: v for k, v in (st.get("brief") or {}).items() if k not in ("sourceText",)},
                "script": {"title": sc["title"], "sections": len(sc["sections"]), "turns": sum(len(s["turns"]) for s in sc["sections"])} if sc else None,
                "music": st.get("music"), "result": st.get("result")}
    if tool == "campaign":
        return {"brief": {k: v for k, v in (st.get("brief") or {}).items() if k != "facts"}, "plan": (st.get("plan") or {}).get("summary"),
                "posts": [{k: p[k] for k in ("id", "date", "market", "platform", "status")} for p in (st.get("posts") or [])[:60]], "export": st.get("export")}
    if tool == "editor":
        return {"settings": st.get("settings"), "segments": [{k: x[k] for k in ("id", "kind", "name", "in", "out", "speed")} for x in st.get("segments", [])],
                "texts": len(st.get("texts", [])), "overlays": len(st.get("overlays", [])), "music": bool((st.get("music") or {}).get("asset")), "result": st.get("result")}
    if tool == "thumbnail":
        return {"brief": st.get("brief"), "variants": [v["file"] for v in st.get("variants", [])]}
    if tool == "avatar":
        return {"brief": st.get("brief"), "result": st.get("result")}
    if tool == "tts":
        return {"language": st.get("language"), "voices": st.get("voices"), "textChars": len(st.get("text", "")), "result": st.get("result")}
    return st


def project_snapshot(s: Services, pid: str) -> str:
    """Một dòng/ công cụ: cho LLM biết dự án đang có gì mà không phải gọi get_state."""
    lines = []
    sub = s.subs.state(pid)
    src = sub.get("source")
    lines.append("subtitles: " + (f"source={src['filename']} ({src['duration']:.0f}s, {'video' if src['hasVideo'] else 'audio'}); tracks="
                                  + (", ".join(f"{l}({t['kind']}{',stale' if t.get('stale') else ''})" for l, t in sub.get('tracks', {}).items()) or "none") if src else "no source yet"))
    hl = s.hl.state(pid)
    lines.append(f"highlights: {len(hl.get('clips', []))} clips" if hl.get("clips") else "highlights: none")
    pod = s.pod.state(pid)
    cs = s.camp.state(pid) if s.camp else None
    if cs:
        lines.append("campaign: " + (f"{len(cs['posts'])} posts planned, " + ", ".join(f"{k}={sum(1 for p in cs['posts'] if p['status'] == k)}" for k in sorted({p['status'] for p in cs['posts']})) if cs["posts"] else "no plan"))
    lines.append("podcast: " + (f"script '{pod['script']['title']}'" if pod.get("script") else "no script") + (", produced" if pod.get("result") else ""))
    dub = s.dub.state(pid)
    lines.append("dubbing: " + (f"plan {len((dub.get('plan') or {}).get('items', []))} items" if dub.get("plan") else "no plan") + (", mixed" if dub.get("result") else ""))
    return "\n".join(lines)


# ---------- handler ----------
def _job(job: dict) -> dict:
    return {"job": job}


def build_tools(s: Services) -> dict[str, ToolSpec]:
    def cmd(ctx: AgentCtx, tool: str, type: str, payload: dict) -> dict:
        return s.repo.apply_command(ctx.pid, tool, type, payload, None, author="agent")

    def get_state(a: GetState, ctx: AgentCtx) -> dict:
        st = s.repo.get_state(ctx.pid, a.tool)["state"] or {}
        return {"state": summarize_state(a.tool, st)}

    def fetch_url(a: FetchUrl, ctx: AgentCtx) -> dict:
        return _job(s.subs.start_fetch(ctx.pid, a.url))

    def transcribe(a: Transcribe, ctx: AgentCtx) -> dict:
        return _job(s.subs.start_transcribe(ctx.pid, a.language, None, a.polish))

    def translate(a: Translate, ctx: AgentCtx) -> dict:
        return _job(s.subs.start_translate(ctx.pid, a.targets, a.tone, a.market))

    def glossary(a: Glossary, ctx: AgentCtx) -> dict:
        rows = []
        for e in a.entries:
            src, _, dst = e.partition("=")
            if src.strip():
                rows.append({"src": src.strip(), "dst": (dst or src).strip()})
        cmd(ctx, "subtitles", "set-glossary", {"glossary": rows})
        return {"glossary": len(rows)}

    def export_subs(a: ExportSubs, ctx: AgentCtx) -> dict:
        return s.subs.export(ctx.pid, a.lang, a.format, a.second)

    def burn(a: BurnSubs, ctx: AgentCtx) -> dict:
        return _job(s.subs.start_burn(ctx.pid, {"lang": a.lang, "second": a.second, "order": "primary-top", "layout": a.layout, "fit": a.fit,
                                                "font": "Arial", "size": None}))

    def dub_setup(a: DubSetup, ctx: AgentCtx) -> dict:
        opts: dict = {"targetLang": a.target_lang}
        if a.voice is not None:
            opts["voice"] = a.voice
        if a.keep_background is not None:
            opts["keepBackground"] = a.keep_background
        if a.max_speed is not None:
            opts["maxSpeed"] = a.max_speed
        cmd(ctx, "dubbing", "set-options", {"options": opts})
        plan = s.dub.build_plan(ctx.pid)["state"]["plan"]
        return {"options": opts, "planItems": len(plan["items"])}

    def dub_synth(_: NoArgs, ctx: AgentCtx) -> dict:
        return _job(s.dub.start_synthesize(ctx.pid))

    def dub_mix(_: NoArgs, ctx: AgentCtx) -> dict:
        return _job(s.dub.start_mix(ctx.pid))

    def hl_setup(a: HlSetup, ctx: AgentCtx) -> dict:
        opts = {k: v for k, v in {"count": a.count, "minLen": a.min_len, "maxLen": a.max_len, "layout": a.layout, "subtitleLang": a.subtitle_lang,
                                  "hookOverlay": a.hook_overlay}.items() if v is not None}
        cmd(ctx, "highlights", "set-options", {"options": opts})
        return {"options": opts}

    def hl_analyze(_: NoArgs, ctx: AgentCtx) -> dict:
        return _job(s.hl.start_analyze(ctx.pid))

    def hl_export(a: HlExport, ctx: AgentCtx) -> dict:
        return _job(s.hl.start_export(ctx.pid, a.ids))

    def hl_summary(_: NoArgs, ctx: AgentCtx) -> dict:
        return _job(s.hl.start_summary(ctx.pid))

    def pod_brief(a: PodBrief, ctx: AgentCtx) -> dict:
        brief: dict = {"topic": a.topic}
        if a.minutes is not None:
            brief["minutes"] = a.minutes
        if a.language:
            brief["language"] = a.language
        if a.hosts:
            brief["hosts"] = [{"name": h.strip(), "voice": None} for h in a.hosts]
        if a.style:
            brief["style"] = a.style
        cmd(ctx, "podcast", "set-brief", {"brief": brief})
        return {"brief": {k: v for k, v in brief.items()}}

    def pod_script(_: NoArgs, ctx: AgentCtx) -> dict:
        return _job(s.pod.start_script(ctx.pid))

    def pod_produce(a: PodProduce, ctx: AgentCtx) -> dict:
        cmd(ctx, "podcast", "set-music", {"music": {"intro": "builtin" if a.music else None, "outro": "builtin" if a.music else None,
                                                     "bed": "builtin" if a.music else None}})
        cmd(ctx, "podcast", "set-options", {"options": {"video": a.video}})
        return _job(s.pod.start_produce(ctx.pid))

    def camp_setup(a: CampBrief, ctx: AgentCtx) -> dict:
        brief = {"goal": a.goal, "markets": a.markets, "platforms": a.platforms, "days": a.days}
        for k, v in (("product", a.product), ("facts", a.facts), ("priceVnd", a.price_vnd), ("fx", a.fx)):
            if v is not None:
                brief[k] = v
        cmd(ctx, "campaign", "set-brief", {"brief": brief})
        return {"brief": brief}

    def camp_plan(_: NoArgs, ctx: AgentCtx) -> dict:
        return _job(s.camp.start_plan(ctx.pid))

    def camp_assets(a: CampAssets, ctx: AgentCtx) -> dict:
        return _job(s.camp.start_assets(ctx.pid, None, a.force, False, True))

    def camp_export(_: NoArgs, ctx: AgentCtx) -> dict:
        return s.camp.export(ctx.pid, False)

    def thumb_make(a: ThumbMake, ctx: AgentCtx) -> dict:
        bg = {"kind": "gradient", "asset": None}
        if a.background_asset:
            kind = s.assets.get(ctx.pid, a.background_asset)["kind"]
            bg = {"kind": "frame" if kind == "video" else "asset", "asset": a.background_asset}
        cmd(ctx, "thumbnail", "set-brief", {"brief": {"title": a.title, "subtitle": a.subtitle or "", "aspect": a.aspect, "count": a.count, "background": bg}})
        return _job(s.thumb.start(ctx.pid))

    def editor_render(a: EditorRender, ctx: AgentCtx) -> dict:
        return _job(s.editor.start_render(ctx.pid, a.preview))

    def avatar_make(a: AvatarMake, ctx: AgentCtx) -> dict:
        cmd(ctx, "avatar", "set-brief", {"brief": {"avatar": a.avatar_id, "audio": a.audio_asset, "aspect": a.aspect}})
        return _job(s.avatar.start(ctx.pid))

    def speak(a: Speak, ctx: AgentCtx) -> dict:
        cmd(ctx, "tts", "set-script", {"text": a.text, "language": a.language})
        if a.voice:
            cmd(ctx, "tts", "set-voices", {"voices": {"default": a.voice}})
        return _job(s.tts.start_synthesize(ctx.pid))

    def list_voices(a: VoicesArgs, ctx: AgentCtx) -> dict:
        from ..tts.engines import preset_voices
        vs = [*preset_voices(a.language), *s.tts.voices.list(a.language)]
        return {"voices": [{"id": v["id"], "name": v["name"], "gender": v.get("gender", "")} for v in vs[:20]], "total": len(vs)}

    def models_status(_: NoArgs, ctx: AgentCtx) -> dict:
        ms = [m for m in s.models.list() if m["downloadable"]]
        llm = s.llm.status()
        return {"installed": [m["id"] for m in ms if m["status"] == "installed"], "missing": [m["id"] for m in ms if m["status"] != "installed"],
                "llm": {"available": llm["available"], "model": llm["model"], "installed": llm["model_installed"]}}

    def download_model(a: DownloadModel, ctx: AgentCtx) -> dict:
        return _job(s.models.start_download(a.model_id, False))   # mô hình phi thương mại luôn bị từ chối ở đây (cần người xác nhận trên UI)

    def draft_text(a: DraftText, ctx: AgentCtx) -> dict:
        from ..podcast.notes import slugify
        from ..subtitles.llm import lang_name, strip_foreign_script
        s.llm.require()
        system = (f"You are a careful writer. Write in {lang_name(a.language)}. Follow the instruction exactly and output only the requested "
                  'text, no preface. Reply with ONLY JSON {"text": "..."}.')
        schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
        res = s.llm.json_object(system, a.instruction, schema, max_tokens=1800)
        text = strip_foreign_script(str((res or {}).get("text", "")), a.language).strip()
        if not text:
            raise ApiError(422, "DRAFT_FAILED", "LLM không viết được bản nháp; thử diễn đạt lại yêu cầu")
        d = s.settings.projects_dir / ctx.pid / "exports" / "drafts"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{slugify(a.title)}.md"
        path.write_text(text + "\n", encoding="utf-8")
        return {"path": f"exports/drafts/{path.name}", "chars": len(text), "preview": text[:400]}

    def ask_user(a: AskUser, ctx: AgentCtx) -> dict:
        return {"__ask": a.question}

    T = ToolSpec
    specs = [
        T("get_state", "Xem trạng thái hiện tại của một công cụ trong project (nguồn, bản dịch, clip, kịch bản…).", GetState, get_state),
        T("project_models", "Xem mô hình nào đã cài/thiếu và LLM có sẵn sàng không.", NoArgs, models_status),
        T("download_model", "Tải một mô hình còn thiếu về máy (nặng, cần người dùng duyệt).", DownloadModel, download_model, APPROVAL_DOWNLOAD),
        T("list_voices", "Liệt kê giọng đọc có sẵn cho một ngôn ngữ.", VoicesArgs, list_voices),
        T("subtitles_fetch_url", "Tải video từ một liên kết làm nguồn của project.", FetchUrl, fetch_url),
        T("subtitles_transcribe", "Nhận dạng giọng nói của nguồn thành phụ đề gốc (transcript).", Transcribe, transcribe),
        T("subtitles_translate", "Dịch phụ đề gốc sang một hoặc nhiều ngôn ngữ.", Translate, translate),
        T("subtitles_glossary", "Đặt bảng thuật ngữ để dịch/sửa đúng tên riêng.", Glossary, glossary),
        T("subtitles_export", "Xuất file phụ đề SRT/VTT/ASS (có thể song ngữ).", ExportSubs, export_subs),
        T("subtitles_burn", "Ghi phụ đề vào video (16:9 hoặc 9:16).", BurnSubs, burn, APPROVAL_RENDER),
        T("dubbing_setup", "Chọn ngôn ngữ/giọng lồng tiếng và lập kế hoạch câu (cần bản dịch đã có).", DubSetup, dub_setup),
        T("dubbing_synthesize", "Đọc từng câu bằng giọng AI và khớp khung thời gian.", NoArgs, dub_synth),
        T("dubbing_mix", "Trộn giọng lồng tiếng với nhạc nền và ghép vào video.", NoArgs, dub_mix, APPROVAL_RENDER),
        T("highlights_setup", "Đặt số clip, độ dài, khung hình cho việc cắt highlight.", HlSetup, hl_setup),
        T("highlights_analyze", "Tìm các đoạn hay trong video dài (cần transcript).", NoArgs, hl_analyze),
        T("highlights_export", "Xuất các clip highlight đã chọn thành video dọc có phụ đề.", HlExport, hl_export, APPROVAL_RENDER),
        T("highlights_summary", "Tạo video tóm tắt có giọng dẫn từ các clip đã chọn.", NoArgs, hl_summary, APPROVAL_RENDER),
        T("podcast_brief", "Đặt chủ đề, số phút, ngôn ngữ, người dẫn cho tập podcast.", PodBrief, pod_brief),
        T("podcast_write_script", "Viết kịch bản hội thoại podcast bằng LLM từ chủ đề đã đặt.", NoArgs, pod_script),
        T("podcast_produce", "Sản xuất podcast: giọng, nhạc, chương, video, show notes.", PodProduce, pod_produce, APPROVAL_RENDER),
        T("campaign_setup", "Đặt mục tiêu, thị trường, nền tảng, số ngày cho chiến dịch nội dung đa nền tảng.", CampBrief, camp_setup),
        T("campaign_plan", "Lập kế hoạch chiến dịch: ý tưởng (LLM) + lịch đăng theo múi giờ từng thị trường.", NoArgs, camp_plan),
        T("campaign_assets", "Tạo caption, hashtag, kịch bản, thumbnail, phụ đề bản địa hoá cho từng bài trong kế hoạch.", CampAssets, camp_assets),
        T("campaign_export", "Xuất gói chiến dịch: thư mục theo thị trường/nền tảng, schedule.csv, zip.", NoArgs, camp_export),
        T("thumbnail_make", "Tạo vài biến thể thumbnail/ảnh bìa có tiêu đề tiếng Việt từ ảnh, khung hình video hoặc nền gradient.", ThumbMake, thumb_make),
        T("editor_render", "Xuất (hoặc xem trước nhanh) video từ dòng thời gian chỉnh sửa hiện có của project.", EditorRender, editor_render, APPROVAL_RENDER),
        T("avatar_make", "Tạo video avatar nói (hoạt hình theo giọng, CPU) từ avatar trong thư viện + audio. Không phải lip-sync AI.", AvatarMake, avatar_make, APPROVAL_RENDER),
        T("speak_text", "Đọc một đoạn văn bản thành file âm thanh.", Speak, speak),
        T("draft_text", "Viết một bản nháp văn bản (kịch bản phân cảnh, lời dẫn, caption, hashtag…) và lưu thành file .md.", DraftText, draft_text),
        T("ask_user", "Hỏi người dùng khi thiếu thông tin bắt buộc (ví dụ chưa có video). Dừng lượt chạy để chờ trả lời.", AskUser, ask_user),
    ]
    return {t.name: t for t in specs}
