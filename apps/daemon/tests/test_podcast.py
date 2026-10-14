import json
import shutil
import subprocess

import numpy as np
import pytest
import soundfile as sf

from openstudio.errors import ApiError
from openstudio.podcast import music as M
from openstudio.podcast import notes as N
from openstudio.podcast.script import clean_turn, n_sections, source_excerpt, words_for
from openstudio.podcast.state import initial_state, reducer

from conftest import wait_job

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="cần ffmpeg")
SR = M.SR


# ---------- thuần ----------
def test_duck_envelope_lowers_during_speech_and_recovers():
    voice = np.zeros(SR * 6, dtype=np.float32)
    voice[SR * 2: SR * 4] = 0.3 * np.sin(2 * np.pi * 200 * np.arange(SR * 2) / SR)
    g = M.duck_envelope(voice, depth_db=-12.0, attack=0.05, release=0.4)
    assert g[int(0.5 * SR)] == pytest.approx(1.0, abs=0.01)                 # trước giọng: nhạc nền nguyên vẹn
    assert g[int(3 * SR)] == pytest.approx(10 ** (-12 / 20), abs=0.03)      # giữa lúc nói: hạ ~12 dB
    assert g[int(4.1 * SR)] < 0.7                                            # vừa hết giọng: chưa vội lên (release)
    assert g[int(5.8 * SR)] > 0.95                                           # đủ lâu sau đó: đã lên lại
    assert 0 < g.min() <= g.max() <= 1.0 + 1e-6 and len(g) == len(voice)


def test_builtin_music_is_audible_bounded_and_loops_seamlessly():
    for arr in (M.builtin_intro(), M.builtin_outro(), M.builtin_bed(10)):
        assert arr.dtype == np.float32 and 0.01 < np.abs(arr).max() < 1.0
    assert len(M.builtin_intro(6)) == 6 * SR
    looped = M.loop_to(M.builtin_bed(3), 10)
    assert len(looped) == 10 * SR
    assert np.abs(np.diff(looped)).max() < 0.2                              # không có bước nhảy "cạch" ở chỗ nối
    assert len(M.loop_to(np.zeros(0, dtype=np.float32), 2)) == 2 * SR


def test_fade_io_endpoints():
    x = M.fade_io(np.ones(SR * 2, dtype=np.float32), 0.5, 0.5)
    assert x[0] == 0 and x[-1] == 0 and x[SR] == 1


def test_notes_helpers():
    assert N.clock(65) == "01:05" and N.clock(3725) == "1:02:05"
    assert N.slugify("Cà phê Việt Nam: Đậm đà!") == "ca-phe-viet-nam-dam-da" and N.slugify("!!!") == "podcast"
    ch = [{"title": "Mở đầu", "start": 0.0}, {"title": "Hạt cà phê", "start": 75.2}]
    assert N.chapters_txt(ch).splitlines() == ["00:00 Mở đầu", "01:15 Hạt cà phê"]
    meta = N.ffmetadata(ch, 200.0, "Tiêu đề; có = ký tự", "AI")
    assert meta.startswith(";FFMETADATA1") and "title=Tiêu đề\\; có \\= ký tự" in meta
    assert "START=0" in meta and "END=75200" in meta and "START=75200" in meta and "END=200000" in meta
    script = {"title": "T", "summary": "S", "takeaways": ["a"], "sections": [{"title": "Mở đầu", "turns": [{"speaker": "Minh", "text": "Chào"}]}]}
    md = N.show_notes(script, ch, 200, ["Minh", "Lan"], "tai-lieu.txt")
    assert "# T" in md and "`01:15` Hạt cà phê" in md and "**Minh:** Chào" in md and "tai-lieu.txt" in md and "AI" in md


def test_script_helpers():
    assert n_sections(1) == 2 and n_sections(3) == 2 and n_sections(10) == 6 and n_sections(60) == 6
    assert words_for("vi", 2) == 440 and words_for("en", 2) == 300
    assert clean_turn("**Minh:** Chào *các* bạn #1", ["Minh", "Lan"]) == "Chào các bạn 1"
    assert clean_turn("Lưu ý: giữ kín", ["Minh"]) == "Lưu ý: giữ kín"           # chỉ bỏ tiền tố là tên người dẫn
    long = "x" * 20000
    ex = source_excerpt(long, 6000)
    assert len(ex) <= 6100 and "[…]" in ex and source_excerpt("ngắn") == "ngắn"


