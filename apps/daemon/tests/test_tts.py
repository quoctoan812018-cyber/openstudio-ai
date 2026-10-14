import json
import shutil
import subprocess

import pytest

from openstudio.tts.script import parse_script, speakers_of
from openstudio.tts.state import initial_state, reducer
from openstudio.errors import ApiError

from conftest import wait_job

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="cần ffmpeg")


# ---------- kịch bản ----------
def test_parse_two_speakers_pauses_and_default():
    segs = parse_script("Mở đầu không thẻ\n[Người A] Xin chào các bạn.\n[nghỉ 1.5s]\n[Người B] Chào bạn!\nDòng tiếp của B\n")
    assert [(s.speaker, s.text) for s in segs] == [
        ("default", "Mở đầu không thẻ"), ("Người A", "Xin chào các bạn."), ("Người B", "Chào bạn!"), ("Người B", "Dòng tiếp của B")]
    assert segs[1].pause_after == 1.5 and segs[0].pause_after == 0
    assert speakers_of(segs) == ["default", "Người A", "Người B"]


def test_inline_pause_splits_segment_and_units():
    segs = parse_script("[A] Một [nghỉ 500ms] hai [pause 2s] ba")
    assert [(s.text, s.pause_after) for s in segs] == [("Một", 0.5), ("hai", 2.0), ("ba", 0.0)]


def test_emotion_tag_is_not_a_speaker_and_pause_is_clamped():
    segs = parse_script("[cười] Haha thật à\n[A] ok [nghỉ 999s]")
    assert segs[0].speaker == "default" and segs[0].text.startswith("[cười]")
    assert segs[1].pause_after == 10.0


def test_empty_script_and_leading_pause():
    assert parse_script("  \n\n") == []
    segs = parse_script("[nghỉ 1s]\n[A] xin chào")
    assert segs[0].is_pause and segs[0].pause_after == 1.0 and segs[1].text == "xin chào"


# ---------- state ----------
def test_tts_reducer_validation():
    s = reducer(initial_state(), "set-script", {"text": "[A] hi", "language": "en"})
    assert s["text"] == "[A] hi" and s["language"] == "en"
    s = reducer(s, "set-voices", {"voices": {"A": "kokoro:af_heart", "B": ""}})
    assert s["voices"] == {"A": "kokoro:af_heart"}
    for bad in ({"options": {"speed": 3}}, {"options": {"format": "ogg"}}, {"options": {"x": 1}}, {"options": {"gap": 9}}):
        with pytest.raises(ApiError):
            reducer(s, "set-options", bad)
    with pytest.raises(ApiError):
        reducer(s, "set-script", {"text": 5})


def test_internal_commands_blocked_from_public_api(client):
    pid = client.post("/projects", json={"name": "x"}).json()["id"]
    r = client.post(f"/projects/{pid}/tools/tts/commands", json={"type": "_set-result", "payload": {"result": {"path": "../x"}}})
    assert r.status_code == 400


# ---------- đồng ý + nhân bản giọng ----------
def make_wav(path, seconds):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}", str(path)], check=True)
    return path.read_bytes()


def consent(client, **kw):
    body = {"kind": "voice", "subject": "Nguyễn Văn A (chính tôi)", "confirmed": True, **kw}
    return client.post("/consents", json=body)


def test_consent_requires_explicit_confirmation(client):
    r = consent(client, confirmed=False)
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONSENT_REQUIRED" and "statement" in r.json()["error"]["details"]
    assert consent(client, subject="  ").status_code == 400
    ok = consent(client)
    assert ok.status_code == 201 and ok.json()["usedBy"] is None and "đồng ý" in ok.json()["statement"]
    assert len(client.get("/consents").json()) == 1


@needs_ffmpeg
def test_clone_needs_valid_unused_consent_and_records_it(client, settings, tmp_path):
    wav = make_wav(tmp_path / "s.wav", 6)
    assert client.put("/voices/clone?name=Giọng&consentId=cns_nope&engine=fake", content=wav).status_code == 409
    cid = consent(client).json()["id"]
    r = client.put(f"/voices/clone?name=Giọng%20của%20tôi&consentId={cid}&engine=fake", content=wav)
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["id"].startswith("clone:") and v["kind"] == "clone" and v["consentId"] == cid
    rec = json.loads((settings.data_dir / "consent" / f"{cid}.json").read_text(encoding="utf-8"))
    assert rec["voiceId"] == v["id"].removeprefix("clone:") and len(rec["sampleSha256"]) == 64 and rec["subject"].startswith("Nguyễn")
    # dùng lại cùng consent → bị từ chối; consent kiểu khuôn mặt cũng không dùng được
    assert client.put(f"/voices/clone?name=B&consentId={cid}&engine=fake", content=wav).json()["error"]["code"] == "CONSENT_ALREADY_USED"
    face = consent(client, kind="face").json()["id"]
    assert client.put(f"/voices/clone?name=C&consentId={face}&engine=fake", content=wav).status_code == 409
    assert any(x["id"] == v["id"] for x in client.get("/voices").json())
    assert client.delete(f"/voices/{v['id']}").status_code == 204
    assert not any(x["id"] == v["id"] for x in client.get("/voices").json())


@needs_ffmpeg
def test_clone_sample_length_limits_leave_consent_unused(client, tmp_path):
    cid = consent(client).json()["id"]
    short = client.put(f"/voices/clone?name=A&consentId={cid}&engine=fake", content=make_wav(tmp_path / "a.wav", 1))
    assert short.status_code == 400 and "giây" in short.json()["error"]["message"]
    assert client.get("/consents").json()[0]["usedBy"] is None  # lỗi mẫu không làm "cháy" bản đồng ý
    assert client.put(f"/voices/clone?name=A&consentId={cid}&engine=fake", content=b"").status_code == 400


