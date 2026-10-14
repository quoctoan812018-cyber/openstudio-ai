import shutil
import subprocess

import numpy as np
import pytest
import soundfile as sf

from openstudio.dubbing import plan as P
from openstudio.dubbing.state import initial_state, reducer
from openstudio.errors import ApiError

from conftest import wait_job

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="cần ffmpeg")


def cue(s, e, t):
    return {"start": s, "end": e, "text": t}


# ---------- kế hoạch (thuần) ----------
def test_build_items_merges_unfinished_sentences_and_computes_slots():
    target = [cue(0, 2, "Initially, coffee plants were grown"), cue(2.1, 4, "in the northern provinces."), cue(6, 8, "Next sentence."),
              cue(8.2, 9, "Short.")]
    src = [cue(0, 4, "Ban đầu cây cà phê được trồng ở miền Bắc."), cue(6, 8, "Câu tiếp.")]
    items = P.build_items(target, src, total=20, min_gap=0.1, slack=0.8)
    assert [i["text"] for i in items] == ["Initially, coffee plants were grown in the northern provinces.", "Next sentence.", "Short."]
    assert items[0]["srcText"] == "Ban đầu cây cà phê được trồng ở miền Bắc."
    assert (items[0]["start"], items[0]["end"]) == (0, 4)
    assert items[0]["slot"] == pytest.approx(4.8)        # 4 + slack 0.8, còn nằm trước câu sau (6 - 0.1)
    assert items[1]["slot"] == pytest.approx(2.0 + 0.1)   # câu sau bắt đầu 8.2 → chỉ còn 0.1s dư (8.2-0.1-6=2.1)
    assert items[2]["slot"] == pytest.approx(1.6)         # câu cuối: (9 + 0.8) - 8.2


def test_build_items_does_not_merge_across_long_gap_or_strong_end():
    items = P.build_items([cue(0, 1, "One"), cue(3, 4, "Two"), cue(4.1, 5, "three.")], None, total=10)
    assert [i["text"] for i in items] == ["One", "Two three."]


def test_fit_decision_and_target_chars():
    assert P.fit_decision(1.9, 2.0, 1.3) == (1.0, "ok")
    assert P.fit_decision(2.2, 2.0, 1.3) == (1.1, "sped")
    t, st = P.fit_decision(4.0, 2.0, 1.3)
    assert st == "too_long" and t == P.HARD_MAX_SPEED
    n = P.target_chars("x" * 100, 4.0, 2.0, 1.3)
    assert 60 <= n <= 66  # 100 * (2*1.3*0.95)/4


def test_compute_starts_pushes_overlap_but_caps_it():
    it = lambda i, s, d: {"id": i, "start": s, "finalDuration": d, "audio": "a.wav"}
    out = P.compute_starts([it("a", 0, 3.0), it("b", 2.0, 1.0), it("c", 3.0, 1.0), it("d", 10, 1)], min_gap=0.1, max_push=1.0)
    assert out[0]["start"] == 0 and out[1]["start"] == pytest.approx(3.0) and out[1]["pushed"] == pytest.approx(1.0)  # đẩy bị chặn ở 1.0
    assert out[2]["start"] == pytest.approx(4.0)
    assert out[3]["start"] == 10 and out[3]["pushed"] == 0
    skipped = P.compute_starts([{"id": "x", "start": 1, "audio": None, "finalDuration": None}])
    assert skipped[0]["skipped"]


def test_dubbing_reducer_set_item_resets_only_that_item_and_validates():
    plan = {"targetLang": "en", "items": [
        {"id": "d1", "text": "a", "status": "ok", "audio": "x", "speed": 1.2, "voice": None},
        {"id": "d2", "text": "b", "status": "sped", "audio": "y", "speed": 1.1, "voice": None}]}
    s = reducer(initial_state(), "_set-plan", {"plan": plan})
    s = reducer(s, "set-item", {"id": "d1", "text": "  mới  ", "voice": "kokoro:af_heart"})
    d1, d2 = s["plan"]["items"]
    assert d1["text"] == "mới" and d1["status"] == "pending" and d1["audio"] is None and d1["voice"] == "kokoro:af_heart"
    assert d2["status"] == "sped" and d2["audio"] == "y"
    for bad in ({"id": "zz"}, {"id": "d1", "text": ""}):
        with pytest.raises(ApiError):
            reducer(s, "set-item", bad)
    with pytest.raises(ApiError):
        reducer(s, "set-options", {"options": {"maxSpeed": 2.5}})
    with pytest.raises(ApiError):
        reducer(initial_state(), "set-item", {"id": "d1"})


