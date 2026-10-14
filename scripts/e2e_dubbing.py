"""Nghiệm thu GĐ3: video tiếng Việt 2 phút (có nhạc nền) → phụ đề Anh → LỒNG TIẾNG Anh bằng Kokoro, tách nền bằng Demucs,
trộn lại, ghép vào video. Chạy với daemon thật + mô hình thật (Whisper turbo, Ollama qwen3, Kokoro, Demucs).

Chạy:  OPENSTUDIO_URL=http://127.0.0.1:8799 OPENSTUDIO_TOKEN=... uv run --project apps/daemon python scripts/e2e_dubbing.py
Yêu cầu: đã tạo apps/daemon/tests/fixtures/sample_vi.mp3, đã tải faster-whisper-large-v3-turbo, kokoro-82m-onnx, demucs-htdemucs; Ollama chạy.
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
import numpy as np
import soundfile as sf

sys.stdout.reconfigure(encoding="utf-8")
URL = os.environ.get("OPENSTUDIO_URL", "http://127.0.0.1:8799")
TOKEN = os.environ["OPENSTUDIO_TOKEN"]
ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "apps/daemon/tests/fixtures"
DATA = Path(os.environ.get("OPENSTUDIO_DATA_DIR", ROOT / ".runtime"))
TMP = ROOT / ".runtime" / "tmp"
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
        print("HTTP", resp.status_code, resp.text[:500])
        sys.exit(2)
    return resp.json()


def words(t: str) -> list[str]:
    return re.findall(r"[\w']+", t.lower())


# ---- 1. dựng video thử: giọng Việt + nhạc nền tổng hợp (hợp âm) + hình testsrc ----
video = TMP / "dub_src.mp4"
subprocess.run([
    "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=121", "-i", str(FIX / "sample_vi.mp3"),
    "-f", "lavfi", "-i", "sine=f=220:d=121", "-f", "lavfi", "-i", "sine=f=277:d=121", "-f", "lavfi", "-i", "sine=f=330:d=121",
    "-filter_complex", "[3:a][4:a][2:a]amix=inputs=3:normalize=0,volume=0.10,aformat=channel_layouts=stereo[bg];"
                       "[1:a]aformat=channel_layouts=stereo[v];[v][bg]amix=inputs=2:normalize=0:duration=longest[a]",
    "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)], check=True)

pid = ok(c.post("/projects", json={"name": "E2E lồng tiếng"}))["id"]
t_all = time.time()
j = wait(ok(c.put(f"/projects/{pid}/subtitles/upload", params={"filename": video.name}, content=video.read_bytes()))["id"])
check("upload+probe", j["status"] == "succeeded", str(j.get("error")))
src_dur = ok(c.get(f"/projects/{pid}/tools/subtitles/state"))["state"]["source"]["duration"]

# ---- 2. phụ đề Việt → Anh ----
t0 = time.time()
j = wait(ok(c.post(f"/projects/{pid}/subtitles/transcribe", json={"language": "vi", "polish": True}))["id"])
check("transcribe", j["status"] == "succeeded", f"{time.time() - t0:.0f}s {j.get('error') or ''}")
t0 = time.time()
j = wait(ok(c.post(f"/projects/{pid}/subtitles/translate", json={"targets": ["en"]}))["id"])
check("translate vi→en", j["status"] == "succeeded", f"{time.time() - t0:.0f}s {j.get('error') or ''}")

# ---- 3. lồng tiếng ----
cmd = f"/projects/{pid}/tools/dubbing/commands"
ok(c.post(cmd, json={"type": "set-options", "payload": {"options": {"targetLang": "en", "keepBackground": True}}}))
plan = ok(c.post(f"/projects/{pid}/dubbing/plan"))["state"]["plan"]
check("lập kế hoạch", len(plan["items"]) >= 10, f"{len(plan['items'])} câu")

t0 = time.time()
j = wait(ok(c.post(f"/projects/{pid}/dubbing/synthesize"))["id"])
check("tổng hợp giọng + khớp thời lượng", j["status"] == "succeeded", f"{time.time() - t0:.0f}s {j.get('error') or ''}")
state = ok(c.get(f"/projects/{pid}/tools/dubbing/state"))["state"]
items = state["plan"]["items"]
stats = j["result"]["stats"]
print("   thống kê:", stats, "| llm:", j["result"]["llm"])
check("không câu nào lỗi", stats["failed"] == 0)
check("≥90% câu vừa khung thời gian", (stats["ok"] + stats["sped"]) / stats["total"] >= 0.9, f"ok={stats['ok']} sped={stats['sped']} too_long={stats['too_long']}")
fit = [it for it in items if it["status"] in ("ok", "sped")]
check("mọi câu ok/sped đều ≤ khung thời gian", all(it["finalDuration"] <= it["slot"] + 0.06 for it in fit),
      f"vi phạm: {[it['id'] for it in fit if it['finalDuration'] > it['slot'] + 0.06]}")
check("tốc độ không vượt trần 1.3x", all(it["speed"] <= 1.3 + 1e-6 for it in fit), f"max {max(it['speed'] for it in items):.2f}")

t0 = time.time()
j = wait(ok(c.post(f"/projects/{pid}/dubbing/mix"))["id"])
check("trộn + Demucs + ghép video", j["status"] == "succeeded", f"{time.time() - t0:.0f}s {j.get('error') or ''}")
res = j["result"]
print("   kết quả:", json.dumps(res, ensure_ascii=False))
pdir = DATA / "projects" / pid

# ---- 4. kiểm tra đầu ra ----
vid = pdir / res["video"]
probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(vid)],
                                  capture_output=True, text=True, encoding="utf-8", check=True).stdout)
kinds = {s["codec_type"]: s for s in probe["streams"]}
check("video giữ nguyên hình (h264 640x360), có audio aac", kinds["video"]["codec_name"] == "h264" and kinds["video"]["width"] == 640 and kinds["audio"]["codec_name"] == "aac")
check("độ dài video = nguồn (±0.3s)", abs(float(probe["format"]["duration"]) - src_dur) < 0.3, f"{float(probe['format']['duration']):.2f}s vs {src_dur:.2f}s")
check("nhãn AI trong metadata", "AI-generated" in probe["format"].get("tags", {}).get("comment", ""))

mix, sr = sf.read(str(pdir / res["audio"]), dtype="float32")
voice, sr_v = sf.read(str(pdir / "work/dub/voice.wav"), dtype="float32")
mixm = mix.mean(axis=1) if mix.ndim > 1 else mix
rms = lambda x, a, b, r: float(np.sqrt(np.mean(x[int(a * r): int(b * r)] ** 2) + 1e-12))
silent = [(max(it["end"], 0.0) + 0.05, it["end"] + 0.3) for it in items[:-1]]
gaps_bg = [rms(mixm, a, b, sr) for a, b in silent if rms(voice, a, b, sr_v) < 1e-3]
check("nhạc nền còn nghe được ở khoảng lặng của giọng", len(gaps_bg) >= 3 and np.mean(gaps_bg) > 0.003, f"RMS nền ≈ {np.mean(gaps_bg) if gaps_bg else 0:.4f} ({len(gaps_bg)} khoảng)")

# Giọng Việt gốc không còn lọt vào bản trộn: nhận dạng bản trộn bằng Whisper (tiếng Anh) rồi so với lời đã lồng
def transcribe(path: Path, lang: str) -> str:
    out = TMP / "rt.json"
    args = {"model_dir": str(DATA / "models/stt/faster-whisper-large-v3-turbo"), "audio": str(path), "language": lang, "device": "cpu",
            "compute_type": "int8", "out": str(out)}
    subprocess.run([sys.executable, "-m", "openstudio.workers.stt_worker", json.dumps(args)], check=True, capture_output=True,
                   env={**os.environ, "PYTHONPATH": str(ROOT / "apps/daemon")})
    d = json.loads(out.read_text(encoding="utf-8"))
    return " ".join(w["word"].strip() for w in d["words"])

heard = transcribe(pdir / res["audio"], "en")
said = " ".join(it["text"] for it in items)
ratio = difflib.SequenceMatcher(None, words(said), words(heard), autojunk=False).ratio()
check("nhận dạng lại bản lồng tiếng khớp lời ≥ 0.80", ratio >= 0.80, f"{ratio:.3f}")
vi_leak = transcribe(pdir / res["audio"], "vi")
leak_ratio = difflib.SequenceMatcher(None, words(" ".join(c["text"] for c in ok(c.get(f"/projects/{pid}/tools/subtitles/state"))["state"]["tracks"]["vi"]["cues"])),
                                     words(vi_leak), autojunk=False).ratio()
check("giọng Việt gốc không còn trong bản trộn (khớp < 0.30)", leak_ratio < 0.30, f"{leak_ratio:.3f}")

sys.path.insert(0, str(ROOT / "apps/daemon"))
from openstudio.subtitles import cues as C  # noqa: E402
srt = C.parse_subtitle((pdir / res["subtitles"]).read_text(encoding="utf-8-sig"))
check("phụ đề khớp giọng: đủ câu, không chồng", len(srt) == len(items) and C.validate(srt) == [], f"{len(srt)} cue")

print("\n--- mẫu 5 câu đầu ---")
for it in items[:5]:
    print(f"[{it['start']:6.2f}] slot={it['slot']:.2f}s dur={it['duration']:.2f}s x{it['speed']:.2f} {it['status']:8} {'(rút gọn) ' if it['shortened'] else ''}{it['text']}")
print(f"\nTổng thời gian: {time.time() - t_all:.0f}s | project: {pid} | video: {vid}")
failed = [n for n, o in results if not o]
print("KẾT QUẢ:", "TẤT CẢ ĐẠT" if not failed else f"THẤT BẠI: {failed}")
sys.exit(1 if failed else 0)
