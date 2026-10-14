import json
import shutil
import subprocess

import pytest

from openstudio.highlights import windows as W
from openstudio.highlights.state import initial_state, reducer
from openstudio.errors import ApiError

from conftest import wait_job

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="cần ffmpeg")


def cue(s, e, t):
    return {"start": s, "end": e, "text": t}


# 12 câu, mỗi câu 5s liền nhau: 0–60s. Câu 6–8 (30–45s) chứa "bí mật" (đoạn hay), câu 1 là lời chào.
TEXTS = ["Xin chào các bạn.", "Hôm nay nói về cà phê.", "Cà phê Robusta có vị đậm.", "Cà phê Arabica thì thơm hơn.", "Giá cả khác nhau nhiều.",
         "Bí mật của người pha chế là gì?", "Bí mật nằm ở nhiệt độ nước chính xác 92 độ.", "Đừng bao giờ dùng nước sôi hẳn!",
         "Xay hạt ngay trước khi pha.", "Bảo quản trong hộp kín.", "Tránh ánh nắng trực tiếp.", "Cảm ơn các bạn, hẹn gặp lại."]
CUES = [cue(i * 5, i * 5 + 4.8, t) for i, t in enumerate(TEXTS)]


# ---------- hàm thuần ----------
def test_sentences_merge_until_strong_end():
    out = W.to_sentences([cue(0, 1, "Cà phê"), cue(1.1, 2, "rất ngon."), cue(2.2, 3, "Tiếp theo")])
    assert [c["text"] for c in out] == ["Cà phê rất ngon.", "Tiếp theo"]


def test_windows_respect_length_and_sentence_boundaries():
    wins = W.build_windows(CUES, min_len=15, max_len=30, duration=60)
    assert wins and all(15 * 0.9 <= w["end"] - w["start"] <= 30 for w in wins)
    starts, ends = {c["start"] for c in CUES}, {c["end"] for c in CUES}
    assert all(w["start"] in starts and w["end"] in ends for w in wins)  # không cắt giữa câu


def test_scene_snapping_only_through_silence():
    # câu 5s với 0.2s lặng giữa các câu; mốc cảnh ở 29.9 (trong khoảng lặng trước câu bắt đầu 30) → được dời
    wins = W.build_windows(CUES, min_len=15, max_len=30, scenes=[29.9], duration=60)
    assert any(w["start"] == 29.9 for w in wins)
    # mốc cảnh nằm giữa lời nói (32.5) thì KHÔNG dời biên tới đó
    wins2 = W.build_windows(CUES, min_len=15, max_len=30, scenes=[32.5], duration=60)
    assert all(w["start"] != 32.5 and w["end"] != 32.5 for w in wins2)


def test_heuristic_prefers_hooks_and_penalizes_greetings():
    hook = W.heuristic_score("Bí mật của người pha chế là gì? Đừng dùng nước sôi hẳn! Chỉ cần 92 độ.", 12)
    greet = W.heuristic_score("Xin chào các bạn, hôm nay chúng ta cùng tìm hiểu. Cảm ơn các bạn, hẹn gặp lại.", 12)
    assert hook > greet and 0 <= greet <= hook <= 10
    assert W.heuristic_score("", 20) < 5


def test_select_clips_no_overlap_min_gap_and_count():
    wins = [{"id": i, "start": s, "end": e, "score": sc} for i, (s, e, sc) in enumerate(
        [(0, 30, 5), (10, 40, 9), (35, 65, 8), (44, 74, 7), (80, 110, 6)])]
    got = W.select_clips(wins, 3, min_gap=3)
    assert [w["id"] for w in got] == [1, 3, 4]            # 9 → loại (0,30)&(35,65) vì chồng/gần; rồi (44,74) và (80,110)
    assert all(a["end"] + 3 <= b["start"] for a, b in zip(got, got[1:]))
    assert len(W.select_clips(wins, 1)) == 1
    # bù thêm từ danh sách khác nhưng vẫn tránh các đoạn đã chọn
    extra = [{"id": 9, "start": 12, "end": 40, "score": 9.9}, {"id": 8, "start": 120, "end": 150, "score": 1}]
    got2 = W.select_clips(extra, 3, chosen=[wins[1]])
    assert [w["id"] for w in got2] == [1, 8]                                     # (12,40) chồng (10,40) nên bị loại