def test_clone_rejects_engine_without_clone_support(client):
    cid = consent(client).json()["id"]
    assert client.put(f"/voices/clone?name=A&consentId={cid}&engine=kokoro", content=b"x").status_code == 400


# ---------- tổng hợp ----------
def setup_script(client, text, voices, options=None, language="xx"):
    pid = client.post("/projects", json={"name": "Giọng đọc"}).json()["id"]
    base = f"/projects/{pid}/tools/tts/commands"
    client.post(base, json={"type": "set-script", "payload": {"text": text, "language": language}})
    client.post(base, json={"type": "set-voices", "payload": {"voices": voices}})
    if options:
        client.post(base, json={"type": "set-options", "payload": {"options": options}})
    return pid


def probe_json(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", str(path)], capture_output=True,
                         text=True, encoding="utf-8", check=True).stdout
    return json.loads(out)["format"]


SCRIPT = "[Người A] Xin chào các bạn hôm nay\n[nghỉ 1s]\n[Người B] Chào bạn rất vui được gặp\nVà hẹn gặp lại các bạn"


@needs_ffmpeg
def test_synthesize_two_speakers_with_pause_and_ai_label(client, settings):
    pid = setup_script(client, SCRIPT, {"Người A": "fake:a", "Người B": "fake:b"})
    job = client.post(f"/projects/{pid}/tts/synthesize").json()
    done = wait_job(client, job["id"], 60)
    assert done["status"] == "succeeded", done
    res = done["result"]
    segs = res["segments"]
    assert [s["speaker"] for s in segs] == ["Người A", "Người B", "Người B"]
    assert all(segs[i]["end"] <= segs[i + 1]["start"] for i in range(len(segs) - 1))
    assert segs[1]["start"] - segs[0]["end"] >= 1.0  # [nghỉ 1s] được tôn trọng
    out = settings.projects_dir / pid / res["path"]
    fmt = probe_json(out)
    assert abs(float(fmt["duration"]) - res["duration"]) < 0.6
    assert "AI-generated" in fmt["tags"].get("comment", "")
    st = client.get(f"/projects/{pid}/tools/tts/state").json()["state"]
    assert st["result"]["path"] == res["path"]


@needs_ffmpeg
def test_speed_option_and_mp3_export(client, settings):
    text = "[A] một hai ba bốn năm sáu bảy tám chín mười"
    fast = setup_script(client, text, {"A": "fake:a"}, {"speed": 1.5, "format": "mp3"})
    normal = setup_script(client, text, {"A": "fake:a"})
    rf = wait_job(client, client.post(f"/projects/{fast}/tts/synthesize").json()["id"], 60)["result"]
    rn = wait_job(client, client.post(f"/projects/{normal}/tts/synthesize").json()["id"], 60)["result"]
    assert rf["path"].endswith(".mp3") and rn["path"].endswith(".wav")
    assert rf["duration"] < rn["duration"] * 0.8


@needs_ffmpeg
def test_cloned_voice_is_used_for_synthesis(client, tmp_path):
    cid = consent(client).json()["id"]
    v = client.put(f"/voices/clone?name=Của%20tôi&consentId={cid}&engine=fake", content=make_wav(tmp_path / "s.wav", 5)).json()
    pid = setup_script(client, "[A] xin chào các bạn", {"A": v["id"]})
    done = wait_job(client, client.post(f"/projects/{pid}/tts/synthesize").json()["id"], 60)
    assert done["status"] == "succeeded" and done["result"]["segments"][0]["voice"] == v["id"]


def test_missing_model_returns_424_with_model_id(client):
    pid = setup_script(client, "[A] hello", {"A": "kokoro:af_heart"}, language="en")
    r = client.post(f"/projects/{pid}/tts/synthesize")
    assert r.status_code == 424 and r.json()["error"]["details"]["modelId"] == "kokoro-82m-onnx"


def test_bad_inputs(client):
    pid = client.post("/projects", json={"name": "x"}).json()["id"]
    assert client.post(f"/projects/{pid}/tts/synthesize").status_code == 400  # kịch bản trống
    setup = setup_script(client, "[A] hi", {"A": "nonsense"})
    assert client.post(f"/projects/{setup}/tts/synthesize").status_code == 400
    assert client.post(f"/projects/{pid}/tts/preview", json={"voice": "fake:a", "text": "x" * 500}).status_code == 400


@needs_ffmpeg
def test_preview_job(client, settings):
    pid = client.post("/projects", json={"name": "p"}).json()["id"]
    done = wait_job(client, client.post(f"/projects/{pid}/tts/preview", json={"voice": "fake:a", "text": "xin chào", "lang": "vi"}).json()["id"], 60)
    assert done["status"] == "succeeded" and (settings.projects_dir / pid / done["result"]["path"]).is_file()


def test_engines_and_voices_endpoints(client):
    engines = {e["id"]: e for e in client.get("/tts/engines").json()}
    assert engines["vieneu"]["clone"] and not engines["kokoro"]["clone"] and not engines["kokoro"]["available"]
    assert "fake" in engines  # chỉ hiện khi dev_fake_tts
    voices = client.get("/voices?lang=en").json()
    assert any(v["id"] == "kokoro:af_heart" for v in voices)
    vi = client.get("/voices?lang=vi").json()
    assert all(v["lang"] == "vi" for v in vi)
