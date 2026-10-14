import json
import shutil
import subprocess

import pytest

from openstudio.editor import render as R
from openstudio.editor.state import initial_state, reducer, seg_duration, timeline_duration
from openstudio.errors import ApiError

from conftest import wait_job

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="cần ffmpeg")


def add(s, **kw):
    base = {"asset": "a1", "kind": "video", "name": "x.mp4", "srcDuration": 10.0, "hasAudio": True}
    return reducer(s, "_add-segment", {**base, **kw})


# ---------- thuần ----------
def test_segments_speed_duration_and_transition_clamp():
    s = add(add(initial_state(), **{"in": 0, "out": 4}), **{"in": 2, "out": 6, "transition": {"type": "fade", "duration": 1.0}})
    assert [round(seg_duration(x), 2) for x in s["segments"]] == [4, 4] and timeline_duration(s["segments"]) == pytest.approx(7.0)
    s = reducer(s, "update-segment", {"id": s["segments"][1]["id"], "speed": 2.0})
    assert seg_duration(s["segments"][1]) == pytest.approx(2.0) and timeline_duration(s["segments"]) == pytest.approx(5.0)
    s = reducer(s, "update-segment", {"id": s["segments"][1]["id"], "transition": {"type": "dissolve", "duration": 3.0}})
    assert s["segments"][1]["transition"]["duration"] == pytest.approx(1.0)          # tối đa nửa đoạn ngắn hơn (2s/2)
    assert s["segments"][0]["transition"]["type"] == "none"                            # đoạn đầu không có chuyển cảnh


def test_split_move_remove_and_validation():
    s = add(initial_state(), **{"in": 0, "out": 10})
    sid = s["segments"][0]["id"]
    s = reducer(s, "split-segment", {"id": sid, "at": 4.0})
    assert [(x["in"], x["out"]) for x in s["segments"]] == [(0, 4.0), (4.0, 10)]
    s = reducer(s, "move-segment", {"id": s["segments"][1]["id"], "index": 0})
    assert s["segments"][0]["in"] == 4.0
    with pytest.raises(ApiError):
        reducer(s, "split-segment", {"id": sid, "at": 3.95})                           # sát đầu/cuối
    with pytest.raises(ApiError):
        reducer(s, "update-segment", {"id": sid, "out": 99})
    with pytest.raises(ApiError):
        reducer(s, "update-segment", {"id": sid, "speed": 9})
    with pytest.raises(ApiError):
        reducer(s, "add-text", {"text": "x", "start": 5, "end": 4})
    with pytest.raises(ApiError):
        reducer(s, "add-text", {"text": "x", "start": 0, "end": 1, "color": "red"})
    assert reducer(s, "remove-segment", {"id": sid})["segments"] != s["segments"]
    s = reducer(s, "add-text", {"text": "Xin chào", "start": 0, "end": 2})
    assert s["texts"][0]["position"] == "bottom" and s["result"] is None


def test_editing_invalidates_previous_render():
    s = add(initial_state())
    s = reducer(s, "_set-result", {"file": {"path": "a.mp4"}})
    assert s["result"]
    assert reducer(s, "set-settings", {"settings": {"aspect": "9:16"}})["result"] is None
    with pytest.raises(ApiError):
        reducer(s, "set-settings", {"settings": {"aspect": "4:3"}})


def test_atempo_chain_and_canvas():
    assert R.atempo_chain(1.0) == "" and R.atempo_chain(4.0).count("atempo") == 2 and R.atempo_chain(0.25).count("atempo") == 2
    assert R.canvas({"aspect": "16:9", "quality": 720}, False) == (1280, 720) and R.canvas({"aspect": "9:16", "quality": 720}, True) == (360, 640)


def test_build_graph_chains_xfade_and_concat():
    s = add(add(add(initial_state(), **{"in": 0, "out": 3}), **{"in": 0, "out": 3, "transition": {"type": "fade", "duration": 0.5}}), **{"in": 0, "out": 3})
    plan = R.build(s, {"a1": "/x/a.mp4"}, preview=False, ass_name=None)
    assert "xfade=transition=fade:duration=0.500:offset=2.500" in plan.graph and "concat=n=2" in plan.graph and "acrossfade" in plan.graph
    assert plan.total == pytest.approx(8.5) and plan.inputs.count("-i") == 3


# ---------- ffmpeg thật ----------
def ff(*a):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *a], check=True)


def probe(path):
    return json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                                     capture_output=True, text=True, encoding="utf-8", check=True).stdout)


def upload(client, pid, path):
    r = client.put(f"/projects/{pid}/assets", params={"filename": path.name}, content=path.read_bytes())
    assert r.status_code == 201, r.text
    return r.json()


def cmd(client, pid, type, payload):
    r = client.post(f"/projects/{pid}/tools/editor/commands", json={"type": type, "payload": payload})
    assert r.status_code == 200, r.text
    return r.json()["state"]