def test_clip_cues_are_shifted_and_clipped():
    out = W.clip_cues([cue(8, 12, "a"), cue(12, 14, "b"), cue(20, 21, "c")], 10, 13)
    assert out == [{"start": 0.0, "end": 2.0, "text": "a"}, {"start": 2.0, "end": 3.0, "text": "b"}]


def test_highlights_reducer_rules():
    s = initial_state()
    s = reducer(s, "_set-analysis", {"analysis": {"windows": 3}, "clips": [{"id": "c001", "start": 5, "end": 30, "title": "t", "hook": "h", "selected": True}]})
    s = reducer(s, "_set-result", {"id": "c001", "path": "exports/clips/x.mp4"})
    s2 = reducer(s, "set-clip", {"id": "c001", "selected": False})
    assert s2["results"]["c001"] and not s2["clips"][0]["selected"]  # bỏ chọn không xoá file đã xuất
    s3 = reducer(s, "set-clip", {"id": "c001", "start": 6})
    assert "c001" not in s3["results"] and s3["clips"][0]["start"] == 6   # đổi khung cắt → file cũ không còn khớp
    for bad in ({"id": "c001", "end": 6.5}, {"id": "zz"}, {"id": "c001", "start": -1}):
        with pytest.raises(ApiError):
            reducer(s, "set-clip", bad)
    s4 = reducer(s, "add-clip", {"start": 40, "end": 60, "title": "thủ công"})
    assert s4["clips"][-1]["id"] == "c002" and s4["clips"][-1]["manual"]
    assert [c["id"] for c in reducer(s4, "remove-clip", {"id": "c001"})["clips"]] == ["c002"]
    for bad in ({"options": {"count": 99}}, {"options": {"minLen": 50, "maxLen": 40}}, {"options": {"layout": "x"}}, {"options": {"zzz": 1}}):
        with pytest.raises(ApiError):
            reducer(s, "set-options", bad)
    with pytest.raises(ApiError):
        reducer(s, "_set-result", {"id": "../x", "path": "p"})


# ---------- đầu-cuối ----------
@pytest.fixture
def hl_project(client, tmp_path):
    """Video 60s 320x180 có 3 lần đổi cảnh (15/30/45s) + transcript mô phỏng."""
    def make(with_transcript=True):
        vid = tmp_path / "v.mp4"
        segs = ["color=c=red", "color=c=blue", "color=c=green", "color=c=yellow"]
        inputs = sum([["-f", "lavfi", "-i", f"{s}:s=320x180:r=10:d=15"] for s in segs], [])
        subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-f", "lavfi", "-i", "sine=frequency=400:duration=60", "-filter_complex",
                        "[0][1][2][3]concat=n=4:v=1:a=0[v]", "-map", "[v]", "-map", "4:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(vid)], check=True)
        pid = client.post("/projects", json={"name": "Highlights"}).json()["id"]
        wait_job(client, client.put(f"/projects/{pid}/subtitles/upload?filename=v.mp4", content=vid.read_bytes()).json()["id"], 60)
        if with_transcript:
            client.post(f"/projects/{pid}/tools/subtitles/commands", json={"type": "set-track", "payload": {"lang": "vi", "kind": "transcript", "cues": CUES}})
        client.post(f"/projects/{pid}/tools/highlights/commands", json={"type": "set-options", "payload": {"options": {"count": 2, "minLen": 15, "maxLen": 30}}})
        return pid
    return make


def state(client, pid):
    return client.get(f"/projects/{pid}/tools/highlights/state").json()["state"]


def run(client, resp, timeout=120):
    assert resp.status_code == 202, resp.text
    done = wait_job(client, resp.json()["id"], timeout)
    assert done["status"] == "succeeded", done
    return done


def ffprobe(path):
    return json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                                     capture_output=True, text=True, encoding="utf-8", check=True).stdout)


