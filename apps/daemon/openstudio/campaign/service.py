"""Chiến dịch nội dung đa nền tảng, đa thị trường:
mục tiêu + thị trường + nền tảng → ý tưởng (LLM) + lịch đăng (xác định) → tài sản từng bài bản địa hoá (caption, hashtag, kịch bản,
thumbnail từ khung hình thật, phụ đề/video theo ngôn ngữ) → bảng theo dõi → xuất gói (thư mục + CSV lịch đăng + zip)."""
from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

from ..config import Settings
from ..errors import ApiError
from ..jobs import JobCancelled, JobContext, JobRunner
from ..podcast.notes import slugify
from ..repo import Repo
from ..security import redact
from ..subtitles import cues as C
from ..subtitles.llm import LLMClient, lang_name, strip_foreign_script
from ..subtitles.service import SubtitleService
from .catalog import MARKETS, PLATFORMS, build_schedule, ideas_needed, local_price, market_warnings, to_utc
from .state import TOOL, clean_hashtags, reducer

IDEAS_SCHEMA = {"type": "object", "properties": {"ideas": {"type": "array", "items": {"type": "object", "properties": {
    "title": {"type": "string"}, "hook": {"type": "string"}, "angle": {"type": "string"}}, "required": ["title", "hook", "angle"]}}}, "required": ["ideas"]}
ASSET_SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}, "caption": {"type": "string"}, "hashtags": {"type": "array", "items": {"type": "string"}},
                                                 "script": {"type": "string"}, "thumbnail_text": {"type": "string"}},
                "required": ["title", "caption", "hashtags", "script", "thumbnail_text"]}
THUMB = {"16:9": (1280, 720), "9:16": (1080, 1920), "1:1": (1080, 1080)}
CJK_LANGS = {"zh", "ja", "ko"}
_CJK = re.compile("[぀-ヿ㐀-䶿一-鿿가-힯]")
BATCH = 6
TERMINAL = ("succeeded", "failed", "cancelled")


