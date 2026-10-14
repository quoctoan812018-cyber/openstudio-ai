"""Nghiệm thu GĐ6B: chủ đề → kịch bản 2 người (qwen3 thật) → giọng VieNeu thật cho 2 người dẫn → nhạc mở/kết + nền ducking
→ loudnorm → MP3 có chương + video sóng âm + show notes. Daemon thật.

Chạy:  OPENSTUDIO_URL=http://127.0.0.1:8799 OPENSTUDIO_TOKEN=... PYTHONPATH=apps/daemon uv run --project apps/daemon python scripts/e2e_podcast.py
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
DATA = Path(os.environ.get("OPENSTUDIO_DATA_DIR", ROOT / ".runtime"))
TMP = DATA / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
c = httpx.Client(base_url=URL, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=60)
results: list[tuple[str, bool]] = []
SOURCE = """Cà phê được người Pháp đưa vào Việt Nam năm 1857. Ban đầu cây cà phê được trồng ở miền Bắc, nhưng Tây Nguyên mới là vùng trồng lớn nhất nhờ khí hậu mát và đất đỏ bazan.
Việt Nam là nước xuất khẩu cà phê lớn thứ hai thế giới, sau Brazil. Phần lớn là cà phê Robusta, vị đậm và nhiều caffeine. Cà phê trứng ra đời ở Hà Nội năm 1946 vì sữa tươi khan hiếm."""


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


def probe(path: Path, *extra: str) -> dict:
    return json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", *extra, str(path)],
                                     capture_output=True, text=True, encoding="utf-8", check=True).stdout)


def words(t: str) -> list[str]:
    return re.findall(r"[\w']+", t.lower())


def loudness(path: Path) -> tuple[float, float]:
    out = subprocess.run(["ffmpeg", "-v", "info", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True,
                         text=True, encoding="utf-8", errors="replace").stderr
    summary = out[out.rindex("Summary:"):]
    return float(re.search(r"I:\s+(-?[0-9.]+) LUFS", summary).group(1)), float(re.search(r"Peak:\s+(-?[0-9.]+) dBFS", summary).group(1))


pid = ok(c.post("/projects", json={"name": "E2E podcast"}))["id"]
cmd = f"/projects/{pid}/tools/podcast/commands"
ok(c.post(cmd, json={"type": "set-brief", "payload": {"brief": {
    "topic": "Hành trình của một ly cà phê Việt Nam", "sourceText": SOURCE, "sourceName": "ghi-chu-ca-phe.txt", "minutes": 2, "language": "vi",
    "hosts": [{"name": "Minh"}, {"name": "Lan"}]}}}))
ok(c.post(cmd, json={"type": "set-music", "payload": {"music": {"intro": "builtin", "outro": "builtin", "bed": "builtin"}}}))
t_all = time.time()
t0 = time.time()
j = wait(ok(c.post(f"/projects/{pid}/podcast/script"))["id"])
check("viết kịch bản (qwen3 thật)", j["status"] == "succeeded", f"{time.time() - t0:.0f}s {j.get('error') or ''}")
st = ok(c.get(f"/projects/{pid}/tools/podcast/state"))["state"]
script = st["script"]
turns = [t for s in script["sections"] for t in s["turns"]]
total_words = sum(len(t["text"].split()) for t in turns)
print(f"   tiêu đề: {script['title']}\n   {len(script['sections'])} chương, {len(turns)} lượt, {total_words} từ")
for s in script["sections"]:
    print(f"   § {s['title']}")
    for t in s["turns"][:3]:
        print(f"      {t['speaker']}: {t['text']}")
check("2 chương trở lên, ≥ 6 lượt nói", len(script["sections"]) >= 2 and len(turns) >= 6)
check("chỉ có hai người dẫn, cả hai đều nói", {t["speaker"] for t in turns} == {"Minh", "Lan"})
check("không còn markdown/emoji/tiền tố tên", not any(re.search(r"[*#`_]|^(Minh|Lan)\s*:", t["text"]) or re.search(r"[\U0001F300-\U0001FAFF]", t["text"]) for t in turns))
check("kịch bản bằng tiếng Việt", sum(1 for t in turns if re.search(r"[ăâđêôơưàáảãạèéẻẽẹìíỉĩịòóỏõọùúủũụỳýỷỹỵ]", t["text"].lower())) >= len(turns) * 0.8)
check("độ dài hợp lý cho 2 phút (150–700 từ)", 150 <= total_words <= 700, f"{total_words} từ")
check("có tiêu đề, tóm tắt, ý chính", bool(script["title"] and script["summary"] and script["takeaways"]))
check("bám tài liệu nguồn (nhắc Tây Nguyên/Robusta/Brazil/1857/1946…)", sum(k in " ".join(t["text"] for t in turns) for k in ("Tây Nguyên", "Robusta", "Brazil", "1857", "1946", "Hà Nội", "Pháp")) >= 2)

t0 = time.time()
j = wait(ok(c.post(f"/projects/{pid}/podcast/produce"))["id"])
check("sản xuất (VieNeu + nhạc + chương + video)", j["status"] == "succeeded", f"{time.time() - t0:.0f}s {j.get('error') or ''}")
res = ok(c.get(f"/projects/{pid}/tools/podcast/state"))["state"]["result"]
base = DATA / "projects" / pid
print("   kết quả:", {k: res[k] for k in ("audio", "video", "notes", "chapters", "duration", "lead")})

d = probe(base / res["audio"], "-show_chapters")
check("MP3 stereo 48k, độ dài khớp", d["streams"][0]["channels"] == 2 and abs(float(d["format"]["duration"]) - res["duration"]) < 0.5, f"{float(d['format']['duration']):.1f}s")
check("chương được nhúng vào MP3 (đúng số chương, bắt đầu 0:00)", len(d["chapters"]) == len(script["sections"]) and float(d["chapters"][0]["start_time"]) == 0.0,
      str([(c_["tags"]["title"], c_["start_time"]) for c_ in d["chapters"]]))
lufs, peak = loudness(base / res["audio"])
check("âm lượng -16 LUFS ±1.5 và không vượt -1 dBFS", abs(lufs + 16) <= 1.5 and peak <= -0.9, f"{lufs:.1f} LUFS, đỉnh {peak:.1f} dBFS")
tl = res["timeline"]
check("lời thoại theo đúng thứ tự, không chồng", all(a["end"] <= b["start"] + 1e-6 for a, b in zip(tl, tl[1:])) and tl[0]["start"] >= res["lead"] - 0.05)
check("nhạc mở/kết kéo dài đúng", res["duration"] > tl[-1]["end"] + 4.0 and res["lead"] > 3.0, f"lead {res['lead']}s, giọng kết thúc {tl[-1]['end']:.1f}s / {res['duration']:.1f}s")
v = next(s for s in probe(base / res["video"])["streams"] if s["codec_type"] == "video")
check("video sóng âm 1280x720", (v["width"], v["height"]) == (1280, 720))
md = (base / res["notes"]).read_text(encoding="utf-8")
check("show notes có tiêu đề, chương, ý chính, nguồn, kịch bản", all(k in md for k in ("# " + script["title"], "## Chương", "## Ý chính", "ghi-chu-ca-phe.txt", "## Kịch bản")))
check("chapters.txt bắt đầu 00:00", (base / res["chapters"]).read_text(encoding="utf-8").splitlines()[0].startswith("00:00 "))

# Nghe lại: nhận dạng audio thành phẩm và so với kịch bản
rt = TMP / "rt.json"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(base / res["audio"]), "-ac", "1", "-ar", "16000", str(TMP / "pod.wav")], check=True)
args = {"model_dir": str(DATA / "models/stt/faster-whisper-large-v3-turbo"), "audio": str(TMP / "pod.wav"), "language": "vi", "device": "cpu", "compute_type": "int8", "out": str(rt)}
subprocess.run([sys.executable, "-m", "openstudio.workers.stt_worker", json.dumps(args)], check=True, capture_output=True, env={**os.environ, "PYTHONPATH": str(ROOT / "apps/daemon")})
heard = " ".join(w["word"].strip() for w in json.loads(rt.read_text(encoding="utf-8"))["words"])
ratio = difflib.SequenceMatcher(None, words(" ".join(t["text"] for t in turns)), words(heard), autojunk=False).ratio()
check("nhận dạng lại bản thành phẩm (có nhạc nền) khớp kịch bản ≥ 0.80", ratio >= 0.80, f"{ratio:.3f}")
print(f"\nTổng thời gian: {time.time() - t_all:.0f}s | project: {pid} | {base / res['audio']}")
failed = [n for n, o in results if not o]
print("KẾT QUẢ:", "TẤT CẢ ĐẠT" if not failed else f"THẤT BẠI: {failed}")
sys.exit(1 if failed else 0)