# ---------- đầu-cuối với TTS giả + tách nền giả ----------
def make_media(path, video=False, seconds=20):
    if video:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=25:duration={seconds}", "-f", "lavfi",
                        "-i", f"sine=frequency=500:duration={seconds}", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    else:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=500:duration={seconds}", str(path)], check=True)
    return path.read_bytes()


# Giọng giả: ~0.35 s/từ.
# A: 3 từ ≈1.05s, khung ≈3.8s → ok
# B: 12 từ ≈4.2s, khung ≈2.5s → quá dài (kể cả tăng tốc) → LLM rút gọn còn nửa số từ ≈2.1s → ok
# C: 6 từ ≈2.1s, khung ≈1.8s → tăng tốc (sped)
VI = [cue(1, 4, "Xin chào các bạn ơi nhé."), cue(6, 8, "Chúng ta cùng tìm hiểu về cà phê Việt Nam cùng tất cả các bạn hôm nay."), cue(8.6, 9.6, "Cảm ơn các bạn rất nhiều nhé.")]
EN = [cue(1, 4, "Hello dear friends."), cue(6, 8, "We will explore coffee from Vietnam together with all of you today."), cue(8.6, 9.6, "Thank you all so very much.")]


@pytest.fixture
def dub_project(client, tmp_path):
    def make(video=False):
        pid = client.post("/projects", json={"name": "Lồng tiếng"}).json()["id"]
        name = "v.mp4" if video else "a.wav"
        data = make_media(tmp_path / name, video)
        wait_job(client, client.put(f"/projects/{pid}/subtitles/upload?filename={name}", content=data).json()["id"], 30)
        cmd = f"/projects/{pid}/tools/subtitles/commands"
        client.post(cmd, json={"type": "set-track", "payload": {"lang": "vi", "kind": "transcript", "cues": VI}})
        client.post(cmd, json={"type": "set-track", "payload": {"lang": "en", "kind": "translation", "cues": EN}})
        client.post(f"/projects/{pid}/tools/dubbing/commands", json={"type": "set-options", "payload": {"options": {"targetLang": "en", "voice": "fake:a"}}})
        return pid
    return make


def run_job(client, resp, timeout=120):
    assert resp.status_code == 202, resp.text
    done = wait_job(client, resp.json()["id"], timeout)
    assert done["status"] == "succeeded", done
    return done


@needs_ffmpeg
def test_full_dubbing_flow_audio_only(client, dub_project, settings, fake_llm):
    pid = dub_project()
    plan_state = client.post(f"/projects/{pid}/dubbing/plan").json()["state"]
    assert [i["text"] for i in plan_state["plan"]["items"]] == [c["text"] for c in EN]
    syn = run_job(client, client.post(f"/projects/{pid}/dubbing/synthesize"))
    st = client.get(f"/projects/{pid}/tools/dubbing/state").json()["state"]
    items = {i["id"]: i for i in st["plan"]["items"]}
    a, b, c = items["d0001"], items["d0002"], items["d0003"]
    assert a["status"] == "ok" and a["speed"] == 1.0 and not a["shortened"]
    assert b["shortened"] and b["status"] in ("ok", "sped") and len(b["text"].split()) < len(EN[1]["text"].split())  # LLM rút gọn rồi mới khớp
    assert c["status"] == "sped" and 1.0 < c["speed"] <= 1.3
    for it in items.values():
        assert it["finalDuration"] <= it["slot"] + 0.05, it  # mọi câu vừa khung thời gian
    assert syn["result"]["stats"]["too_long"] == 0 and syn["result"]["stats"]["shortened"] == 1

    mix = run_job(client, client.post(f"/projects/{pid}/dubbing/mix"))
    res = mix["result"]
    out = settings.projects_dir / pid / res["audio"]
    info = sf.info(str(out))
    assert abs(info.frames / info.samplerate - 20.0) < 0.15 and info.channels == 2 and res["video"] is None and res["background"] is True
    # giọng nằm đúng vị trí: im lặng ở đầu, có tiếng quanh các mốc 1s / 6s / 8.6s (nhạc nền giả rất nhỏ và liên tục → so với voice.wav)
    voice, sr = sf.read(str(settings.projects_dir / pid / "work/dub/voice.wav"), dtype="float32")
    rms = lambda s, e: float(np.sqrt(np.mean(voice[int(s * sr): int(e * sr)] ** 2)))
    assert rms(0, 0.9) < 0.002 and rms(1.05, 1.9) > 0.05 and rms(4.5, 5.9) < 0.002 and rms(6.05, 6.7) > 0.05 and rms(8.65, 9.3) > 0.05
    srt = (settings.projects_dir / pid / res["subtitles"]).read_text(encoding="utf-8-sig")
    assert "Hello dear friends." in srt and b["text"] in srt  # phụ đề khớp với lời đã rút gọn
    from openstudio.subtitles import cues as C
    parsed = C.parse_subtitle(srt)
    assert len(parsed) == 3 and C.validate(parsed) == [] and parsed[0]["start"] == pytest.approx(1.0, abs=0.06)
    assert client.get(f"/projects/{pid}/tools/dubbing/state").json()["state"]["result"]["audio"] == res["audio"]