def lang_ok(text: str, lang: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    cjk = sum(1 for ch in letters if _CJK.match(ch)) / len(letters)
    return cjk >= 0.3 if lang in CJK_LANGS else cjk == 0


def plain_latin(text: str, lang: str) -> str:
    """Tiếng Anh: tên riêng tiếng Việt lọt vào ("Tây Nguyên") đổi về chữ không dấu ("Tay Nguyen") như cách viết thông thường trong bài tiếng Anh."""
    if lang != "en":
        return text
    t = text.replace("đ", "d").replace("Đ", "D")
    return "".join(ch for ch in unicodedata.normalize("NFD", t) if unicodedata.category(ch) != "Mn")


def trim_words(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] if " " in text[:limit] else text[:limit]
    return cut.rstrip(" ,;:-—") + "…" if len(cut) < len(text) else cut


class CampaignService:
    def __init__(self, settings: Settings, repo: Repo, runner: JobRunner, subs: SubtitleService, llm: LLMClient):
        self.s, self.repo, self.runner, self.subs, self.llm = settings, repo, runner, subs, llm
        repo.reducers[TOOL] = reducer
        runner.register("campaign.plan", self._job_plan)
        runner.register("campaign.assets", self._job_assets)

    # ---- tiện ích ----
    def state(self, pid: str) -> dict:
        from .state import initial_state
        st = self.repo.get_state(pid, TOOL)["state"]
        return {**initial_state(), **st} if st else initial_state()

    def commit(self, pid: str, type: str, payload: dict) -> dict:
        return self.repo.apply_command(pid, TOOL, type, payload, None, author="job")

    def pdir(self, pid: str) -> Path:
        d = self.s.projects_dir / pid
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _wait_child(self, ctx: JobContext, job: dict) -> dict:
        while True:
            j = self.runner.get(job["id"])
            if j and j["status"] in TERMINAL:
                return j
            if ctx.cancelled():
                self.runner.cancel(job["id"])
                raise JobCancelled()
            time.sleep(0.4)

    # ---- tạo job ----
    def start_plan(self, pid: str) -> dict:
        b = self.state(pid)["brief"]
        if not b["goal"].strip():
            raise ApiError(409, "BRIEF_REQUIRED", "Hãy nhập mục tiêu chiến dịch")
        self.llm.require()
        return self.runner.submit("campaign.plan", {}, pid, TOOL)

    def start_assets(self, pid: str, post_ids: list[str] | None, force: bool, render_videos: bool, auto_translate: bool) -> dict:
        st = self.state(pid)
        if not st["posts"]:
            raise ApiError(409, "PLAN_REQUIRED", "Hãy lập kế hoạch trước")
        if post_ids is not None:
            unknown = [p for p in post_ids if p not in {x["id"] for x in st["posts"]}]
            if unknown:
                raise ApiError(404, "POST_NOT_FOUND", "Không có bài: " + ", ".join(unknown[:3]))
        if render_videos and not self.subs.state(pid).get("source"):
            raise ApiError(409, "SOURCE_REQUIRED", "Muốn dựng video có phụ đề cần video nguồn (làm ở công cụ Phụ đề & Dịch)")
        self.llm.require()
        return self.runner.submit("campaign.assets", {"postIds": post_ids, "force": force, "renderVideos": render_videos, "autoTranslate": auto_translate}, pid, TOOL)

    # ---- job: ý tưởng + lịch ----
    def _ideas(self, brief: dict, n: int, ctx: JobContext) -> tuple[list[dict], list[str]]:
        warnings: list[str] = []
        ideas: list[dict] = []
        seen: set[str] = set()
        lang = brief["language"]
        system = (f"You are a social media strategist. Brainstorm distinct, concrete content ideas for ONE campaign, written in {lang_name(lang)}. "
                  "Each idea has a short title (max 60 characters), a hook (the first line that stops the scroll, max 90 characters) and an angle "
                  "(one sentence: what the post shows or teaches). Vary the formats: tips, myths, behind-the-scenes, comparisons, stories, FAQs. "
                  "Never invent facts, prices or claims that are not in the brief. "
                  'Reply with ONLY JSON {"ideas":[{"title":"...","hook":"...","angle":"..."}]}.')
        calls = 0
        while len(ideas) < n and calls < 8:
            ctx.check_cancel()
            calls += 1
            want = min(BATCH, n - len(ideas))
            user = (f"Campaign goal: {brief['goal']}\nProduct/topic: {brief['product'] or '(see goal)'}\nFacts you may use: {brief['facts'] or '(none)'}\n"
                    f"Tone: {brief['tone']}\nAlready used titles (do not repeat): {', '.join(i['title'] for i in ideas) or '(none)'}\nGive exactly {want} new ideas.")
            res = self.llm.json_object(system, user, IDEAS_SCHEMA, max_tokens=900)
            for it in (res or {}).get("ideas", []):
                title = strip_foreign_script(str(it.get("title", "")), lang).strip()
                if title and title.lower() not in seen:
                    seen.add(title.lower())
                    ideas.append({"title": title[:80], "hook": strip_foreign_script(str(it.get("hook", "")), lang).strip()[:140],
                                  "angle": strip_foreign_script(str(it.get("angle", "")), lang).strip()[:300]})
            ctx.progress("ideas", 5 + 70 * min(len(ideas), n) / n, f"Ý tưởng {min(len(ideas), n)}/{n}", len(ideas), 0, n)
        if len(ideas) < n:
            warnings.append(f"LLM chỉ tạo được {len(ideas)}/{n} ý tưởng; phần còn lại dùng khung mặc định — nên bổ sung tay.")
            base = brief["product"] or brief["goal"]
            for k in range(len(ideas), n):
                ideas.append({"title": f"{base[:40]} — ý tưởng {k + 1}", "hook": "", "angle": ""})
        return ideas[:n], warnings

    def _job_plan(self, ctx: JobContext) -> dict:
        pid = ctx.project_id
        b = self.state(pid)["brief"]
        start = date.fromisoformat(b["startDate"]) if b["startDate"] else date.today() + timedelta(days=1)
        per_week = b.get("perWeek") or None
        n = ideas_needed(b["markets"], b["platforms"], b["days"], per_week)
        ctx.progress("ideas", 3, "Lập ý tưởng")
        ideas, warnings = self._ideas(b, n, ctx)
        warnings += market_warnings(b["markets"], b["platforms"])
        sched = build_schedule({m: len(ideas) for m in b["markets"]}, b["markets"], b["platforms"], b["days"], start, per_week)
        posts = []
        for p in sched:
            idea = ideas[p["idea_index"]]
            posts.append({**p, "title": idea["title"][:PLATFORMS[p["platform"]]["title_limit"]], "hook": idea["hook"], "idea": idea["angle"], "status": "planned",
                          "caption": "", "hashtags": [], "script": "", "thumbnailText": "", "thumbnail": None, "subtitles": None, "video": None, "note": ""})
        for m in b["markets"]:
            if local_price(b["priceVnd"], b["fx"], MARKETS[m]["currency"]) is None and b["priceVnd"]:
                warnings.append(f"Thiếu tỷ giá {MARKETS[m]['currency']} → bài ở {MARKETS[m]['name']} sẽ KHÔNG nhắc giá (OpenStudio không tự bịa tỷ giá).")
        plan = {"summary": f"{b['days']} ngày · {len(b['markets'])} thị trường · {len(b['platforms'])} nền tảng · {len(posts)} bài", "ideas": ideas,
                "warnings": list(dict.fromkeys(warnings)), "startDate": start.isoformat()}
        self.commit(pid, "_set-plan", {"plan": plan, "posts": posts})
        ctx.progress("done", 100, "Hoàn tất")
        return {"posts": len(posts), "ideas": len(ideas), "warnings": plan["warnings"]}

    # ---- thumbnail từ khung hình thật ----
    def render_thumbnail(self, pid: str, post: dict, text: str, src_rel: str | None, duration: float) -> str:
        base = self.pdir(pid)
        out_dir = base / "exports" / "campaign" / "thumbs"
        out_dir.mkdir(parents=True, exist_ok=True)
        aspect = PLATFORMS[post["platform"]]["aspect"][post["format"]]
        w, h = THUMB[aspect]
        ass_name = f"{post['id']}.ass"
        (out_dir / ass_name).write_text(C.to_ass([], width=w, height=h, size=round(h * (0.075 if w > h else 0.052)), hook=text, hook_seconds=30, hook_align=5,
                                                 hook_fade=False, wrap_chars=22 if w > h else 16), encoding="utf-8")
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},eq=brightness=-0.22:saturation=1.1,subtitles={ass_name}"
        name = f"{post['id']}.png"
        ff = shutil.which("ffmpeg") or "ffmpeg"
        if src_rel:
            at = max(0.0, duration * (0.1 + 0.8 * ((post["idea_index"] * 0.37) % 1.0)))
            cmd = [ff, "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(base / src_rel), "-vf", vf, "-frames:v", "1", name]
        else:
            palette = ["0x1e293b", "0x3b0764", "0x14532d", "0x7c2d12", "0x1e3a8a", "0x831843"]
            cmd = [ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={palette[post['idea_index'] % len(palette)]}:s={w}x{h}:d=1", "-vf",
                   f"subtitles={ass_name}", "-frames:v", "1", name]
        r = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0 or not (out_dir / name).is_file():
            raise ApiError(422, "THUMBNAIL_FAILED", "Không dựng được thumbnail: " + redact(r.stderr[-200:]))
        return f"exports/campaign/thumbs/{name}"

    # ---- sinh tài sản một bài ----
    def _generate(self, brief: dict, post: dict, ctx_price: str | None) -> dict:
        market, plat = MARKETS[post["market"]], PLATFORMS[post["platform"]]
        lang = market["lang"]
        fmt = post["format"]
        kind = {"long_video": "a long video (describe a 3-5 point outline with approximate timings)", "short_video": "a short vertical video of 30-45 seconds "
                "(write HOOK for the first 3 seconds, BODY, CTA, with approximate seconds)", "post": "a text/image post (leave `script` empty)"}[fmt]
        system = (f"You are a social-media copywriter localizing a campaign for the {market['name']} market ({market['region']}). Write EVERYTHING in {lang_name(lang)} "
                  f"(natural, not word-by-word translation). Tone: {brief['tone']}. Formality: {market['formality']} — {market['address']}. "
                  f"Cultural and formatting notes: {' '.join(market['notes'])} Dates use {market['date']}; units are {market['units']} — convert measurements when present. "
                  f"Platform: {plat['name']}. Content: {kind}. `title` max {plat['title_limit']} characters; `caption` max {plat['caption_limit']} characters; at most "
                  f"{plat['hashtags']} hashtags written WITHOUT the # sign; `thumbnail_text` max {18 if lang in CJK_LANGS else 38} characters, punchy. "
                  "Use only the facts given by the user; NEVER invent prices, discounts, statistics, awards or claims. "
                  'Reply with ONLY JSON {"title","caption","hashtags":[...],"script","thumbnail_text"}.')
        facts = brief["facts"] or "(none)"
        price = f"\nLocal price (already converted, use exactly): {ctx_price}" if ctx_price else "\nDo not mention any price."
        user = (f"Campaign goal: {brief['goal']}\nProduct/topic: {brief['product'] or '(see goal)'}\nFacts: {facts}{price}\n"
                f"Post idea (written in {lang_name(brief['language'])}): title \"{post['title']}\"; hook \"{post['hook']}\"; angle \"{post['idea']}\".\n"
                f"Localize this idea for {market['name']} on {plat['name']}.")
        last_err = ""
        for _attempt in range(2):
            res = self.llm.json_object(system, user + (f"\nPrevious attempt was rejected: {last_err}. Fix it." if last_err else ""), ASSET_SCHEMA, max_tokens=1100)
            if not res:
                last_err = "invalid JSON"
                continue
            title = strip_foreign_script(str(res.get("title", "")), lang).strip() if lang not in CJK_LANGS else str(res.get("title", "")).strip()
            caption = strip_foreign_script(str(res.get("caption", "")), lang).strip() if lang not in CJK_LANGS else str(res.get("caption", "")).strip()
            script = strip_foreign_script(str(res.get("script", "")), lang).strip() if lang not in CJK_LANGS else str(res.get("script", "")).strip()
            thumb = strip_foreign_script(str(res.get("thumbnail_text", "")), lang).strip() if lang not in CJK_LANGS else str(res.get("thumbnail_text", "")).strip()
            title, caption, script, thumb = (plain_latin(x, lang) for x in (title, caption, script, thumb))
            if not caption or not title:
                last_err = "empty title or caption"
                continue
            if not lang_ok(caption, lang):
                last_err = f"the caption is not written in {lang_name(lang)}"
                continue
            return {"title": trim_words(title, plat["title_limit"]), "caption": trim_words(caption, plat["caption_limit"]),
                    "hashtags": clean_hashtags(res.get("hashtags"), plat["hashtags"]), "script": script if fmt != "post" else "",
                    "thumbnailText": trim_words(thumb or title, 18 if lang in CJK_LANGS else 40)}
        raise ApiError(422, "ASSET_FAILED", f"LLM không viết được nội dung hợp lệ ({last_err})")

    # ---- job: tài sản ----
    def _job_assets(self, ctx: JobContext) -> dict:
        pid, p = ctx.project_id, ctx.params
        st = self.state(pid)
        brief = st["brief"]
        want = set(p["postIds"]) if p.get("postIds") is not None else None
        todo = [x for x in st["posts"] if (want is None or x["id"] in want) and (p.get("force") or x["status"] in ("planned", "failed"))]
        if not todo:
            return {"generated": 0, "failed": 0, "skipped": len(st["posts"])}
        subs_state = self.subs.state(pid)
        src = subs_state.get("source")
        langs = sorted({MARKETS[x["market"]]["lang"] for x in todo})
        lang_assets: dict[str, dict] = {l: {"subtitles": None, "video": None} for l in langs}
        notes: list[str] = []

        # 1) phụ đề / video theo ngôn ngữ (nếu dự án có nguồn + transcript)
        if src and subs_state.get("sourceLang"):
            src_lang = subs_state["sourceLang"]
            tracks = subs_state.get("tracks", {})
            missing = [l for l in langs if l != src_lang and (l not in tracks or tracks[l].get("stale"))]
            if missing and p.get("autoTranslate", True):
                ctx.progress("translate", 4, "Dịch phụ đề cho các thị trường: " + ", ".join(missing))
                try:
                    j = self._wait_child(ctx, self.subs.start_translate(pid, missing, None, None))
                    if j["status"] != "succeeded":
                        notes.append("Dịch phụ đề lỗi: " + str((j.get("error") or {}).get("message", ""))[:120])
                except ApiError as e:
                    notes.append("Không dịch được phụ đề: " + e.message)
            tracks = self.subs.state(pid).get("tracks", {})
            vertical = all(set(PLATFORMS[pp]["aspect"].values()) == {"9:16"} for pp in brief["platforms"])
            for i, l in enumerate(langs):
                ctx.check_cancel()
                if l != src_lang and l not in tracks:
                    continue
                ctx.progress("subtitles", 8 + 12 * i / len(langs), f"Xuất phụ đề {l}")
                try:
                    lang_assets[l]["subtitles"] = self.subs.export(pid, l, "srt")["path"]
                    if p.get("renderVideos"):
                        j = self._wait_child(ctx, self.subs.start_burn(pid, {"lang": l, "second": None, "order": "primary-top", "layout": "vertical" if vertical else "horizontal",
                                                                             "fit": "crop", "font": "Arial", "size": None}))
                        if j["status"] == "succeeded":
                            lang_assets[l]["video"] = (j.get("result") or {}).get("path")
                        else:
                            notes.append(f"Dựng video {l} lỗi: " + str((j.get("error") or {}).get("message", ""))[:100])
                except ApiError as e:
                    notes.append(f"{l}: {e.message}")

        # 2) từng bài
        updates: dict[str, dict] = {}
        failed = 0
        for i, post in enumerate(todo):
            ctx.check_cancel()
            ctx.progress("assets", 22 + 76 * i / len(todo), f"Bài {i + 1}/{len(todo)} · {MARKETS[post['market']]['name']} · {PLATFORMS[post['platform']]['name']}", i, failed, len(todo))
            market = MARKETS[post["market"]]
            price = local_price(brief["priceVnd"], brief["fx"], market["currency"])
            try:
                a = self._generate(brief, post, price)
                thumb = self.render_thumbnail(pid, post, a["thumbnailText"], src["path"] if src and src.get("hasVideo") else None, float(src["duration"]) if src else 0.0)
                la = lang_assets[market["lang"]]
                updates[post["id"]] = {**a, "thumbnail": thumb, "subtitles": la["subtitles"], "video": la["video"], "status": "ready", "note": ""}
            except ApiError as e:
                failed += 1
                updates[post["id"]] = {"status": "failed", "note": e.message[:200]}
            if len(updates) >= 4:
                self.commit(pid, "_merge-posts", {"updates": updates})
                updates = {}
        if updates:
            self.commit(pid, "_merge-posts", {"updates": updates})
        ctx.progress("done", 100, "Hoàn tất")
        return {"generated": len(todo) - failed, "failed": failed, "notes": notes, "languages": langs}

    # ---- xuất gói ----
    def export(self, pid: str, include_videos: bool = False) -> dict:
        st = self.state(pid)
        brief, posts = st["brief"], st["posts"]
        ready = [x for x in posts if x["status"] in ("ready", "approved", "posted")]
        if not ready:
            raise ApiError(409, "NOTHING_TO_EXPORT", "Chưa có bài nào có tài sản (hãy tạo tài sản trước)")
        base = self.pdir(pid)
        slug = slugify(brief["product"] or brief["goal"], "chien-dich") + "-" + ((st["plan"] or {}).get("startDate") or date.today().isoformat())
        root = base / "exports" / "campaign" / slug
        if root.exists():
            shutil.rmtree(root)               # chỉ xoá thư mục gói do chính OpenStudio sinh ra ở lần xuất trước
        root.mkdir(parents=True)
        rows, files = [], 0
        for x in sorted(posts, key=lambda x: (x["date"], x["market"], x["platform"])):
            folder = None
            if x["status"] in ("ready", "approved", "posted"):
                folder = root / x["market"] / x["platform"] / f"{x['date']}_{x['id']}"
                folder.mkdir(parents=True)
                tags = " ".join(f"#{h}" for h in x["hashtags"])
                (folder / "caption.txt").write_text(f"{x['title']}\n\n{x['caption']}\n\n{tags}\n", encoding="utf-8")
                files += 1
                if x["script"]:
                    (folder / "script.md").write_text(f"# {x['title']}\n\n{x['script']}\n", encoding="utf-8")
                    files += 1
                for key, name in (("thumbnail", "thumbnail.png"), ("subtitles", "subtitles.srt")) + ((("video", "video.mp4"),) if include_videos else ()):
                    if x.get(key) and (base / x[key]).is_file():
                        shutil.copyfile(base / x[key], folder / name)
                        files += 1
            m, plat = MARKETS[x["market"]], PLATFORMS[x["platform"]]
            def rel(f: str, folder: Path | None = folder) -> str:
                return (folder / f).relative_to(root).as_posix() if folder and (folder / f).is_file() else ""

            rows.append({"post_id": x["id"], "date": x["date"], "time": x["time"], "timezone": m["tz"], "utc": to_utc(x["date"], x["time"], m["tz"]), "market": x["market"],
                         "language": m["region"], "platform": plat["name"], "format": x["format"], "title": x["title"], "caption": x["caption"],
                         "hashtags": " ".join(f"#{h}" for h in x["hashtags"]), "thumbnail": rel("thumbnail.png"), "subtitles": rel("subtitles.srt"),
                         "video": rel("video.mp4") or (("project:" + x["video"]) if x.get("video") else ""), "script": rel("script.md"), "status": x["status"], "note": x.get("note", "")})
        csv_path = root / "schedule.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        (root / "campaign.json").write_text(json.dumps({"brief": brief, "plan": st["plan"], "posts": posts}, ensure_ascii=False, indent=1), encoding="utf-8")
        (root / "README.md").write_text(self._readme(brief, st, rows, include_videos), encoding="utf-8")
        zip_path = shutil.make_archive(str(root), "zip", root_dir=root)
        result = {"folder": root.relative_to(base).as_posix(), "csv": csv_path.relative_to(base).as_posix(),
                  "zip": Path(zip_path).relative_to(base).as_posix(), "posts": len(ready), "rows": len(rows), "files": files,
                  "exportedAt": datetime.now().isoformat(timespec="seconds")}
        self.commit(pid, "_set-export", {"export": result})
        return result

    @staticmethod
    def _readme(brief: dict, st: dict, rows: list[dict], include_videos: bool) -> str:
        lines = [f"# Gói chiến dịch: {brief['product'] or brief['goal'][:60]}", "", f"**Mục tiêu:** {brief['goal']}", "",
                 f"**Kế hoạch:** {(st['plan'] or {}).get('summary', '')}", ""]
        for w in (st["plan"] or {}).get("warnings", []):
            lines.append(f"- ⚠ {w}")
        lines += ["", "## Cách dùng", "- `schedule.csv` (UTF-8 có BOM, mở được bằng Excel): ngày/giờ **theo múi giờ địa phương của thị trường** (`timezone`) và bản quy đổi UTC.",
                  "- Mỗi bài có thư mục `<thị trường>/<nền tảng>/<ngày>_<mã bài>/` gồm caption, kịch bản, thumbnail, phụ đề.",
                  "- Video " + ("đã được chép vào từng thư mục." if include_videos else "không chép vào gói (nặng); cột `video` trỏ tới file trong project."),
                  "- Nội dung do AI viết cục bộ: **cần người bản ngữ rà soát** trước khi đăng (đặc biệt giá, thuật ngữ, quy định quảng cáo).", "", "## Lịch đăng", "",
                  "| Ngày | Giờ | TZ | Thị trường | Nền tảng | Định dạng | Tiêu đề | Trạng thái |", "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['date']} | {r['time']} | {r['timezone']} | {r['market']} | {r['platform']} | {r['format']} | {r['title'].replace('|', '/')} | {r['status']} |")
        return "\n".join(lines) + "\n"
