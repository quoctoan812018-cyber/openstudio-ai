"""Nghiệm thu GĐ4+5 (phần chạy được trên CPU), daemon thật + VieNeu thật + FFmpeg thật:
giọng Việt (TTS) → avatar nói (puppet) 16:9 → chỉnh sửa video (avatar + thẻ tiêu đề + chữ + nhạc nền) xuất 9:16 → thumbnail từ khung hình video.

Chạy:  OPENSTUDIO_URL=http://127.0.0.1:8799 OPENSTUDIO_TOKEN=... PYTHONPATH=apps/daemon uv run --project apps/daemon python scripts/e2e_creative.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
URL = os.environ.get("OPENSTUDIO_URL", "http://127.0.0.1:8799")
TOKEN = os.environ["OPENSTUDIO_TOKEN"]
ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("OPENSTUDIO_DATA_DIR", ROOT / ".runtime"))
TMP = DATA / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
c = httpx.Client(base_url=URL, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=120)
results: list[tuple[str, bool]] = []
TEXT = ("Xin chào các bạn. Hôm nay mình sẽ chỉ cách pha một ly cà phê phin thơm ngon ngay tại nhà. "
        "Chỉ cần nước nóng chín mươi hai độ, cà phê xay vừa và một chút kiên nhẫn.")


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok))
    print(("PASS" if ok else "FAIL"), name, detail, flush=True)


def wait(job_id: str, limit: float = 1800) -> dict:
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
        time.sleep(3)
    raise TimeoutError(job_id)


def ok(resp: httpx.Response) -> dict:
    if resp.status_code >= 300:
        print("HTTP", resp.status_code, resp.text[:600])
        sys.exit(2)
    return resp.json()


def ffprobe(path: Path) -> dict:
    return json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)], capture_output=True, text=True, encoding="utf-8", check=True).stdout)


def frame(path: Path, t: float, w: int, h: int) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(int)


# ---- mascot hoạt hình (ảnh minh hoạ, không phải người thật) ----
w, h = 600, 700
yy, xx = np.mgrid[0:h, 0:w]
img = np.zeros((h, w, 3), np.uint8)
img[:] = (30, 90, 160)
img[np.hypot((xx - 300) / 1.0, (yy - 360) * 0.85) < 250] = (245, 215, 70)
for ex in (220, 380):
    img[((xx - ex) ** 2 + (yy - 290) ** 2) < 32 ** 2] = (255, 255, 255)
    img[((xx - ex) ** 2 + (yy - 295) ** 2) < 16 ** 2] = (20, 20, 20)
img[(abs(yy - 480) < 5) & (abs(xx - 300) < 70)] = (140, 50, 50)
(TMP / "mascot.rgb").write_bytes(img.tobytes())
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-i", str(TMP / "mascot.rgb"), "-frames:v", "1", str(TMP / "mascot.png")], check=True)
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=196:d=30", "-f", "lavfi", "-i", "sine=f=247:d=30", "-filter_complex", "amix=inputs=2,volume=0.4", str(TMP / "pad.wav")], check=True)

pid = ok(c.post("/projects", json={"name": "E2E sáng tạo"}))["id"]
pdir = DATA / "projects" / pid
t_all = time.time()

# ---- 1. giọng đọc thật ----
ok(c.post(f"/projects/{pid}/tools/tts/commands", json={"type": "set-script", "payload": {"text": TEXT, "language": "vi"}}))
t0 = time.time()
j = wait(ok(c.post(f"/projects/{pid}/tts/synthesize"))["id"])
check("TTS tiếng Việt (VieNeu)", j["status"] == "succeeded", f"{time.time() - t0:.0f}s {j.get('error') or ''}")
voice = j["result"]
audio = ok(c.post(f"/projects/{pid}/assets/register", json={"path": voice["path"], "name": "giong-doc"}))
check("đưa kết quả TTS vào kho tài nguyên", audio["kind"] == "audio" and audio["duration"] > 5, f"{audio['duration']:.1f}s")

# ---- 2. avatar ----
r = c.put("/avatars", params={"name": "Mascot cà phê"}, content=(TMP / "mascot.png").read_bytes())
check("tạo avatar KHÔNG khai báo người thật bị từ chối", r.status_code == 400)
r = c.put("/avatars", params={"name": "Mascot cà phê", "realPerson": "true"}, content=(TMP / "mascot.png").read_bytes())
check("avatar người thật không kèm đồng ý bị chặn", r.status_code == 409 and r.json()["error"]["code"] == "CONSENT_REQUIRED")
av = ok(c.put("/avatars", params={"name": "Mascot cà phê", "realPerson": "false", "mouthX": 0.5, "mouthY": 480 / 700, "mouthW": 0.2}, content=(TMP / "mascot.png").read_bytes()))
cmd = lambda tool, t, p: ok(c.post(f"/projects/{pid}/tools/{tool}/commands", json={"type": t, "payload": p}))
cmd("avatar", "set-brief", {"brief": {"avatar": av["id"], "audio": audio["id"], "aspect": "16:9", "frame": "rounded"}})
t0 = time.time()
j = wait(ok(c.post(f"/projects/{pid}/avatar/render"))["id"])
check("render avatar 16:9", j["status"] == "succeeded", f"{time.time() - t0:.0f}s {j.get('error') or ''}")
res = j["result"]
vid = pdir / res["path"]
d = ffprobe(vid)
v = next(s for s in d["streams"] if s["codec_type"] == "video")
check("video avatar 1280×720, dài bằng giọng đọc (±0,2s)", (v["width"], v["height"]) == (1280, 720) and abs(float(d["format"]["duration"]) - voice["duration"]) < 0.2, f"{float(d['format']['duration']):.2f}s vs {voice['duration']}s")
check("nhãn AI trong metadata", "AI-generated" in d["format"].get("tags", {}).get("comment", ""))
# miệng mở theo giọng thật: lấy mẫu 30 khung, đo độ tối vùng miệng
ay, ax = int(0.5 * 720 + 0.0), 640
dark = []
for k in range(40):
    f = frame(vid, 0.2 + k * (voice["duration"] - 0.4) / 40, 1280, 720)
    dark.append(float(f[430:520, 590:690].mean()))
dark = np.array(dark)
check("miệng đóng/mở theo giọng thật (độ tối vùng miệng biến thiên)", dark.max() - dark.min() > 8 and 0.1 < ((dark < dark.max() - 8).mean()) < 0.95, f"min={dark.min():.0f} max={dark.max():.0f}")

# ---- 3. chỉnh sửa: thẻ tiêu đề + avatar + chữ + nhạc, xuất 9:16 ----
card = TMP / "card.png"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x0b1b3a:s=1280x720:d=1", "-frames:v", "1", str(card)], check=True)
card_a = ok(c.put(f"/projects/{pid}/assets", params={"filename": card.name}, content=card.read_bytes()))
pad_a = ok(c.put(f"/projects/{pid}/assets", params={"filename": "pad.wav"}, content=(TMP / "pad.wav").read_bytes()))
vid_a = ok(c.post(f"/projects/{pid}/assets/register", json={"path": res["path"], "name": "avatar.mp4"}))
att = lambda **kw: ok(c.post(f"/projects/{pid}/editor/attach", json=kw))
att(kind="segment", assetId=card_a["id"], params={"duration": 2.5})
att(kind="segment", assetId=vid_a["id"], params={"transition": {"type": "fade", "duration": 0.6}})
att(kind="music", assetId=pad_a["id"])
cmd("editor", "set-settings", {"settings": {"aspect": "9:16", "quality": 720, "fit": "crop"}})
cmd("editor", "add-text", {"text": "Pha cà phê phin ngon tại nhà", "start": 0.2, "end": 2.4, "position": "center", "size": 6})
cmd("editor", "add-text", {"text": "Bước 1: nước 92 độ", "start": 3.5, "end": 7.0, "position": "top"})
expect = 2.5 + voice["duration"] - 0.6
t0 = time.time()
j = wait(ok(c.post(f"/projects/{pid}/editor/render", json={"preview": False}))["id"])
check("xuất video chỉnh sửa 9:16", j["status"] == "succeeded", f"{time.time() - t0:.0f}s {j.get('error') or ''}")
out = pdir / j["result"]["path"]
d = ffprobe(out)
v = next(s for s in d["streams"] if s["codec_type"] == "video")
check("video 720×1280, độ dài = tổng − phần chồng chuyển cảnh (±0,3s)", (v["width"], v["height"]) == (720, 1280) and abs(float(d["format"]["duration"]) - expect) < 0.3, f"{float(d['format']['duration']):.2f}s vs {expect:.2f}s")
f_title = frame(out, 1.0, 720, 1280)
check("chữ tiêu đề tiếng Việt được vẽ lên khung (có điểm ảnh trắng trên nền xanh đậm)", int(((f_title > 235).all(axis=2)).sum()) > 2000)
check("âm thanh: có giọng + nhạc (RMS > 0)", float(np.abs(np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-t", "6", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True, check=True).stdout, np.int16)).mean()) > 50)

# ---- 4. thumbnail từ khung hình video avatar ----
cmd("thumbnail", "set-brief", {"brief": {"title": "Pha cà phê phin ngon tại nhà", "subtitle": "Chỉ 5 phút mỗi sáng", "count": 3, "aspect": "16:9",
                                          "background": {"kind": "frame", "asset": vid_a["id"], "at": 1.5}}})
j = wait(ok(c.post(f"/projects/{pid}/thumbnail/render"))["id"])
check("render 3 thumbnail", j["status"] == "succeeded", str(j.get("error") or ""))
vs = ok(c.get(f"/projects/{pid}/tools/thumbnail/state"))["state"]["variants"]
sizes = {(ffprobe(pdir / x["file"])["streams"][0]["width"]) for x in vs}
check("3 biến thể 1280 px, khác nhau", len(vs) == 3 and sizes == {1280} and len({(pdir / x["file"]).read_bytes() for x in vs}) == 3)

print(f"\nTổng thời gian {time.time() - t_all:.0f}s | project {pid}")
bad = [n for n, k in results if not k]
print(f"{len(results) - len(bad)}/{len(results)} đạt", ("— LỖI: " + "; ".join(bad)) if bad else "")
sys.exit(1 if bad else 0)
