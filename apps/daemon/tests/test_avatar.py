import json
import shutil
import subprocess

import numpy as np
import pytest

from openstudio.avatar import engine as E
from openstudio.avatar.state import initial_state, reducer
from openstudio.errors import ApiError

from conftest import wait_job

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="cần ffmpeg")
SR = 16000


def speech_like(segments):
    """[(giây, biên độ)] → tín hiệu: sin 200 Hz điều biên."""
    out = []
    for dur, amp in segments:
        t = np.arange(int(dur * SR)) / SR
        out.append((amp * np.sin(2 * np.pi * 200 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t))).astype(np.float32))
    return np.concatenate(out)


# ---------- thuần ----------
def test_envelope_silence_closed_speech_open_and_smoothed():
    e = E.envelope(speech_like([(1.0, 0.0), (1.5, 0.5), (1.0, 0.0)]), SR)
    assert len(e) == 88 or abs(len(e) - 88) <= 1
    assert e[:20].max() == 0.0                                  # im lặng → miệng đóng
    assert e[35:55].mean() > 0.4                                # đang nói → mở
    assert e[-10:].max() < 0.2                                  # hết nói → khép lại
    assert np.abs(np.diff(e)).max() < 0.6                       # có làm mượt, không nhảy vọt
    assert E.envelope(np.zeros(SR, np.float32), SR).max() == 0.0
    assert E.level_for(0.0) == 0 and E.level_for(1.0) == E.LEVELS - 1 and E.level_for(5) == E.LEVELS - 1


def test_mouth_levels_open_darkens_mouth_region_only():
    img = np.full((200, 160, 3), 200, np.uint8)
    lv = E.mouth_levels(img, {"x": 0.5, "y": 0.7, "w": 0.2})
    assert len(lv) == E.LEVELS and (lv[0] == img).all()          # mức 0 = ảnh gốc
    mouth = lambda a: a[130:150, 70:90].mean()
    assert mouth(lv[-1]) < mouth(lv[0]) - 40                     # mở to → khoang miệng tối
    assert (lv[-1][:60] == img[:60]).all()                       # xa miệng không đổi (trán/tóc)


def test_shape_masks_and_fit():
    assert E.shape_mask(40, 40, "none") is None
    c = E.shape_mask(40, 40, "circle")
    assert c[20, 20, 0] == 1 and c[0, 0, 0] == 0
    r = E.shape_mask(40, 40, "rounded")
    assert r[20, 20, 0] == 1 and r[0, 0, 0] == 0 and r[0, 20, 0] >= 0.45
    assert E.fit_size(1000, 2000, 400, 400) == (200, 400)


def test_brief_validation():
    s = reducer(initial_state(), "set-brief", {"brief": {"aspect": "9:16", "background": {"kind": "color", "color": "#112233"}}})
    assert s["brief"]["aspect"] == "9:16" and s["brief"]["background"]["color"] == "#112233"
    for bad in ({"aspect": "3:2"}, {"engine": "musetalk"}, {"frame": "star"}, {"background": {"kind": "image"}}, {"background": {"color": "red"}}, {"subtitleLang": "Việt"}, {"x": 1}):
        with pytest.raises(ApiError):
            reducer(s, "set-brief", {"brief": bad})


# ---------- API ----------
def ff(*a):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *a], check=True)


def face_png(path):
    w, h = 400, 500
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = (40, 80, 200)
    img[np.hypot(xx - 200, (yy - 250) * 0.9) < 170] = (240, 210, 60)      # mặt vàng
    img[((xx - 150) ** 2 + (yy - 200) ** 2) < 20 ** 2] = (20, 20, 20)       # mắt
    img[((xx - 250) ** 2 + (yy - 200) ** 2) < 20 ** 2] = (20, 20, 20)
    raw = path.with_suffix(".rgb")
    raw.write_bytes(img.tobytes())
    ff("-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-i", str(raw), "-frames:v", "1", str(path))


def frame_at(video, t, w, h):
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(out, np.uint8).reshape(h, w, 3)


def make_avatar(client, tmp_path, **q):
    face_png(tmp_path / "face.png")
    return client.put("/avatars", params={"name": "Mascot", **q}, content=(tmp_path / "face.png").read_bytes())


