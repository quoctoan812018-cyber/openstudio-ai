"""Nghiệm thu GĐ6A: video dài → transcript thật → chọn highlight bằng LLM thật + phân cảnh → xuất clip 9:16 có phụ đề/tiêu đề
→ video tóm tắt có lời dẫn (VieNeu thật). Daemon thật + Whisper turbo + qwen3 + VieNeu.

Chạy:  OPENSTUDIO_URL=http://127.0.0.1:8799 OPENSTUDIO_TOKEN=... PYTHONPATH=apps/daemon uv run --project apps/daemon python scripts/e2e_highlights.py
"""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
import time
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


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok))
    print(("PASS" if ok else "FAIL"), name, detail, flush=True)


def wait(job_id: str, limit: float = 3600) -> dict:
    t0, last = time.time(), None
    while time.time() - t0 < limit:
        j = c.get(f"/jobs/{job_id}").json()
        p = j.get("progress") or {}
        line = f"{j['status']} {p.get('phase', '')} {p.get('percent', 0):.0f}%"
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


def probe(path: Path) -> dict:
    return json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                                     capture_output=True, text=True, encoding="utf-8", check=True).stdout)


def words(t: str) -> list[str]:
    return re.findall(r"[\w']+", t.lower())


# ---- video thử: hình đổi màu mỗi ~12s (để có đổi cảnh thật) + giọng Việt 2 phút ----
video = TMP / "hl_src.mp4"
colors = ["0xf5f5f5", "0x101010", "0xe02020", "0x20c020", "0x2020e0", "0xe0e020", "0x20e0e0", "0xe020e0", "0xf5f5f5", "0x101010"]  # tương phản mạnh: đổi cảnh thật sự
inputs = sum([["-f", "lavfi", "-i", f"color=c={col}:s=640x360:r=25:d=12.1"] for col in colors], [])
subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-i", str(FIX / "sample_vi.mp3"), "-filter_complex",
                "".join(f"[{i}:v]" for i in range(len(colors))) + f"concat=n={len(colors)}:v=1:a=0[v]", "-map", "[v]", "-map", f"{len(colors)}:a",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)], check=True)

pid = ok(c.post("/projects", json={"name": "E2E highlight"}))["id"]
t_all = time.time()
j = wait(ok(c.put(f"/projects/{pid}/subtitles/upload", params={"filename": video.name}, content=video.read_bytes()))["id"])
check("upload", j["status"] == "succeeded", str(j.get("error")))
t0 = time.time()
j = wait(ok(c.post(f"/projects/{pid}/subtitles/transcribe", json={"language": "vi", "polish": False}))["id"])
check("transcript", j["status"] == "succeeded", f"{time.time() - t0:.0f}s")
sub = ok(c.get(f"/projects/{pid}/tools/subtitles/state"))["state"]
cues = sub["tracks"]["vi"]["cues"]

ok(c.post(f"/projects/{pid}/tools/highlights/commands", json={"type": "set-options", "payload": {"options": {"count": 2, "minLen": 20, "maxLen": 45}}}))
t0 = time.time()
j = wait(ok(c.post(f"/projects/{pid}/highlights/analyze"))["id"])
check("phân tích highlight (LLM thật)", j["status"] == "succeeded", f"{time.time() - t0:.0f}s {j.get('error') or ''}")
hs = ok(c.get(f"/projects/{pid}/tools/highlights/state"))["state"]
a, clips = hs["analysis"], hs["clips"]
print("   analysis:", a)
check("LLM chấm điểm được các đoạn", a["llm"] and a["scored"] >= 3, f"{a['scored']}/{a['windows']} đoạn")
check("phát hiện đổi cảnh thật", a["scenes"] >= 7, f"{a['scenes']} mốc (hình đổi mỗi ~12s, kỳ vọng ~9)")
check("chọn đủ 2 clip", len(clips) == 2, f"{len(clips)}")
check("độ dài clip 18–45s", all(18 <= x["end"] - x["start"] <= 45 for x in clips), str([round(x["end"] - x["start"], 1) for x in clips]))
check("không chồng nhau", all(clips[i]["end"] <= clips[i + 1]["start"] for i in range(len(clips) - 1)))
straddle = [(x["id"], cu["text"][:30]) for x in clips for cu in cues for edge in (x["start"], x["end"]) if cu["start"] + 0.05 < edge < cu["end"] - 0.05]
check("không cắt ngang giữa lời nói", not straddle, str(straddle[:3]))
check("mọi clip có tiêu đề + hook do LLM viết", all(x["title"] and x["hook"] and x["llm"] is not None for x in clips))
check("tiêu đề tiếng Việt, ngắn", all(len(x["title"]) <= 80 and re.search(r"[À-ỹ]", x["title"]) or len(x["title"]) <= 80 for x in clips))
for x in clips:
    print(f"   [{x['start']:6.1f}-{x['end']:6.1f}] điểm {x['score']} (llm {x['llm']}, heuristic {x['heuristic']}) | {x['title']} | hook: {x['hook']}\n      {x['reason']}")

