"""Nghiệm thu tạo ảnh AI + ảnh→video chuyển động, daemon thật + FLUX.2 klein 4B thật (CPU) + qwen3 dịch prompt.
Luồng: mô tả tiếng Việt → LLM dịch → ảnh 512px → tự vào kho tài nguyên → video chuyển động 9:16 → thumbnail tiêu đề tiếng Việt từ chính ảnh đó.

Chạy:  OPENSTUDIO_URL=http://127.0.0.1:8799 OPENSTUDIO_TOKEN=... uv run --project apps/daemon python scripts/e2e_images.py   (mất ~5 phút trên CPU)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")
URL = os.environ.get("OPENSTUDIO_URL", "http://127.0.0.1:8799")
TOKEN = os.environ["OPENSTUDIO_TOKEN"]
ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("OPENSTUDIO_DATA_DIR", ROOT / ".runtime"))
c = httpx.Client(base_url=URL, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=120)
results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok))
    print(("PASS" if ok else "FAIL"), name, detail, flush=True)


def get_json(url: str) -> dict:
    """uvicorn đóng kết nối rảnh sau 5 s; poll mỗi 5 s dễ đụng đúng lúc đó → thử lại một lần."""
    for attempt in range(3):
        try:
            return c.get(url).json()
        except httpx.TransportError:
            if attempt == 2:
                raise
            time.sleep(1)


def wait(job_id: str, limit: float = 2400) -> dict:
    t0, last = time.time(), None
    while time.time() - t0 < limit:
        j = get_json(f"/jobs/{job_id}")
        p = j.get("progress") or {}
        line = f"{j['status']} {p.get('phase', '')} {p.get('percent', 0):.0f}% {p.get('message', '')}"
        if line != last:
            print("   ", line, flush=True)
            last = line
        if j["status"] in ("succeeded", "failed", "cancelled"):
            return j
        time.sleep(5)
    raise TimeoutError(job_id)


def ok(resp: httpx.Response) -> dict:
    if resp.status_code >= 300:
        print("HTTP", resp.status_code, resp.text[:600])
        sys.exit(2)
    return resp.json()


def probe(path: Path) -> dict:
    return json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)], capture_output=True, text=True, encoding="utf-8", check=True).stdout)


pid = os.environ.get("E2E_PID") or ok(c.post("/projects", json={"name": "E2E ảnh AI"}))["id"]   # E2E_PID: tiếp tục project cũ, bỏ qua bước tạo ảnh nếu đã có
pdir = DATA / "projects" / pid
t_all = time.time()
st = ok(c.get("/image/status"))
check("engine + mô hình ảnh được Model Manager nhận là đã cài", st["engineInstalled"] and st["modelInstalled"], str(st))
cmd = lambda tool, t, p: ok(c.post(f"/projects/{pid}/tools/{tool}/commands", json={"type": t, "payload": p}))
existing = ok(c.get(f"/projects/{pid}/tools/image/state"))["state"].get("results") if os.environ.get("E2E_PID") else None
cmd("image", "set-brief", {"brief": {"prompt": "một ly cà phê phin Việt Nam trên bàn gỗ, ánh nắng buổi sáng, ảnh chụp thật", "aspect": "16:9", "quality": "draft", "count": 1, "seed": 7}})
t0 = time.time()
if existing:
    res = {"prompt": existing[0]["prompt"], "warnings": []}
    check("tạo ảnh AI (FLUX.2 klein, CPU) — dùng kết quả của lần chạy trước", True, f"{existing[0]['seconds']}s")
else:
    j = wait(ok(c.post(f"/projects/{pid}/image/generate"))["id"])
    check("tạo ảnh AI (FLUX.2 klein, CPU)", j["status"] == "succeeded", f"{time.time() - t0:.0f}s {j.get('error') or ''}")
    res = j["result"]
print("   prompt tiếng Anh:", res["prompt"], "| cảnh báo:", res["warnings"])
im = ok(c.get(f"/projects/{pid}/tools/image/state"))["state"]["results"][0]
png = pdir / im["file"]
info = probe(png)["streams"][0]
check("ảnh 512×288 (16:9, bội số 16), file PNG thật", (info["width"], info["height"]) == (512, 288) and png.stat().st_size > 20_000, f"{png.stat().st_size // 1024} KB")
check("prompt đã được dịch sang tiếng Anh (không còn dấu tiếng Việt)", all(ord(ch) < 0x300 or ch.isascii() for ch in res["prompt"]) and "coffee" in res["prompt"].lower(), res["prompt"][:80])
check("ảnh tự vào kho tài nguyên (kind=image)", any(a["id"] == im["assetId"] and a["kind"] == "image" for a in c.get(f"/projects/{pid}/assets").json()))
sidecar = json.loads(png.with_suffix(".png.json").read_text(encoding="utf-8"))
check("nhãn 'AI tạo' đi kèm ảnh", sidecar.get("ai_generated") is True and sidecar["seed"] == 7)

cmd("video", "set-brief", {"brief": {"asset": im["assetId"], "preset": "pan-right", "duration": 5, "aspect": "9:16", "quality": 720}})
t0 = time.time()
j = wait(ok(c.post(f"/projects/{pid}/video/render"))["id"])
check("ảnh → video chuyển động 9:16", j["status"] == "succeeded", f"{time.time() - t0:.0f}s {j.get('error') or ''}")
d = probe(pdir / j["result"]["path"])
v = next(s for s in d["streams"] if s["codec_type"] == "video")
check("video 720×1280, dài 5 s", (v["width"], v["height"]) == (720, 1280) and abs(float(d["format"]["duration"]) - 5.0) < 0.2)

cmd("thumbnail", "set-brief", {"brief": {"title": "Cà phê phin thơm ngon", "subtitle": "Pha chuẩn vị tại nhà", "count": 2, "aspect": "16:9", "background": {"kind": "asset", "asset": im["assetId"]}}})
j = wait(ok(c.post(f"/projects/{pid}/thumbnail/render"))["id"])
vs = ok(c.get(f"/projects/{pid}/tools/thumbnail/state"))["state"]["variants"]
check("thumbnail tiếng Việt dùng ảnh AI làm nền", j["status"] == "succeeded" and len(vs) == 2 and all((pdir / x["file"]).stat().st_size > 20_000 for x in vs))
print(f"\nTổng thời gian {time.time() - t_all:.0f}s | project {pid}")
bad = [n for n, k in results if not k]
print(f"{len(results) - len(bad)}/{len(results)} đạt", ("— LỖI: " + "; ".join(bad)) if bad else "")
sys.exit(1 if bad else 0)