@needs_ffmpeg
def test_library_consent_rules(client, tmp_path):
    assert make_avatar(client, tmp_path).status_code == 400                                         # phải nói rõ có phải người thật không
    r = make_avatar(client, tmp_path, realPerson="true")
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONSENT_REQUIRED" and "statement" in r.json()["error"]["details"]
    voice = client.post("/consents", json={"kind": "voice", "subject": "Lan", "confirmed": True}).json()
    assert make_avatar(client, tmp_path, realPerson="true", consentId=voice["id"]).status_code == 409   # sai loại đồng ý
    assert client.post("/consents", json={"kind": "face", "subject": "Lan", "confirmed": False}).status_code == 409
    face = client.post("/consents", json={"kind": "face", "subject": "Nguyễn Văn A", "confirmed": True}).json()
    ok = make_avatar(client, tmp_path, realPerson="true", consentId=face["id"])
    assert ok.status_code == 201 and ok.json()["subject"] == "Nguyễn Văn A" and ok.json()["realPerson"]
    assert make_avatar(client, tmp_path, realPerson="true", consentId=face["id"]).status_code == 409   # mỗi đồng ý chỉ dùng một lần
    cartoon = make_avatar(client, tmp_path, realPerson="false")
    assert cartoon.status_code == 201 and cartoon.json()["consentId"] is None
    assert client.put("/avatars", params={"name": "x", "realPerson": "false"}, content=b"not an image").status_code in (400, 422)
    assert client.patch(f"/avatars/{cartoon.json()['id']}", json={"mouth": {"x": 0.5, "y": 0.6, "w": 0.2}}).json()["mouth"]["y"] == 0.6
    assert client.patch(f"/avatars/{cartoon.json()['id']}", json={"mouth": {"x": 2, "y": 0.6, "w": 0.2}}).status_code == 400
    assert client.get(f"/avatars/{cartoon.json()['id']}/image").status_code == 200
    assert len(client.get("/avatars").json()) == 2
    assert client.delete(f"/avatars/{cartoon.json()['id']}").status_code == 204


def test_engines_are_honest(client):
    es = {e["id"]: e for e in client.get("/avatar/engines").json()}
    assert es["puppet"]["implemented"] and es["puppet"]["realLipSync"] is False
    assert es["musetalk"]["implemented"] is False and es["latentsync"]["realLipSync"] is True


@needs_ffmpeg
def test_render_mouth_follows_voice_in_both_aspects(client, settings, tmp_path):
    av = make_avatar(client, tmp_path, realPerson="false", mouthX=0.5, mouthY=0.7, mouthW=0.22).json()
    sig = speech_like([(1.0, 0.0), (1.5, 0.5), (1.0, 0.0)])
    import soundfile as sf
    sf.write(str(tmp_path / "talk.wav"), sig, SR)
    pid = client.post("/projects", json={"name": "Avatar"}).json()["id"]
    assert client.post(f"/projects/{pid}/avatar/render").json()["error"]["code"] == "AVATAR_REQUIRED"
    audio = client.put(f"/projects/{pid}/assets", params={"filename": "talk.wav"}, content=(tmp_path / "talk.wav").read_bytes()).json()
    cmd = lambda p: client.post(f"/projects/{pid}/tools/avatar/commands", json={"type": "set-brief", "payload": {"brief": p}})
    assert cmd({"avatar": av["id"]}).status_code == 200
    assert client.post(f"/projects/{pid}/avatar/render").json()["error"]["code"] == "AUDIO_REQUIRED"
    assert cmd({"audio": audio["id"], "frame": "rounded", "aspect": "16:9"}).status_code == 200
    j = wait_job(client, client.post(f"/projects/{pid}/avatar/render").json()["id"], 120)
    assert j["status"] == "succeeded", j
    res = j["result"]
    video = settings.projects_dir / pid / res["path"]
    d = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(video)], capture_output=True, text=True, check=True).stdout)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1280, 720) and abs(float(d["format"]["duration"]) - 3.5) < 0.2
    assert "AI-generated" in d["format"]["tags"]["comment"] and any(s["codec_type"] == "audio" for s in d["streams"])
    closed, opened = frame_at(video, 0.5, 1280, 720).astype(int), frame_at(video, 1.9, 1280, 720).astype(int)
    diff = np.abs(closed - opened).sum(axis=2)
    assert (diff > 60).sum() > 200                                  # có thay đổi ở vùng miệng
    ys, xs = np.nonzero(diff > 350)                                  # thay đổi MẠNH = khoang miệng tối (nhịp thở chỉ gây lệch viền nhẹ)
    assert len(ys) > 100 and 430 < ys.mean() < 540 and 590 < xs.mean() < 690
    assert not (settings.projects_dir / pid / "exports/avatar/_work").exists()
    # 9:16 + khung tròn + nền màu + phụ đề thiếu → lỗi rõ
    assert cmd({"aspect": "9:16", "frame": "circle", "background": {"kind": "color", "color": "#223344"}}).status_code == 200
    j = wait_job(client, client.post(f"/projects/{pid}/avatar/render").json()["id"], 120)
    assert j["status"] == "succeeded", j
    d = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(settings.projects_dir / pid / j["result"]["path"])], capture_output=True, text=True, check=True).stdout)
    assert next((s["width"], s["height"]) for s in d["streams"] if s["codec_type"] == "video") == (720, 1280)
    assert cmd({"subtitleLang": "en"}).status_code == 200
    assert client.post(f"/projects/{pid}/tools/avatar/commands", json={"type": "_set-result", "payload": {"result": {}}}).status_code >= 400
    j = wait_job(client, client.post(f"/projects/{pid}/avatar/render").json()["id"], 60)
    assert j["status"] == "failed" and j["error"]["code"] == "TRACK_NOT_FOUND"