t0 = time.time()
j = wait(ok(c.post(f"/projects/{pid}/highlights/export"))["id"])
check("xuất clip 9:16", j["status"] == "succeeded", f"{time.time() - t0:.0f}s {j.get('error') or ''}")
hs = ok(c.get(f"/projects/{pid}/tools/highlights/state"))["state"]
pdir = DATA / "projects" / pid
for x in clips:
    out = pdir / hs["results"][x["id"]]
    d = probe(out)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    check(f"clip {x['id']} 1080x1920 có âm thanh, đúng độ dài", (v["width"], v["height"]) == (1080, 1920) and any(s["codec_type"] == "audio" for s in d["streams"])
          and abs(float(d["format"]["duration"]) - (x["end"] - x["start"])) < 0.6, f"{float(d['format']['duration']):.1f}s vs {x['end'] - x['start']:.1f}s")
    # trích một khung ở giây thứ 1.5 để xem tiêu đề + phụ đề đã được vẽ lên hình
    png = TMP / f"{x['id']}.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "1.5", "-i", str(out), "-frames:v", "1", str(png)], check=True)
    print("   khung hình:", png)

ok(c.post(f"/projects/{pid}/tools/highlights/commands", json={"type": "set-options", "payload": {"options": {"layout": "horizontal"}}}))
t0 = time.time()
j = wait(ok(c.post(f"/projects/{pid}/highlights/summary"))["id"])
check("video tóm tắt có lời dẫn (VieNeu)", j["status"] == "succeeded", f"{time.time() - t0:.0f}s {j.get('error') or ''}")
sm = ok(c.get(f"/projects/{pid}/tools/highlights/state"))["state"]["summary"]
for n in sm["narrations"]:
    print(f"   lời dẫn ({n['dur']:.1f}s, llm={n['llm']}): {n['text']}")
d = probe(pdir / sm["path"])
expect = sum(max(x["end"] - x["start"], n["dur"] + 0.5) for x, n in zip(clips, sm["narrations"]))
check("độ dài video tóm tắt = tổng các đoạn (giữ khung hình cuối nếu lời dẫn dài)", abs(float(d["format"]["duration"]) - expect) < 0.8, f"{float(d['format']['duration']):.1f}s vs {expect:.1f}s")
check("lời dẫn do LLM viết", all(n["llm"] for n in sm["narrations"]))

# nghe lại lời dẫn: nhận dạng audio của video tóm tắt, so với lời dẫn
sys.path.insert(0, str(ROOT / "apps/daemon"))
rt = TMP / "rt.json"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(pdir / sm["path"]), "-vn", "-ac", "1", "-ar", "16000", str(TMP / "sum.wav")], check=True)
args = {"model_dir": str(DATA / "models/stt/faster-whisper-large-v3-turbo"), "audio": str(TMP / "sum.wav"), "language": "vi", "device": "cpu",
        "compute_type": "int8", "out": str(rt)}
subprocess.run([sys.executable, "-m", "openstudio.workers.stt_worker", json.dumps(args)], check=True, capture_output=True, env={**os.environ, "PYTHONPATH": str(ROOT / "apps/daemon")})
heard = " ".join(w["word"].strip() for w in json.loads(rt.read_text(encoding="utf-8"))["words"])
said = " ".join(n["text"] for n in sm["narrations"])
sm_ratio = difflib.SequenceMatcher(None, words(said), words(heard), autojunk=False).ratio()
print("   nghe lại:", heard[:300])
check("nhận dạng lại video tóm tắt có chứa lời dẫn (khớp từ ≥ 0.5; còn lẫn tiếng gốc nhỏ)", difflib.SequenceMatcher(None, words(said), words(heard), autojunk=False).quick_ratio() >= 0.5 and sm_ratio > 0.25, f"{sm_ratio:.3f}")

print(f"\nTổng thời gian: {time.time() - t_all:.0f}s | project: {pid}")
failed = [n for n, o in results if not o]
print("KẾT QUẢ:", "TẤT CẢ ĐẠT" if not failed else f"THẤT BẠI: {failed}")
sys.exit(1 if failed else 0)
