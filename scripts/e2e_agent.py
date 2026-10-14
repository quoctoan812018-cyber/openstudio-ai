"""Nghiệm thu GĐ7: Agent chạy bằng qwen3:4b THẬT qua Ollama, gọi công cụ thật (Whisper turbo, ffmpeg…) trên daemon thật.

Kịch bản:
  A. "Tạo phụ đề tiếng Việt cho video rồi dịch sang tiếng Anh"  → phải gọi transcribe → translate, không dùng tool thừa
  B. "Cắt 2 clip ngắn dọc từ video này" → analyze → xin duyệt trước khi xuất clip (script duyệt) → clip 9:16 có thật
  C. Project TRỐNG: "Lồng tiếng video sang tiếng Anh" → phải HỎI người dùng (ask_user), không bịa/không gọi tool vô nghĩa
  D. (OPENSTUDIO_E2E_FULL=1) Podcast 2 người dẫn từ một chủ đề
Chạy:  OPENSTUDIO_URL=http://127.0.0.1:8799 OPENSTUDIO_TOKEN=... uv run --project apps/daemon python scripts/e2e_agent.py
"""
from __future__ import annotations

import json
import os
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
c = httpx.Client(base_url=URL, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=60)
results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok))
    print(("PASS" if ok else "FAIL"), name, detail, flush=True)


def ok(resp: httpx.Response) -> dict:
    if resp.status_code >= 300:
        print("HTTP", resp.status_code, resp.text[:600])
        sys.exit(2)
    return resp.json()


def wait_job(job_id: str, limit: float = 1800) -> dict:
    t0 = time.time()
    while time.time() - t0 < limit:
        j = c.get(f"/jobs/{job_id}").json()
        if j["status"] in ("succeeded", "failed", "cancelled"):
            return j
        time.sleep(2)
    raise TimeoutError(job_id)


def run_thread(pid: str, text: str, *, approve: bool = False, skill: str | None = None, limit: float = 2400) -> dict:
    """Gửi tin nhắn, in diễn tiến, (tuỳ chọn) tự duyệt các yêu cầu phê duyệt như người dùng bấm "Duyệt"."""
    tid = ok(c.post(f"/projects/{pid}/threads", json={}))["id"]
    ok(c.post(f"/threads/{tid}/messages", json={"text": text, "skill": skill}))
    t0, shown, approved = time.time(), 0, set()
    while time.time() - t0 < limit:
        th = c.get(f"/threads/{tid}").json()
        for m in th["messages"][shown:]:
            k, ct = m["kind"], m["content"]
            if k == "tool_call":
                print(f"   → {ct['tool']}({json.dumps(ct['args'], ensure_ascii=False)[:160]})  [{ct['thought'][:80]}]", flush=True)
            elif k == "tool_result":
                print(f"   ← {'ok ' if ct['ok'] else 'ERR'} {json.dumps(ct['summary'], ensure_ascii=False)[:200]}", flush=True)
            elif k in ("assistant", "question", "skill", "approval"):
                print(f"   [{k}] {json.dumps(ct, ensure_ascii=False)[:260]}", flush=True)
        shown = len(th["messages"])
        for ap in th["pendingApprovals"]:
            if approve and ap["id"] not in approved:
                approved.add(ap["id"])
                print(f"   ✔ (người dùng duyệt) {ap['tool']}", flush=True)
                ok(c.post(f"/approvals/{ap['id']}", json={"decision": "approve"}))
        if th["run"] and th["run"]["status"] in ("succeeded", "failed", "cancelled"):
            th["elapsed"] = time.time() - t0
            return th
        time.sleep(2)
    raise TimeoutError(tid)


def tools_called(th: dict) -> list[str]:
    return [m["content"]["tool"] for m in th["messages"] if m["kind"] == "tool_call"]


print("== A: phụ đề + dịch ==")
pid = ok(c.post("/projects", json={"name": "E2E agent"}))["id"]
wait_job(ok(c.put(f"/projects/{pid}/subtitles/upload", params={"filename": "sample_vi.mp3"}, content=(FIX / "sample_vi.mp3").read_bytes()))["id"])
a = run_thread(pid, "Tạo phụ đề tiếng Việt cho video này rồi dịch sang tiếng Anh nhé.")
seq = tools_called(a)
st = ok(c.get(f"/projects/{pid}/tools/subtitles/state"))["state"]
print("   thứ tự tool:", seq, f"| {a['elapsed']:.0f}s")
check("A: lượt chạy thành công", a["run"]["status"] == "succeeded", str(a["run"].get("error")))
check("A: gọi transcribe rồi translate", "subtitles_transcribe" in seq and "subtitles_translate" in seq and seq.index("subtitles_transcribe") < seq.index("subtitles_translate"), str(seq))
check("A: có bản gốc vi và bản dịch en trong state", {"vi", "en"} <= set(st.get("tracks", {})), str(list(st.get("tracks", {}))))
check("A: không tool thừa tốn tài nguyên (không burn/mix/export clip)", not set(seq) & {"subtitles_burn", "dubbing_mix", "highlights_export", "podcast_produce"})
check("A: ≤ 8 bước và không lặp vô ích", len(seq) <= 8 and len(set(map(str, seq))) >= len(seq) - 2, f"{len(seq)} bước")
final = [m for m in a["messages"] if m["kind"] == "assistant"][-1]["content"]["text"]
request_a = "Tạo phụ đề tiếng Việt cho video này rồi dịch sang tiếng Anh nhé."
check("A: câu trả lời cuối KHÔNG chép lại yêu cầu và có tệp thật", final.strip().lower() != request_a.lower() and "exports/" in final, final[:200].replace(chr(10), " | "))