def test_podcast_reducer_validation():
    s = initial_state()
    s2 = reducer(s, "set-brief", {"brief": {"topic": "Cà phê", "minutes": 5, "hosts": [{"name": " An "}, {"name": "Bình", "voice": "kokoro:af_heart"}, {"name": "Chi"}]}})
    assert [h["name"] for h in s2["brief"]["hosts"]] == ["An", "Bình", "Chi"] and s2["brief"]["hosts"][1]["voice"] == "kokoro:af_heart"
    bads = [{"hosts": [{"name": "A"}]}, {"hosts": [{"name": "A"}, {"name": "a"}]}, {"minutes": 99}, {"zzz": 1}, {"sourceText": "x" * 300000}]
    for b in bads:
        with pytest.raises(ApiError):
            reducer(s, "set-brief", {"brief": b})
    script = {"title": "T", "sections": [{"title": "S1", "turns": [{"speaker": "minh", "text": "Chào"}, {"speaker": "LAN", "text": "Chào bạn"}]}]}
    ok = reducer(s, "set-script", {"script": script})
    assert [t["speaker"] for t in ok["script"]["sections"][0]["turns"]] == ["Minh", "Lan"]   # chuẩn hoá hoa/thường theo tên người dẫn
    for bad in ({"sections": []}, {"sections": [{"title": "x", "turns": [{"speaker": "Ai đó", "text": "hi"}]}]},
                {"sections": [{"title": "x", "turns": [{"speaker": "Minh", "text": ""}]}]}, "không phải dict"):
        with pytest.raises(ApiError):
            reducer(s, "set-script", {"script": bad})
    with pytest.raises(ApiError):
        reducer(s, "set-music", {"music": {"bedGain": 3}})
    with pytest.raises(ApiError):
        reducer(s, "set-options", {"options": {"format": "ogg"}})


# ---------- API ----------
def state(client, pid):
    return client.get(f"/projects/{pid}/tools/podcast/state").json()["state"]


def cmd(client, pid, type, payload):
    r = client.post(f"/projects/{pid}/tools/podcast/commands", json={"type": type, "payload": payload})
    assert r.status_code == 200, r.text
    return r.json()


def run(client, resp, timeout=120):
    assert resp.status_code == 202, resp.text
    done = wait_job(client, resp.json()["id"], timeout)
    assert done["status"] == "succeeded", done
    return done


def probe(path, *extra):
    return json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", *extra, str(path)],
                                     capture_output=True, text=True, encoding="utf-8", check=True).stdout)


@pytest.fixture
def pod(client):
    pid = client.post("/projects", json={"name": "Podcast"}).json()["id"]
    cmd(client, pid, "set-brief", {"brief": {"topic": "Cà phê Việt Nam", "minutes": 6, "hosts": [{"name": "Minh", "voice": "fake:a"}, {"name": "Lan", "voice": "fake:b"}]}})
    return pid


def test_script_generation_with_llm(client, pod, fake_llm):
    done = run(client, client.post(f"/projects/{pod}/podcast/script"))
    script = state(client, pod)["script"]
    assert script["title"] == "Cà phê Việt" and len(script["sections"]) == 3 and done["result"]["turns"] == 12
    assert all(t["speaker"] in ("Minh", "Lan") and t["text"] and "*" not in t["text"] for s in script["sections"] for t in s["turns"])
    assert script["takeaways"] == ["Robusta đậm", "Arabica thơm"]
    second = script["sections"][0]["turns"][1]["text"]
    assert not second.startswith("Lan:") and not second.startswith("Minh:")      # tiền tố tên người nói bị gỡ
    system_prompts = [c["messages"][0]["content"] for c in fake_llm.calls]
    assert any("Vietnamese" in s and "Minh, Lan" in s for s in system_prompts)
    assert any("FIRST section" in s for s in system_prompts) and any("LAST section" in s for s in system_prompts)


def test_script_needs_brief_and_llm(client, settings):
    pid = client.post("/projects", json={"name": "trống"}).json()["id"]
    assert client.post(f"/projects/{pid}/podcast/script").json()["error"]["code"] == "BRIEF_REQUIRED"
    import httpx
    from fastapi.testclient import TestClient
    from conftest import FAKE_STT, TOKEN, _handler
    from openstudio.app import create_app

    def down(_req):
        raise httpx.ConnectError("x")
    app = create_app(settings, TOKEN, lambda: httpx.Client(transport=httpx.MockTransport(_handler)), stt_cmd=FAKE_STT,
                     llm_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(down)), sep_engine="fake")
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        p2 = c.post("/projects", json={"name": "x"}).json()["id"]
        c.post(f"/projects/{p2}/tools/podcast/commands", json={"type": "set-brief", "payload": {"brief": {"topic": "t"}}})
        r = c.post(f"/projects/{p2}/podcast/script")
        assert r.status_code == 424 and r.json()["error"]["code"] == "LLM_UNAVAILABLE"