@needs_ffmpeg
def test_full_edit_pipeline(client, settings, tmp_path):
    ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=4", "-f", "lavfi", "-i", "sine=f=440:d=4", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tmp_path / "v.mp4"))
    ff("-f", "lavfi", "-i", "color=c=red:s=200x200:d=1", "-frames:v", "1", str(tmp_path / "logo.png"))
    ff("-f", "lavfi", "-i", "color=c=blue:s=800x600:d=1", "-frames:v", "1", str(tmp_path / "photo.png"))
    ff("-f", "lavfi", "-i", "sine=f=220:d=3", str(tmp_path / "music.wav"))
    pid = client.post("/projects", json={"name": "Edit"}).json()["id"]
    vid, logo, photo, music = (upload(client, pid, tmp_path / n) for n in ("v.mp4", "logo.png", "photo.png", "music.wav"))
    assert (vid["kind"], vid["hasAudio"], vid["width"]) == ("video", True, 640)
    assert (logo["kind"], photo["kind"], music["kind"]) == ("image", "image", "audio")
    assert client.put(f"/projects/{pid}/assets", params={"filename": "x.exe"}, content=b"abc").status_code == 400
    assert client.put(f"/projects/{pid}/assets", params={"filename": "bad.mp4"}, content=b"not media").status_code == 422

    def att(**kw):
        return client.post(f"/projects/{pid}/editor/attach", json=kw)

    assert att(kind="segment", assetId=vid["id"], params={"in": 0, "out": 3}).status_code == 200
    assert att(kind="segment", assetId=photo["id"], params={"duration": 2, "transition": {"type": "fade", "duration": 0.5}}).status_code == 200
    assert att(kind="segment", assetId=vid["id"], params={"in": 1, "out": 3}).status_code == 200
    assert att(kind="segment", assetId=music["id"]).status_code == 400                  # audio không vào track chính
    assert att(kind="overlay", assetId=logo["id"], params={"start": 0.5, "end": 3, "x": 0.9, "y": 0.05, "width": 0.15}).status_code == 200
    assert att(kind="music", assetId=music["id"]).status_code == 200
    cmd(client, pid, "set-settings", {"settings": {"aspect": "9:16", "quality": 480}})
    cmd(client, pid, "add-text", {"text": "Xin chào Việt Nam – cà phê", "start": 0.2, "end": 3.0, "position": "top"})
    expect = 3 + (2 - 0.5) + 2          # 3s + ảnh 2s (chồng 0.5s) + 2s
    j = wait_job(client, client.post(f"/projects/{pid}/editor/render", json={"preview": True}).json()["id"], 120)
    assert j["status"] == "succeeded", j
    pv = probe(settings.projects_dir / pid / j["result"]["path"])
    v = next(x for x in pv["streams"] if x["codec_type"] == "video")
    assert (v["width"], v["height"]) == (360, 640) and abs(float(pv["format"]["duration"]) - expect) < 0.3
    j = wait_job(client, client.post(f"/projects/{pid}/editor/render").json()["id"], 180)
    assert j["status"] == "succeeded", j
    out = probe(settings.projects_dir / pid / j["result"]["path"])
    v = next(x for x in out["streams"] if x["codec_type"] == "video")
    assert (v["width"], v["height"]) == (480, 852) and any(x["codec_type"] == "audio" for x in out["streams"])
    assert abs(float(out["format"]["duration"]) - expect) < 0.3
    st = client.get(f"/projects/{pid}/tools/editor/state").json()["state"]
    assert st["result"]["path"] == j["result"]["path"] and st["preview"]
    cmd(client, pid, "set-music", {"remove": True})
    assert client.get(f"/projects/{pid}/tools/editor/state").json()["state"]["result"] is None   # sửa → bản cũ hết hiệu lực


@needs_ffmpeg
def test_render_speed_and_silent_source(client, settings, tmp_path):
    ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tmp_path / "mute.mp4"))     # không có audio
    pid = client.post("/projects", json={"name": "Edit2"}).json()["id"]
    a = upload(client, pid, tmp_path / "mute.mp4")
    assert a["hasAudio"] is False
    client.post(f"/projects/{pid}/editor/attach", json={"kind": "segment", "assetId": a["id"], "params": {"in": 0, "out": 4}})
    sid = client.get(f"/projects/{pid}/tools/editor/state").json()["state"]["segments"][0]["id"]
    cmd(client, pid, "update-segment", {"id": sid, "speed": 2.0})
    j = wait_job(client, client.post(f"/projects/{pid}/editor/render", json={"preview": True}).json()["id"], 120)
    assert j["status"] == "succeeded", j
    assert abs(float(probe(settings.projects_dir / pid / j["result"]["path"])["format"]["duration"]) - 2.0) < 0.3
    empty = client.post("/projects", json={"name": "E"}).json()["id"]
    assert client.post(f"/projects/{empty}/editor/render").json()["error"]["code"] == "TIMELINE_EMPTY"