print("== B: cắt clip (có duyệt) ==")
b = run_thread(pid, "Cắt 2 clip ngắn dọc từ video này để đăng TikTok.", approve=True)
seq = tools_called(b)
hs = ok(c.get(f"/projects/{pid}/tools/highlights/state"))["state"]
print("   thứ tự tool:", seq, f"| {b['elapsed']:.0f}s")
check("B: lượt chạy thành công", b["run"]["status"] == "succeeded", str(b["run"].get("error")))
check("B: phân tích trước khi xuất", "highlights_analyze" in seq and "highlights_export" in seq and seq.index("highlights_analyze") < seq.index("highlights_export"), str(seq))
aps = ok(c.get(f"/approvals?threadId={b['thread']['id']}"))
check("B: bước xuất clip đã xin duyệt và được duyệt", any(x["tool"] == "highlights_export" and x["status"] == "approved" for x in aps), str([(x["tool"], x["status"]) for x in aps]))
check("B: có clip đã xuất 9:16", bool(hs.get("results")) and all((DATA / "projects" / pid / p).is_file() for p in hs["results"].values()), str(hs.get("results")))
after_export = seq[seq.index("highlights_export") + 1:] if "highlights_export" in seq else seq
check("B: xong thì dừng (tối đa 1 bước sau khi xuất)", len(after_export) <= 1, str(after_export))
final_b = [m for m in b["messages"] if m["kind"] == "assistant"][-1]["content"]["text"]
check("B: câu trả lời cuối liệt kê đúng các clip đã xuất", "exports/clips" in final_b and all(p in final_b for p in hs.get("results", {}).values()), final_b[:200].replace(chr(10), " | "))
check("B: số clip đúng yêu cầu (2) hoặc ít hơn có giải thích", len(hs.get("clips", [])) in (1, 2) and hs.get("options", {}).get("count") in (2, 3, None), f"{len(hs.get('clips', []))} clip, count={hs.get('options', {}).get('count')}")

print("== C: project trống → phải hỏi lại ==")
pid2 = ok(c.post("/projects", json={"name": "E2E agent trống"}))["id"]
d = run_thread(pid2, "Lồng tiếng video sang tiếng Anh giúp mình.")
seq = tools_called(d)
print("   thứ tự tool:", seq, f"| {d['elapsed']:.0f}s")
check("C: lượt chạy kết thúc không lỗi", d["run"]["status"] == "succeeded", str(d["run"].get("error")))
asked = d["messages"][-1]["kind"] == "question" or "ask_user" in seq
check("C: hỏi người dùng thay vì tự làm bậy", asked, str(seq))
check("C: không gọi tool tốn tài nguyên khi chưa có nguồn", not set(seq) & {"dubbing_synthesize", "dubbing_mix", "subtitles_transcribe", "subtitles_burn"}, str(seq))

if os.environ.get("OPENSTUDIO_E2E_FULL") == "1":
    print("== D: podcast ==")
    pid3 = ok(c.post("/projects", json={"name": "E2E agent podcast"}))["id"]
    e = run_thread(pid3, "Làm một tập podcast 2 phút về hành trình của ly cà phê Việt Nam, hai người dẫn tên Minh và Lan.", approve=True)
    seq = tools_called(e)
    pod = ok(c.get(f"/projects/{pid3}/tools/podcast/state"))["state"]
    print("   thứ tự tool:", seq, f"| {e['elapsed']:.0f}s")
    check("D: brief → script → produce", all(t in seq for t in ("podcast_brief", "podcast_write_script", "podcast_produce")) and seq.index("podcast_brief") < seq.index("podcast_write_script") < seq.index("podcast_produce"), str(seq))
    check("D: có MP3 thành phẩm", bool(pod.get("result")) and (DATA / "projects" / pid3 / pod["result"]["audio"]).is_file())
    check("D: hai người dẫn Minh/Lan", [h["name"] for h in pod["brief"]["hosts"]] == ["Minh", "Lan"])

print("\nKẾT QUẢ:", "TẤT CẢ ĐẠT" if all(o for _, o in results) else "THẤT BẠI: " + str([n for n, o in results if not o]))
sys.exit(0 if all(o for _, o in results) else 1)
