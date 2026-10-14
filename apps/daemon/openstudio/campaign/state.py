"""State machine công cụ Chiến dịch nội dung (campaign): brief → kế hoạch (ý tưởng + lịch) → tài sản từng bài → duyệt/đăng → xuất gói."""
from __future__ import annotations

import copy
import re
from datetime import date, time

from ..errors import ApiError
from .catalog import MARKETS, PLATFORMS

TOOL = "campaign"
DEFAULT_BRIEF = {"goal": "", "product": "", "facts": "", "markets": ["us"], "platforms": ["tiktok"], "days": 7, "startDate": None,
                 "language": "vi", "tone": "thân thiện, dễ hiểu", "priceVnd": None, "fx": {}, "perWeek": {}}
STATUSES = ("planned", "ready", "approved", "posted", "failed")
TRANSITIONS = {"approved": {"ready", "approved", "posted"}, "posted": {"approved", "posted"}, "planned": set(STATUSES)}
POST_FIELDS = ("title", "hook", "caption", "hashtags", "script", "date", "time", "thumbnailText", "note")


def initial_state() -> dict:
    return {"brief": copy.deepcopy(DEFAULT_BRIEF), "plan": None, "posts": [], "export": None}


def _bad(msg: str) -> ApiError:
    return ApiError(400, "VALIDATION_FAILED", msg)


def clean_hashtags(items: object, limit: int) -> list[str]:
    out: list[str] = []
    for h in items if isinstance(items, list) else []:
        t = re.sub(r"[^\w]", "", str(h).lstrip("#"), flags=re.UNICODE)
        if t and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out[:limit]


def validate_brief(brief: dict) -> dict:
    if not isinstance(brief.get("goal"), str) or len(brief["goal"]) > 2000:
        raise _bad("Mục tiêu tối đa 2000 ký tự")
    for k in ("product", "facts"):
        if not isinstance(brief.get(k), str) or len(brief[k]) > 4000:
            raise _bad(f"{k} tối đa 4000 ký tự")
    ms, ps = brief.get("markets"), brief.get("platforms")
    if not isinstance(ms, list) or not (1 <= len(ms) <= 8) or any(m not in MARKETS for m in ms) or len(set(ms)) != len(ms):
        raise _bad("Chọn 1–8 thị trường hợp lệ: " + ", ".join(MARKETS))
    if not isinstance(ps, list) or not (1 <= len(ps) <= 3) or any(p not in PLATFORMS for p in ps) or len(set(ps)) != len(ps):
        raise _bad("Chọn 1–3 nền tảng hợp lệ: " + ", ".join(PLATFORMS))
    if brief.get("days") not in (7, 14, 30):
        raise _bad("days phải là 7, 14 hoặc 30")
    sd = brief.get("startDate")
    if sd is not None:
        try:
            date.fromisoformat(str(sd))
        except ValueError:
            raise _bad("startDate phải dạng YYYY-MM-DD")
    pv = brief.get("priceVnd")
    if pv is not None and (not isinstance(pv, (int, float)) or isinstance(pv, bool) or not (0 < pv < 1e12)):
        raise _bad("priceVnd phải là số dương")
    fx = brief.get("fx") or {}
    if not isinstance(fx, dict) or any(not isinstance(v, (int, float)) or v <= 0 for v in fx.values()):
        raise _bad("fx phải là {mã tiền tệ: số VND cho 1 đơn vị}, giá trị dương")
    pw = brief.get("perWeek") or {}
    if not isinstance(pw, dict) or any(k not in PLATFORMS or not isinstance(v, int) or not (1 <= v <= 7) for k, v in pw.items()):
        raise _bad("perWeek: {nền tảng: 1–7 bài/tuần}")
    brief["tone"] = str(brief.get("tone", ""))[:200]
    brief["language"] = str(brief.get("language", "vi"))[:8]
    return brief


def _check_time(d: str | None, t: str | None) -> None:
    try:
        if d:
            date.fromisoformat(d)
        if t:
            time.fromisoformat(t)
    except ValueError:
        raise _bad("date phải YYYY-MM-DD và time phải HH:MM")


def reducer(state: dict, type: str, payload: dict) -> dict:
    s = copy.deepcopy(state) or initial_state()
    for k, v in initial_state().items():
        s.setdefault(k, v)

    if type == "set-brief":
        b = payload.get("brief")
        if not isinstance(b, dict) or set(b) - set(DEFAULT_BRIEF):
            raise _bad("brief không hợp lệ")
        s["brief"] = validate_brief({**s["brief"], **b})
        return s

    if type == "set-post":
        post = next((p for p in s["posts"] if p["id"] == payload.get("id")), None)
        if not post:
            raise ApiError(404, "POST_NOT_FOUND", "Không có bài này")
        spec = PLATFORMS[post["platform"]]
        for k in POST_FIELDS:
            if k not in payload:
                continue
            v = payload[k]
            if k == "caption":
                v = str(v).strip()
                if len(v) > spec["caption_limit"]:
                    raise _bad(f"Caption tối đa {spec['caption_limit']} ký tự cho {spec['name']}")
            elif k == "title":
                v = str(v).strip()
                if len(v) > spec["title_limit"]:
                    raise _bad(f"Tiêu đề tối đa {spec['title_limit']} ký tự cho {spec['name']}")
            elif k == "hashtags":
                v = clean_hashtags(v, spec["hashtags"])
            else:
                v = str(v).strip()[:3000]
            post[k] = v
        if "date" in payload or "time" in payload:
            _check_time(post.get("date"), post.get("time"))
        if "status" in payload:
            target = payload["status"]
            if target not in STATUSES or target in ("ready", "failed"):
                raise _bad("Bạn chỉ chuyển được sang: planned, approved, posted")
            if post["status"] not in TRANSITIONS[target]:
                raise ApiError(409, "STATUS_TRANSITION", f"Không chuyển '{post['status']}' → '{target}' (cần tạo tài sản và duyệt trước)")
            post["status"] = target
        elif post["status"] in ("approved", "posted") and any(k in payload for k in ("caption", "hashtags", "script", "title")):
            post["status"] = "ready"   # sửa nội dung sau khi duyệt → phải duyệt lại
        return s

    if type == "_set-plan":
        s["plan"], s["posts"], s["export"] = payload["plan"], payload["posts"], None
        return s

    if type == "_merge-posts":
        by_id = {p["id"]: p for p in s["posts"]}
        for pid, upd in (payload.get("updates") or {}).items():
            if pid in by_id:
                by_id[pid].update(upd)
        s["export"] = None
        return s

    if type == "_set-export":
        s["export"] = payload.get("export")
        return s

    raise _bad(f"Lệnh không hỗ trợ: {type}")