@needs_ffmpeg
def test_analyze_picks_the_hooky_window_with_llm_and_scene_detection(client, hl_project, fake_llm):
    pid = hl_project()
    done = run(client, client.post(f"/projects/{pid}/highlights/analyze"))
    st = state(client, pid)
    a, clips = st["analysis"], st["clips"]
    assert a["llm"] and a["scored"] > 0 and a["scenes"] >= 3 and a["windows"] >= 3
    assert 1 <= len(clips) <= 2 and all(15 * 0.9 <= c["end"] - c["start"] <= 30 for c in clips)
    best = max(clips, key=lambda c: c["score"])
    assert best["start"] < 40 and best["end"] > 30 and "Bí mật" in best["text"]       # đoạn chứa "bí mật" được chọn
    assert best["llm"] == 9 and best["title"].startswith("Tiêu đề") and best["hook"].startswith("Móc câu")
    assert all(clips[i]["end"] <= clips[i + 1]["start"] for i in range(len(clips) - 1))
    assert done["result"]["clips"] == len(clips)


@needs_ffmpeg
def test_analyze_without_llm_uses_heuristics(settings, tmp_path):
    import httpx
    from fastapi.testclient import TestClient
    from conftest import FAKE_STT, TOKEN, _handler
    from openstudio.app import create_app

    def down(_req):
        raise httpx.ConnectError("x")
    app = create_app(settings, TOKEN, lambda: httpx.Client(transport=httpx.MockTransport(_handler)), stt_cmd=FAKE_STT,
                     llm_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(down)), sep_engine="fake")
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        pid = c.post("/projects", json={"name": "x"}).json()["id"]
        wav = tmp_path / "a.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=400:duration=60", str(wav)], check=True)
        wait_job(c, c.put(f"/projects/{pid}/subtitles/upload?filename=a.wav", content=wav.read_bytes()).json()["id"], 30)
        c.post(f"/projects/{pid}/tools/subtitles/commands", json={"type": "set-track", "payload": {"lang": "vi", "kind": "transcript", "cues": CUES}})
        c.post(f"/projects/{pid}/tools/highlights/commands", json={"type": "set-options", "payload": {"options": {"count": 1, "minLen": 15, "maxLen": 30}}})
        done = wait_job(c, c.post(f"/projects/{pid}/highlights/analyze").json()["id"], 60)
        assert done["status"] == "succeeded" and done["result"]["llm"] is False and done["result"]["scenes"] == 0
        clip = c.get(f"/projects/{pid}/tools/highlights/state").json()["state"]["clips"][0]
        assert clip["llm"] is None and "heuristic" in clip["reason"].lower() and clip["start"] > 0     # không chọn đoạn chào hỏi mở đầu


@needs_ffmpeg
def test_preconditions(client, hl_project):
    empty = client.post("/projects", json={"name": "trống"}).json()["id"]
    assert client.post(f"/projects/{empty}/highlights/analyze").status_code == 409
    pid = hl_project(with_transcript=False)
    assert client.post(f"/projects/{pid}/highlights/analyze").json()["error"]["code"] == "TRANSCRIPT_REQUIRED"
    pid = hl_project()
    assert client.post(f"/projects/{pid}/highlights/export").status_code == 409          # chưa phân tích
    client.post(f"/projects/{pid}/tools/highlights/commands", json={"type": "set-options", "payload": {"options": {"minLen": 100, "maxLen": 150}}})
    assert client.post(f"/projects/{pid}/highlights/analyze").json()["error"]["code"] == "TOO_SHORT"
    assert client.post(f"/projects/{pid}/tools/highlights/commands", json={"type": "_set-analysis", "payload": {}}).status_code == 400


@needs_ffmpeg
def test_export_vertical_clips_with_subtitles_and_hook(client, hl_project, settings, fake_llm):
    pid = hl_project()
    run(client, client.post(f"/projects/{pid}/highlights/analyze"))
    clips = state(client, pid)["clips"]
    run(client, client.post(f"/projects/{pid}/highlights/export"))
    st = state(client, pid)
    assert set(st["results"]) == {c["id"] for c in clips}
    for c in clips:
        out = settings.projects_dir / pid / st["results"][c["id"]]
        d = ffprobe(out)
        v = next(s for s in d["streams"] if s["codec_type"] == "video")
        assert (v["width"], v["height"]) == (1080, 1920) and any(s["codec_type"] == "audio" for s in d["streams"])
        assert abs(float(d["format"]["duration"]) - (c["end"] - c["start"])) < 0.6
        ass = (out.parent / f"v.{c['id']}.ass").read_text(encoding="utf-8")
        assert "PlayResX: 1080" in ass and c["hook"] in ass.replace("\\N", " ") and "Dialogue: 1,0:00:00.00,0:00:03.50,Hook" in ass
        first = ass.split("Default,,0,0,0,,")[1].split("\n")[0]
        assert first.strip() != ""  # có phụ đề được burn
    # xuất chỉ một clip + bỏ hook overlay
    client.post(f"/projects/{pid}/tools/highlights/commands", json={"type": "set-options", "payload": {"options": {"hookOverlay": False, "layout": "horizontal"}}})
    run(client, client.post(f"/projects/{pid}/highlights/export", json={"ids": [clips[0]["id"]]}))
    out = settings.projects_dir / pid / state(client, pid)["results"][clips[0]["id"]]
    assert out.name.endswith(".horizontal.mp4") and (ffprobe(out)["streams"][0]["width"]) == 320
    assert "Hook,,0,0,0" not in (out.parent / f"v.{clips[0]['id']}.ass").read_text(encoding="utf-8")


