"""Nghiệm thu GĐ2: file mẫu tiếng Việt 2 phút → phụ đề Việt → phụ đề Anh (daemon thật + Whisper thật + Ollama thật).

Chạy:  OPENSTUDIO_URL=http://127.0.0.1:8799 OPENSTUDIO_TOKEN=... uv run --project apps/daemon python scripts/e2e_subtitles.py
Yêu cầu: đã tải mô hình faster-whisper, Ollama đang chạy và có mô hình LLM, đã tạo apps/daemon/tests/fixtures/sample_vi.mp3.
"""
from __future__ import annotations

import difflib
import os
import re
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

URL = os.environ.get("OPENSTUDIO_URL", "http://127.0.0.1:8799")
TOKEN = os.environ["OPENSTUDIO_TOKEN"]
ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "apps/daemon/tests/fixtures/sample_vi.mp3"
REF = ROOT / "apps/daemon/tests/fixtures/sample_vi.txt"
VI_CHARS = re.compile(r"[ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]", re.I)

c = httpx.Client(base_url=URL, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=60)
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("PASS" if ok else "FAIL"), name, detail, flush=True)


def wait(job_id: str, limit: float = 1800) -> dict:
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
        time.sleep(2)
    raise TimeoutError(job_id)


def words(t: str) -> list[str]:
    return re.findall(r"\w+", t.lower())


pid = c.post("/projects", json={"name": "E2E phụ đề"}).json()["id"]
t_all = time.time()
j = wait(c.put(f"/projects/{pid}/subtitles/upload", params={"filename": SAMPLE.name}, content=SAMPLE.read_bytes()).json()["id"])
check("upload+probe", j["status"] == "succeeded", str(j.get("error")))
st = c.get(f"/projects/{pid}/tools/subtitles/state").json()["state"]
duration = st["source"]["duration"]
check("duration≈120s", 118 < duration < 122, f"{duration:.1f}s")

t0 = time.time()
r = c.post(f"/projects/{pid}/subtitles/transcribe", json={"language": "vi", "polish": True})
if r.status_code != 202:
    print(r.text)
    sys.exit(2)
j = wait(r.json()["id"])
check("transcribe+polish", j["status"] == "succeeded", f"{time.time() - t0:.0f}s {j.get('error') or ''}")
st = c.get(f"/projects/{pid}/tools/subtitles/state").json()["state"]
vi = st["tracks"]["vi"]
cues = vi["cues"]
print("   model:", vi["meta"].get("model"), "| polished:", vi["meta"].get("polished"), "| fallbacks:", vi["meta"].get("fallbacks"))

overlaps = [i for i in range(1, len(cues)) if cues[i]["start"] < cues[i - 1]["end"] - 1e-6]
check("không chồng dòng", not overlaps, f"{len(cues)} cue")
gaps = [cues[i]["start"] - cues[i - 1]["end"] for i in range(1, len(cues))]
check("không mất đoạn (khoảng trống lớn nhất < 6s)", max(gaps, default=0) < 6, f"max gap {max(gaps, default=0):.1f}s")
check("phủ đủ đầu/cuối", cues[0]["start"] < 4 and cues[-1]["end"] > duration - 8,
      f"đầu {cues[0]['start']:.1f}s, cuối {cues[-1]['end']:.1f}s / {duration:.1f}s")
check("độ dài cue hợp lý (≤ 8s, ≤ 100 ký tự)", all(x["end"] - x["start"] <= 8 and len(x["text"]) <= 100 for x in cues))
ref, hyp = words(REF.read_text(encoding="utf-8")), words(" ".join(x["text"] for x in cues))
ratio = difflib.SequenceMatcher(None, ref, hyp, autojunk=False).ratio()
check("độ khớp nội dung với kịch bản gốc ≥ 0.85", ratio >= 0.85, f"{ratio:.3f}")

t0 = time.time()
r = c.post(f"/projects/{pid}/subtitles/translate", json={"targets": ["en"], "tone": "neutral"})
if r.status_code != 202:
    print(r.text)
    sys.exit(2)
j = wait(r.json()["id"])
check("translate vi→en", j["status"] == "succeeded", f"{time.time() - t0:.0f}s {j.get('error') or ''}")
st = c.get(f"/projects/{pid}/tools/subtitles/state").json()["state"]
en = st["tracks"]["en"]
check("số cue Anh = số cue Việt", len(en["cues"]) == len(cues), f"{len(en['cues'])}/{len(cues)}")
check("thời gian giữ nguyên", all(a["start"] == b["start"] and a["end"] == b["end"] for a, b in zip(en["cues"], cues)))
left = [x for x in en["cues"] if VI_CHARS.search(x["text"])]
check("không còn dòng tiếng Việt chưa dịch", len(left) <= max(1, len(cues) // 20), f"{len(left)} dòng, fallbacks={en['meta']['fallbacks']}")

for fmt in ("srt", "vtt", "ass"):
    e = c.post(f"/projects/{pid}/subtitles/export", json={"lang": "en", "second": "vi", "format": fmt}).json()
    check(f"xuất song ngữ {fmt}", e["bytes"] > 500, e["path"])

print("\n--- mẫu (6 cue đầu) ---")
for a, b in list(zip(cues, en["cues"]))[:6]:
    print(f"[{a['start']:6.2f}-{a['end']:6.2f}] {a['text']}\n{'':15}{b['text']}")
print(f"\nTổng thời gian: {time.time() - t_all:.0f}s | project: {pid}")
failed = [n for n, ok, _ in results if not ok]
print("KẾT QUẢ:", "TẤT CẢ ĐẠT" if not failed else f"THẤT BẠI: {failed}")
sys.exit(1 if failed else 0)
