"""Nghiệm thu GĐ8: CHIẾN DỊCH 3 ngôn ngữ (Việt · Anh · Nhật) từ một video tiếng Việt, daemon thật + Whisper turbo + qwen3 thật.

Luồng: video → transcript → dịch en+ja → kế hoạch 7 ngày (3 thị trường × 2 nền tảng) → tài sản từng bài (caption/hashtag/kịch bản/thumbnail)
+ video có phụ đề từng ngôn ngữ → duyệt vài bài → xuất gói (thư mục + schedule.csv + zip).

Chạy:  OPENSTUDIO_URL=http://127.0.0.1:8799 OPENSTUDIO_TOKEN=... uv run --project apps/daemon python scripts/e2e_campaign.py
"""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")
URL = os.environ.get("OPENSTUDIO_URL", "http://127.0.0.1:8799")
TOKEN = os.environ["OPENSTUDIO_TOKEN"]
ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "apps/daemon/tests/fixtures"
DATA = Path(os.environ.get("OPENSTUDIO_DATA_DIR", ROOT / ".runtime"))
TMP = DATA / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
c = httpx.Client(base_url=URL, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=60)
results: list[tuple[str, bool]] = []
VI_MARKS = re.compile("[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]", re.I)
KANA = re.compile("[぀-ヿ]")


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok))
    print(("PASS" if ok else "FAIL"), name, detail, flush=True)


def wait(job_id: str, limit: float = 3600) -> dict:
    t0, last = time.time(), None
    while time.time() - t0 < limit:
        j = c.get(f"/jobs/{job_id}").json()
        p = j.get("progress") or {}
        line = f"{j['status']} {p.get('phase', '')} {p.get('percent', 0):.0f}% {p.get('message', '')}"
        if line != last:
            print("   ", line, flush=True)
            last = line
        if j["status"] in ("succeeded", "failed", "cancelled"):
            return j
        time.sleep(4)
    raise TimeoutError(job_id)


def ok(resp: httpx.Response) -> dict:
    if resp.status_code >= 300:
        print("HTTP", resp.status_code, resp.text[:600])
        sys.exit(2)
    return resp.json()


# ---- 1. video nguồn: 70 giây đầu của bản thu tiếng Việt + hình testsrc ----
video = TMP / "camp_src.mp4"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=960x540:rate=25:duration=70", "-i", str(FIX / "sample_vi.mp3"),
                "-t", "70", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)], check=True)
pid = ok(c.post("/projects", json={"name": "E2E chiến dịch"}))["id"]
t_all = time.time()
j = wait(ok(c.put(f"/projects/{pid}/subtitles/upload", params={"filename": video.name}, content=video.read_bytes()))["id"])
check("upload+probe", j["status"] == "succeeded", str(j.get("error")))
src = ok(c.get(f"/projects/{pid}/tools/subtitles/state"))["state"]["source"]

t0 = time.time()
j = wait(ok(c.post(f"/projects/{pid}/subtitles/transcribe", json={"language": "vi", "polish": True}))["id"])
check("transcript tiếng Việt", j["status"] == "succeeded", f"{time.time() - t0:.0f}s {j.get('error') or ''}")

# ---- 2. brief: 3 thị trường × 2 nền tảng, giá + tỷ giá USD do người dùng cấp (KHÔNG có tỷ giá JPY) ----
start = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
cmd = f"/projects/{pid}/tools/campaign/commands"
ok(c.post(cmd, json={"type": "set-brief", "payload": {"brief": {
    "goal": "Ra mắt gói cà phê rang xay Tây Nguyên và tăng đơn hàng trực tuyến", "product": "Cà phê rang xay Tây Nguyên 500g",
    "facts": "Hạt Robusta và Arabica trồng ở Tây Nguyên. Rang xay tươi mỗi tuần. Giao hàng toàn quốc và quốc tế. Đóng gói kín giữ hương.",
    "markets": ["vn", "us", "jp"], "platforms": ["tiktok", "facebook"], "days": 7, "startDate": start,
    "priceVnd": 250000, "fx": {"USD": 25000}, "tone": "gần gũi, đáng tin"}}}))

t0 = time.time()
j = wait(ok(c.post(f"/projects/{pid}/campaign/plan"))["id"])
check("lập kế hoạch (LLM ý tưởng + lịch)", j["status"] == "succeeded", f"{time.time() - t0:.0f}s {j.get('error') or ''}")
st = ok(c.get(f"/projects/{pid}/tools/campaign/state"))["state"]
posts = st["posts"]
check("kế hoạch phủ 3 thị trường × 2 nền tảng", {p["market"] for p in posts} == {"vn", "us", "jp"} and {p["platform"] for p in posts} == {"tiktok", "facebook"}, f"{len(posts)} bài")
check("mọi bài nằm trong 7 ngày từ ngày bắt đầu", all(start <= p["date"] <= (datetime.fromisoformat(start) + timedelta(days=6)).strftime("%Y-%m-%d") for p in posts))
check("có cảnh báo thiếu tỷ giá JPY (không bịa)", any("JPY" in w for w in st["plan"]["warnings"]), "; ".join(st["plan"]["warnings"])[:200])
print("   ý tưởng mẫu:", [i["title"] for i in st["plan"]["ideas"][:3]])

