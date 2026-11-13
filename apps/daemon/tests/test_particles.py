import json
import shutil
import subprocess

import numpy as np
import pytest

from openstudio.errors import ApiError
from openstudio.video import particles as P
from openstudio.video import service as VS
from openstudio.video.state import initial_state as vinit
from openstudio.video.state import reducer as vreducer

from conftest import wait_job

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="cần ffmpeg")


def test_spawn_is_deterministic_and_scales_with_density():
    a = P.spawn(10, 360, 640, density=2, origin=(0.5, 0.4), floor=0.75, seed=3)
    b = P.spawn(10, 360, 640, density=2, origin=(0.5, 0.4), floor=0.75, seed=3)
    assert len(a) == 20 and [p.x0 for p in a] == [p.x0 for p in b]
    assert [p.x0 for p in P.spawn(10, 360, 640, density=2, origin=(0.5, 0.4), floor=0.75, seed=4)] != [p.x0 for p in a]
    assert len(P.spawn(10, 360, 640, density=0.5, origin=None, floor=None, seed=1)) == 5


def test_petals_fall_land_on_floor_and_fade():
    p = P.spawn(20, 360, 640, density=1, origin=(0.5, 0.3), floor=0.75, seed=1)[5]
    assert p.pose(p.born - 0.1) is None
    y_start = p.pose(p.born)[1]
    t_land = p.born + (p.floor_y - p.y0) / p.vy
    mid = p.pose((p.born + t_land) / 2)
    assert mid[1] > y_start and mid[4] is False
    landed = p.pose(t_land + 1)
    assert landed[4] is True and landed[1] == pytest.approx(p.floor_y) and 0.75 * 640 <= p.floor_y <= 0.87 * 640
    assert landed[:2] == p.pose(t_land + 2)[:2]                      # nằm yên trên bàn
    assert p.alpha(t_land + p.stay + P.LANDED_FADE + 0.1) == 0 and p.pose(t_land + p.stay + P.LANDED_FADE + 0.1) is None


def test_frames_are_rgba_with_transparent_background_and_visible_petals():
    petals = P.spawn(2, 120, 200, density=10, origin=(0.5, 0.3), floor=0.7, seed=2)
    fr = list(P.frames(petals, 120, 200, 10, 20))
    assert len(fr) == 20 and all(len(f) == 120 * 200 * 4 for f in fr)
    last = np.frombuffer(fr[-1], np.uint8).reshape(200, 120, 4)
    assert last[..., 3].max() > 200                                  # có cánh hoa đậm
    assert (last[..., 3] == 0).mean() > 0.7                          # phần lớn trong suốt
    assert last[:20, :, 3].max() == 0                                # trên điểm phát không có cánh


def test_overlay_brief_validation_and_still_preset():
    b = vreducer(vinit(), "set-brief", {"brief": {"preset": "still", "overlay": "petals", "overlayOrigin": [0.4, 0.3], "overlayFloor": 0.7}})["brief"]
    assert b["overlay"] == "petals" and b["overlayOrigin"] == [0.4, 0.3]
    assert "z='1'" in VS.zoompan_filter("still", 50, 720, 1280, 25, 0.25)
    for bad in ({"overlay": "snow"}, {"overlayDensity": 0}, {"overlayDensity": True}, {"overlayOrigin": [0.5]},
                {"overlayOrigin": [1.5, 0.2]}, {"overlayFloor": 1.2}, {"overlayOrigin": [0.5, 0.8], "overlayFloor": 0.6},
                {"overlaySeed": -1}, {"overlaySeed": 1.5}):
        with pytest.raises(ApiError):
            vreducer(vinit(), "set-brief", {"brief": bad})


@needs_ffmpeg
def test_render_with_petal_overlay(client, settings, tmp_path):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x1d5b5b:s=360x640:d=1", "-frames:v", "1",
                    str(tmp_path / "bg.png")], check=True)
    pid = client.post("/projects", json={"name": "Petals"}).json()["id"]
    pic = client.put(f"/projects/{pid}/assets", params={"filename": "bg.png"}, content=(tmp_path / "bg.png").read_bytes()).json()
    brief = {"asset": pic["id"], "duration": 2, "preset": "still", "aspect": "9:16", "quality": 480,
             "overlay": "petals", "overlayDensity": 6, "overlayOrigin": [0.5, 0.35], "overlayFloor": 0.7}
    assert client.post(f"/projects/{pid}/tools/video/commands", json={"type": "set-brief", "payload": {"brief": brief}}).status_code == 200
    j = wait_job(client, client.post(f"/projects/{pid}/video/render").json()["id"], 120)
    assert j["status"] == "succeeded", j.get("error")
    out = settings.projects_dir / pid / j["result"]["path"]
    d = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(out)],
                                  capture_output=True, text=True, check=True).stdout)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (480, 852) and abs(float(d["format"]["duration"]) - 2.0) < 0.2
    assert j["result"]["overlay"] == "petals" and j["result"]["generative"] is False
    # khung cuối phải có điểm ảnh khác hẳn màu nền teal (cánh hoa ấm màu)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-sseof", "-0.1", "-i", str(out), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    px = np.frombuffer(raw, np.uint8).reshape(852, 480, 3).astype(int)
    assert (px[..., 0] > 150).sum() > 200