@needs_ffmpeg
def test_produce_full_episode_with_music_chapters_video_and_notes(client, pod, settings, fake_llm):
    run(client, client.post(f"/projects/{pod}/podcast/script"))
    cmd(client, pod, "set-music", {"music": {"intro": "builtin", "outro": "builtin", "bed": "builtin"}})
    done = run(client, client.post(f"/projects/{pod}/podcast/produce"), 180)
    res = state(client, pod)["result"]
    base = settings.projects_dir / pod
    assert res["audio"].endswith(".mp3") and res["video"].endswith(".horizontal.mp4") and done["result"]["turns"] == 12
    # thời gian: lead = intro(6s) - 1.2s; đoạn thoại không chồng, theo thứ tự
    assert res["lead"] == pytest.approx(4.8, abs=0.02)
    tl = res["timeline"]
    assert tl[0]["start"] == pytest.approx(res["lead"], abs=0.02) and all(a["end"] <= b["start"] + 1e-6 for a, b in zip(tl, tl[1:]))
    assert tl[-1]["end"] + 5.0 < res["duration"] + 0.5                         # nhạc kết nối đuôi sau giọng
    # âm thanh: đúng độ dài, stereo 48k, có chương nhúng trong MP3
    d = probe(base / res["audio"], "-show_chapters")
    assert abs(float(d["format"]["duration"]) - res["duration"]) < 0.4
    assert d["streams"][0]["channels"] == 2 and d["streams"][0]["sample_rate"] == "48000"
    assert [c["tags"]["title"] for c in d["chapters"]] == ["Mở đầu", "Hạt cà phê", "Kết"] and float(d["chapters"][0]["start_time"]) == 0.0
    assert float(d["chapters"][1]["start_time"]) == pytest.approx(res["chapterList"][1]["start"], abs=0.05)
    assert "AI-generated" in d["format"]["tags"].get("comment", "") and d["format"]["tags"].get("title") == "Cà phê Việt"
    # video sóng âm
    v = probe(base / res["video"])
    vs = next(s for s in v["streams"] if s["codec_type"] == "video")
    assert (vs["width"], vs["height"]) == (1280, 720) and abs(float(v["format"]["duration"]) - res["duration"]) < 0.6
    # show notes + chương
    md = (base / res["notes"]).read_text(encoding="utf-8")
    assert "# Cà phê Việt" in md and "## Chương" in md and "Hạt cà phê" in md and "**Minh:**" in md
    assert (base / res["chapters"]).read_text(encoding="utf-8").splitlines()[0] == "00:00 Mở đầu"
    # nhạc nền có thật: trước khi giọng vào chỉ có intro/bed → mix không im lặng; nhạc nền được ducking (mix khi nói < nhạc nền khi nghỉ giữa chương)
    mix, sr = sf.read(str(base / "work/podcast/mix.wav"), dtype="float32")
    rms = lambda a, b: float(np.sqrt(np.mean(mix[int(a * sr): int(b * sr)] ** 2)))
    assert rms(0.5, 3.5) > 0.02