# ---- 3. tài sản: dịch phụ đề en+ja tự động, dựng video có phụ đề từng ngôn ngữ ----
t0 = time.time()
j = wait(ok(c.post(f"/projects/{pid}/campaign/assets", json={"renderVideos": True, "autoTranslate": True}))["id"], 7200)
check("tạo tài sản cho các bài", j["status"] == "succeeded", f"{time.time() - t0:.0f}s {j.get('error') or ''}")
res = j.get("result") or {}
print("   kết quả:", json.dumps(res, ensure_ascii=False))
posts = ok(c.get(f"/projects/{pid}/tools/campaign/state"))["state"]["posts"]
ready = [p for p in posts if p["status"] == "ready"]
check("≥ 90% bài sẵn sàng", len(ready) / len(posts) >= 0.9, f"{len(ready)}/{len(posts)}; lỗi: {[p['note'] for p in posts if p['status'] == 'failed'][:2]}")
pdir = DATA / "projects" / pid
check("mỗi bài sẵn sàng có thumbnail PNG thật", all(p["thumbnail"] and (pdir / p["thumbnail"]).stat().st_size > 5000 for p in ready))
by = lambda m: [p for p in ready if p["market"] == m]
check("caption thị trường VN viết tiếng Việt", all(VI_MARKS.search(p["caption"]) for p in by("vn")), f"mẫu: {by('vn')[0]['caption'][:80] if by('vn') else ''}")
check("caption thị trường US viết tiếng Anh (không dấu tiếng Việt, không kana)", all(not VI_MARKS.search(p["caption"]) and not KANA.search(p["caption"]) for p in by("us")), f"mẫu: {by('us')[0]['caption'][:80] if by('us') else ''}")
check("caption thị trường JP có chữ Nhật", all(KANA.search(p["caption"]) for p in by("jp")), f"mẫu: {by('jp')[0]['caption'][:60] if by('jp') else ''}")
check("không bịa giá: JP/KR không có ký hiệu ¥/円 khi thiếu tỷ giá", all(not re.search(r"[¥円]|JPY|\$|USD", p["caption"]) for p in by("jp")))
check("VN nếu nhắc giá thì đúng 250.000", all(("250" in p["caption"]) or not re.search(r"\d{2,3}[.,]?\d{3}\s*(đ|₫|VND)", p["caption"]) for p in by("vn")))
check("giới hạn hashtag & caption theo nền tảng", all(len(p["hashtags"]) <= 5 and len(p["caption"]) <= 2200 for p in ready if p["platform"] == "tiktok") and all(not h.startswith("#") for p in ready for h in p["hashtags"]))
vids = {p["market"]: p["video"] for p in ready if p["video"]}
check("có video phụ đề cho cả 3 ngôn ngữ", set(vids) == {"vn", "us", "jp"}, str(vids))
for m, v in vids.items():
    d = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", str(pdir / v)], capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    check(f"video {m} dài ≈ nguồn", abs(float(d["format"]["duration"]) - src["duration"]) < 1.0, f"{float(d['format']['duration']):.1f}s vs {src['duration']:.1f}s")

# ---- 4. duyệt vài bài + xuất ----
for p in ready[:3]:
    ok(c.post(cmd, json={"type": "set-post", "payload": {"id": p["id"], "status": "approved"}}))
bad = c.post(cmd, json={"type": "set-post", "payload": {"id": posts[0]["id"], "caption": "x" * 5000}})
check("caption quá giới hạn bị từ chối", bad.status_code == 400)
ex = ok(c.post(f"/projects/{pid}/campaign/export", json={"includeVideos": False}))
print("   xuất:", json.dumps(ex, ensure_ascii=False))
rows = list(csv.DictReader((pdir / ex["csv"]).open(encoding="utf-8-sig", newline="")))
check("schedule.csv đủ dòng, có UTC + múi giờ", len(rows) == len(posts) and all(r["utc"] and r["timezone"] for r in rows), f"{len(rows)} dòng")
vn = next(r for r in rows if r["market"] == "vn")
local = datetime.fromisoformat(f"{vn['date']}T{vn['time']}")
check("UTC của VN = giờ địa phương − 7h", datetime.fromisoformat(vn["utc"].replace("Z", "+00:00")).replace(tzinfo=None) == local - timedelta(hours=7), f"{vn['date']} {vn['time']} → {vn['utc']}")
check("giờ đăng tách theo múi giờ (JP ≠ US ≠ VN trong UTC)", len({(r["market"], r["utc"][11:16]) for r in rows}) >= 3)
with zipfile.ZipFile(pdir / ex["zip"]) as z:
    names = z.namelist()
check("zip có schedule.csv, README, caption từng bài, thumbnail", "schedule.csv" in names and "README.md" in names and sum(n.endswith("caption.txt") for n in names) == len(ready) and sum(n.endswith("thumbnail.png") for n in names) == len(ready), f"{len(names)} file")
check("gói xuất chỉ chứa bài có tài sản (bài lỗi không lọt vào)", ex["posts"] == len(ready))
state = ok(c.get(f"/projects/{pid}/tools/campaign/state"))
check("mỗi lần sửa tạo phiên bản mới (revision tăng)", state["revision"] >= 6, f"revision {state['revision']}")

print(f"\nTổng thời gian {time.time() - t_all:.0f}s")
bad = [n for n, k in results if not k]
print(f"{len(results) - len(bad)}/{len(results)} đạt", ("— LỖI: " + "; ".join(bad)) if bad else "")
sys.exit(1 if bad else 0)