@needs_ffmpeg
def test_edit_clip_invalidates_result_and_manual_clip_exports(client, hl_project, settings, fake_llm):
    pid = hl_project()
    run(client, client.post(f"/projects/{pid}/highlights/analyze"))
    run(client, client.post(f"/projects/{pid}/highlights/export"))
    cid = state(client, pid)["clips"][0]["id"]
    r = client.post(f"/projects/{pid}/tools/highlights/commands", json={"type": "set-clip", "payload": {"id": cid, "title": "Tên mới", "selected": True}})
    assert cid not in r.json()["state"]["results"] and len(r.json()["state"]["results"]) == len(state(client, pid)["clips"]) - 1
    r = client.post(f"/projects/{pid}/tools/highlights/commands", json={"type": "add-clip", "payload": {"start": 2, "end": 12, "title": "Thủ công"}})
    assert r.status_code == 200
    run(client, client.post(f"/projects/{pid}/highlights/export"))
    assert len(state(client, pid)["results"]) == len(state(client, pid)["clips"])


@needs_ffmpeg
def test_summary_video_with_narration_extends_short_clips(client, hl_project, settings, fake_llm):
    pid = hl_project()
    run(client, client.post(f"/projects/{pid}/highlights/analyze"))
    client.post(f"/projects/{pid}/tools/highlights/commands", json={"type": "set-options", "payload": {"options": {"voice": "fake:a", "layout": "horizontal"}}})
    done = run(client, client.post(f"/projects/{pid}/highlights/summary"), 180)
    summ = state(client, pid)["summary"]
    clips = [c for c in state(client, pid)["clips"] if c["selected"]]
    assert len(summ["narrations"]) == len(clips) and all(n["llm"] for n in summ["narrations"]) and summ["narrations"][0]["text"].startswith("Phần này nói về")
    out = settings.projects_dir / pid / summ["path"]
    d = ffprobe(out)
    expect = sum(max(c["end"] - c["start"], n["dur"] + 0.5) for c, n in zip(clips, summ["narrations"]))
    assert abs(float(d["format"]["duration"]) - expect) < 0.8 and abs(summ["duration"] - expect) < 0.1
    assert {s["codec_type"] for s in d["streams"]} == {"video", "audio"}
    assert (settings.projects_dir / pid / summ["script"]).read_text(encoding="utf-8").startswith("[0.0s] Phần này nói về")
    assert done["result"]["lang"] == "vi"


@needs_ffmpeg
def test_summary_requires_video_and_voice_model(client, hl_project, tmp_path):
    pid = hl_project()
    run(client, client.post(f"/projects/{pid}/highlights/analyze"))
    r = client.post(f"/projects/{pid}/highlights/summary")           # voice mặc định tiếng Việt = VieNeu, chưa cài trong test
    assert r.status_code == 424 and r.json()["error"]["details"]["modelId"] == "vieneu-tts-v3-turbo"
    audio_pid = client.post("/projects", json={"name": "a"}).json()["id"]
    wav = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=400:duration=60", str(wav)], check=True)
    wait_job(client, client.put(f"/projects/{audio_pid}/subtitles/upload?filename=a.wav", content=wav.read_bytes()).json()["id"], 30)
    client.post(f"/projects/{audio_pid}/tools/subtitles/commands", json={"type": "set-track", "payload": {"lang": "vi", "kind": "transcript", "cues": CUES}})
    assert client.post(f"/projects/{audio_pid}/highlights/summary").json()["error"]["code"] == "VIDEO_REQUIRED"