@needs_ffmpeg
def test_dub_video_is_muxed_with_new_audio_and_video_untouched(client, dub_project, settings):
    pid = dub_project(video=True)
    client.post(f"/projects/{pid}/dubbing/plan")
    client.post(f"/projects/{pid}/tools/dubbing/commands", json={"type": "set-options", "payload": {"options": {"keepBackground": False, "format": "mp3"}}})
    run_job(client, client.post(f"/projects/{pid}/dubbing/synthesize"))
    res = run_job(client, client.post(f"/projects/{pid}/dubbing/mix"))["result"]
    assert res["audio"].endswith(".mp3") and res["video"].endswith(".dub.mp4") and res["background"] is False
    out = settings.projects_dir / pid / res["video"]
    probe = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(out)], capture_output=True,
                           text=True, encoding="utf-8", check=True).stdout
    import json
    d = json.loads(probe)
    kinds = {s["codec_type"]: s for s in d["streams"]}
    assert kinds["video"]["codec_name"] == "h264" and kinds["video"]["width"] == 320 and kinds["audio"]["codec_name"] == "aac"
    assert abs(float(d["format"]["duration"]) - 20.0) < 0.3
    assert "AI-generated" in d["format"]["tags"].get("comment", "")


@needs_ffmpeg
def test_editing_one_item_resynthesizes_only_that_item(client, dub_project, settings, fake_llm):
    pid = dub_project()
    client.post(f"/projects/{pid}/dubbing/plan")
    run_job(client, client.post(f"/projects/{pid}/dubbing/synthesize"))
    before = {i["id"]: i for i in client.get(f"/projects/{pid}/tools/dubbing/state").json()["state"]["plan"]["items"]}
    r = client.post(f"/projects/{pid}/tools/dubbing/commands", json={"type": "set-item", "payload": {"id": "d0001", "text": "Hi everyone out there today"}})
    assert r.status_code == 200 and r.json()["state"]["result"] is None
    calls_before = len(fake_llm.calls)
    run_job(client, client.post(f"/projects/{pid}/dubbing/synthesize"))
    after = {i["id"]: i for i in client.get(f"/projects/{pid}/tools/dubbing/state").json()["state"]["plan"]["items"]}
    assert after["d0001"]["text"] == "Hi everyone out there today" and after["d0001"]["status"] == "ok"
    for k in ("d0002", "d0003"):  # không bị tổng hợp lại, cũng không bị áp tốc độ hai lần
        assert after[k]["audio"] == before[k]["audio"] and after[k]["finalDuration"] == before[k]["finalDuration"]
    assert len(fake_llm.calls) == calls_before  # không cần rút gọn lần này