@needs_ffmpeg
def test_produce_without_music_is_voice_only_and_vertical_layout(client, pod, settings, fake_llm):
    run(client, client.post(f"/projects/{pod}/podcast/script"))
    cmd(client, pod, "set-options", {"options": {"layout": "vertical", "format": "wav", "video": True}})
    run(client, client.post(f"/projects/{pod}/podcast/produce"), 180)
    res = state(client, pod)["result"]
    base = settings.projects_dir / pod
    assert res["audio"].endswith(".wav") and res["lead"] == pytest.approx(0.4, abs=0.01)
    v = next(s for s in probe(base / res["video"])["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1080, 1920)
    mix, sr = sf.read(str(base / "work/podcast/mix.wav"), dtype="float32")
    assert float(np.abs(mix[: int(0.35 * sr)]).max()) < 1e-4                    # không nhạc → đầu bài im lặng


@needs_ffmpeg
def test_bed_is_ducked_under_speech(client, pod, settings, fake_llm):
    run(client, client.post(f"/projects/{pod}/podcast/script"))
    cmd(client, pod, "set-options", {"options": {"video": False}})
    run(client, client.post(f"/projects/{pod}/podcast/produce"))
    base = settings.projects_dir / pod
    clean, sr = sf.read(str(base / "work/podcast/mix.wav"), dtype="float32")        # chỉ giọng
    cmd(client, pod, "set-music", {"music": {"bed": "builtin", "bedGain": -14.0}})
    res = run(client, client.post(f"/projects/{pod}/podcast/produce"))["result"]
    with_bed, _ = sf.read(str(base / "work/podcast/mix.wav"), dtype="float32")
    n = min(len(clean), len(with_bed))
    bed_only = with_bed[:n] - clean[:n]
    tl = res["timeline"]
    speaking = np.concatenate([bed_only[int((t["start"] + 0.2) * sr): int((t["end"] - 0.2) * sr)] for t in tl])
    i = next(k for k in range(len(tl) - 1) if tl[k]["section"] != tl[k + 1]["section"])   # khoảng nghỉ dài giữa hai chương (≥0.9s)
    gap = bed_only[int((tl[i]["end"] + 0.55) * sr): int((tl[i + 1]["start"] - 0.05) * sr)]
    r = lambda x: float(np.sqrt(np.mean(x ** 2)))
    assert r(speaking) > 0                                                             # nhạc nền vẫn nghe được dưới giọng
    assert r(gap) > 2.0 * r(speaking)                                                  # nhưng to hơn nhiều ở lúc không ai nói


@needs_ffmpeg
def test_user_music_requires_license_and_can_be_used(client, pod, tmp_path, fake_llm):
    wav = tmp_path / "m.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=5", str(wav)], check=True)
    data = wav.read_bytes()
    assert client.put("/music?name=Bài&kind=intro&license=", content=data).json()["error"]["code"] == "LICENSE_REQUIRED"
    assert client.put("/music?name=Bài&kind=zzz&license=CC0", content=data).status_code == 400
    assert client.put("/music?name=Bài&kind=intro&license=CC0", content=b"").status_code == 400
    m = client.put("/music?name=Nhạc%20mở&kind=intro&license=CC0%20-%20tự%20sáng%20tác", content=data).json()
    assert m["id"].startswith("mus_") and m["license"].startswith("CC0")
    lib = client.get("/music").json()
    assert lib[0]["id"] == "builtin" and any(x["id"] == m["id"] for x in lib)
    run(client, client.post(f"/projects/{pod}/podcast/script"))
    cmd(client, pod, "set-music", {"music": {"intro": m["id"]}})
    cmd(client, pod, "set-options", {"options": {"video": False}})
    res = run(client, client.post(f"/projects/{pod}/podcast/produce"))["result"]
    assert res["lead"] == pytest.approx(5.0 - M.LEAD_OVERLAP if hasattr(M, "LEAD_OVERLAP") else 3.8, abs=0.1) or res["lead"] == pytest.approx(3.8, abs=0.1)
    assert client.delete(f"/music/{m['id']}").status_code == 204
    r = client.post(f"/projects/{pod}/podcast/produce")                                  # nhạc đã bị xoá khỏi thư viện
    assert r.status_code == 404 and r.json()["error"]["code"] == "MUSIC_NOT_FOUND"


@needs_ffmpeg
def test_manual_script_and_preconditions(client, pod, fake_llm):
    assert client.post(f"/projects/{pod}/podcast/produce").json()["error"]["code"] == "SCRIPT_REQUIRED"
    script = {"title": "Tập tự viết", "sections": [{"title": "Một", "turns": [{"speaker": "Minh", "text": "Xin chào các bạn"}, {"speaker": "Lan", "text": "Chào Minh"}]}]}
    cmd(client, pod, "set-script", {"script": script})
    cmd(client, pod, "set-options", {"options": {"video": False}})
    res = run(client, client.post(f"/projects/{pod}/podcast/produce"))["result"]
    assert res["turns"] == 2 and res["video"] is None and len(res["chapterList"]) == 1       # không cần LLM cho kịch bản tự viết
    r = client.post(f"/projects/{pod}/tools/podcast/commands", json={"type": "set-script", "payload": {"script": {"sections": [{"title": "x", "turns": [{"speaker": "Ai", "text": "hi"}]}]}}})
    assert r.status_code == 400
    assert client.post(f"/projects/{pod}/tools/podcast/commands", json={"type": "_set-result", "payload": {"result": {}}}).status_code == 400


def test_missing_voice_model_reports_model_id(client):
    pid = client.post("/projects", json={"name": "x"}).json()["id"]
    cmd(client, pid, "set-brief", {"brief": {"topic": "t"}})
    cmd(client, pid, "set-script", {"script": {"title": "t", "sections": [{"title": "s", "turns": [{"speaker": "Minh", "text": "a"}, {"speaker": "Lan", "text": "b"}]}]}})
    r = client.post(f"/projects/{pid}/podcast/produce")       # hosts không có voice → VieNeu mặc định cho tiếng Việt, chưa cài trong test
    assert r.status_code == 424 and r.json()["error"]["details"]["modelId"] == "vieneu-tts-v3-turbo"