@needs_ffmpeg
def test_too_long_without_llm_falls_back_to_max_speed_and_flags(settings, tmp_path):
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
        wait_job(c, c.put(f"/projects/{pid}/subtitles/upload?filename=a.wav", content=make_media(tmp_path / "a.wav")).json()["id"], 30)
        cmd = f"/projects/{pid}/tools/subtitles/commands"
        c.post(cmd, json={"type": "set-track", "payload": {"lang": "vi", "kind": "transcript", "cues": VI}})
        c.post(cmd, json={"type": "set-track", "payload": {"lang": "en", "kind": "translation", "cues": EN}})
        c.post(f"/projects/{pid}/tools/dubbing/commands", json={"type": "set-options", "payload": {"options": {"targetLang": "en", "voice": "fake:a"}}})
        c.post(f"/projects/{pid}/dubbing/plan")
        done = run_job(c, c.post(f"/projects/{pid}/dubbing/synthesize"))
        b = {i["id"]: i for i in c.get(f"/projects/{pid}/tools/dubbing/state").json()["state"]["plan"]["items"]}["d0002"]
        assert done["result"]["llm"] is False and b["status"] == "too_long" and b["speed"] == P.HARD_MAX_SPEED and "tối đa" in b["note"]
        assert b["finalDuration"] < b["duration"]


@needs_ffmpeg
def test_preconditions(client, dub_project):
    pid = client.post("/projects", json={"name": "trống"}).json()["id"]
    assert client.post(f"/projects/{pid}/dubbing/plan").status_code == 409                      # chưa có nguồn
    assert client.post(f"/projects/{pid}/dubbing/synthesize").status_code == 409                # chưa có plan
    assert client.post(f"/projects/{pid}/dubbing/mix").status_code == 409                       # chưa tổng hợp
    pid = dub_project()
    client.post(f"/projects/{pid}/tools/dubbing/commands", json={"type": "set-options", "payload": {"options": {"targetLang": "vi"}}})
    assert client.post(f"/projects/{pid}/dubbing/plan").status_code == 400                      # trùng ngôn ngữ gốc
    client.post(f"/projects/{pid}/tools/dubbing/commands", json={"type": "set-options", "payload": {"options": {"targetLang": "ja"}}})
    assert client.post(f"/projects/{pid}/dubbing/plan").status_code == 409                      # chưa dịch sang ja
    client.post(f"/projects/{pid}/tools/dubbing/commands", json={"type": "set-options", "payload": {"options": {"targetLang": "en"}}})
    client.post(f"/projects/{pid}/tools/subtitles/commands", json={"type": "set-track", "payload": {"lang": "vi", "kind": "transcript", "cues": VI}})
    r = client.post(f"/projects/{pid}/dubbing/plan")
    assert r.status_code == 409 and r.json()["error"]["code"] == "TRACK_STALE"                  # bản gốc vừa đổi → bản dịch cũ
    assert client.post(f"/projects/{pid}/tools/dubbing/commands", json={"type": "_set-plan", "payload": {"plan": {}}}).status_code == 400


@needs_ffmpeg
def test_mix_needs_separation_model_unless_background_off(settings, tmp_path):
    import httpx
    from fastapi.testclient import TestClient
    from conftest import FAKE_STT, TOKEN, _handler
    from openstudio.app import create_app
    app = create_app(settings, TOKEN, lambda: httpx.Client(transport=httpx.MockTransport(_handler)), stt_cmd=FAKE_STT)  # sep_engine = demucs thật
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        pid = c.post("/projects", json={"name": "x"}).json()["id"]
        wait_job(c, c.put(f"/projects/{pid}/subtitles/upload?filename=a.wav", content=make_media(tmp_path / "a.wav")).json()["id"], 30)
        cmd = f"/projects/{pid}/tools/subtitles/commands"
        c.post(cmd, json={"type": "set-track", "payload": {"lang": "vi", "kind": "transcript", "cues": VI}})
        c.post(cmd, json={"type": "set-track", "payload": {"lang": "en", "kind": "translation", "cues": EN}})
        c.post(f"/projects/{pid}/tools/dubbing/commands", json={"type": "set-options", "payload": {"options": {"targetLang": "en", "voice": "fake:a"}}})
        c.post(f"/projects/{pid}/dubbing/plan")
        run_job(c, c.post(f"/projects/{pid}/dubbing/synthesize"))
        r = c.post(f"/projects/{pid}/dubbing/mix")
        assert r.status_code == 424 and r.json()["error"]["details"]["modelId"] == "demucs-htdemucs"
        c.post(f"/projects/{pid}/tools/dubbing/commands", json={"type": "set-options", "payload": {"options": {"keepBackground": False}}})
        assert c.post(f"/projects/{pid}/dubbing/mix").status_code == 202
