import shutil
import subprocess

import pytest

from openstudio.errors import ApiError
from openstudio.thumbnail.service import _wrap, thumb_ass
from openstudio.thumbnail.state import initial_state, reducer

from conftest import wait_job

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="cần ffmpeg")


def test_brief_validation_and_variants_state():
    s = reducer(initial_state(), "set-brief", {"brief": {"title": "Cà phê Việt", "aspect": "9:16", "background": {"dim": 0.5}}})
    assert s["brief"]["aspect"] == "9:16" and s["brief"]["background"]["dim"] == 0.5 and s["brief"]["background"]["kind"] == "gradient"
    for bad in ({"aspect": "4:3"}, {"count": 0}, {"layouts": ["nope"]}, {"palettes": []}, {"title": "x" * 200}, {"background": {"kind": "asset"}}, {"brand": {"position": "mid"}}, {"x": 1}):
        with pytest.raises(ApiError):
            reducer(s, "set-brief", {"brief": bad})
    s = reducer(s, "_set-variants", {"variants": [{"id": "v1", "file": "a.png"}]})
    assert reducer(s, "select", {"id": "v1"})["selected"] == "v1"
    with pytest.raises(ApiError):
        reducer(s, "select", {"id": "zzz"})


def test_ass_keeps_vietnamese_and_wraps():
    b = {"title": "Bí quyết pha cà phê ngon tại nhà trong 5 phút", "subtitle": "Đơn giản, dễ làm, không cần máy"}
    ass = thumb_ass(b, "banner", "navy", 1280, 720)
    assert "Bí quyết" in ass and "Đơn giản" in ass and "BorderStyle" in ass and "\\N" in ass
    assert _wrap("một hai ba bốn năm sáu", 8, 2) == ["một hai", "ba bốn năm sáu"]       # dòng cuối dồn phần dư
    for lay in ("center", "left", "top"):
        assert "Dialogue" in thumb_ass(b, lay, "sun", 1080, 1920)


def ff(*a):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *a], check=True)


def png_size(path):
    import json
    d = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(path)], capture_output=True, text=True, check=True).stdout)
    return d["streams"][0]["width"], d["streams"][0]["height"]


@needs_ffmpeg
def test_render_variants_from_video_frame_and_brand(client, settings, tmp_path):
    ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tmp_path / "v.mp4"))
    ff("-f", "lavfi", "-i", "color=c=red:s=200x100:d=1", "-frames:v", "1", str(tmp_path / "logo.png"))
    pid = client.post("/projects", json={"name": "Thumb"}).json()["id"]
    up = lambda p: client.put(f"/projects/{pid}/assets", params={"filename": p.name}, content=p.read_bytes()).json()
    vid, logo = up(tmp_path / "v.mp4"), up(tmp_path / "logo.png")
    cmd = lambda t, p: client.post(f"/projects/{pid}/tools/thumbnail/commands", json={"type": t, "payload": p})
    assert client.post(f"/projects/{pid}/thumbnail/render").json()["error"]["code"] == "BRIEF_REQUIRED"
    r = cmd("set-brief", {"brief": {"title": "Bí quyết cà phê ngon", "subtitle": "Chỉ 5 phút", "count": 3, "background": {"kind": "frame", "asset": vid["id"], "at": 1.0},
                                    "brand": {"asset": logo["id"]}}})
    assert r.status_code == 200, r.text
    j = wait_job(client, client.post(f"/projects/{pid}/thumbnail/render").json()["id"], 120)
    assert j["status"] == "succeeded", j
    st = client.get(f"/projects/{pid}/tools/thumbnail/state").json()["state"]
    assert len(st["variants"]) == 3 and len({(v["layout"], v["palette"]) for v in st["variants"]}) == 3
    files = [settings.projects_dir / pid / v["file"] for v in st["variants"]]
    assert all(f.stat().st_size > 5000 for f in files) and all(png_size(f) == (1280, 720) for f in files)
    assert len({f.read_bytes() for f in files}) == 3                          # các biến thể thật sự khác nhau
    # đổi tỉ lệ + nền gradient
    cmd("set-brief", {"brief": {"aspect": "9:16", "count": 1, "background": {"kind": "gradient"}, "brand": {"asset": None}}})
    j = wait_job(client, client.post(f"/projects/{pid}/thumbnail/render").json()["id"], 120)
    assert j["status"] == "succeeded", j
    v = client.get(f"/projects/{pid}/tools/thumbnail/state").json()["state"]["variants"][0]
    assert png_size(settings.projects_dir / pid / v["file"]) == (1080, 1920)
    # nền "khung hình" mà tài nguyên là ảnh → báo lỗi rõ
    cmd("set-brief", {"brief": {"background": {"kind": "frame", "asset": logo["id"]}}})
    j = wait_job(client, client.post(f"/projects/{pid}/thumbnail/render").json()["id"], 60)
    assert j["status"] == "failed"


def test_templates_builtin_user_and_protection(client):
    ts = client.get("/templates").json()
    ids = {t["id"] for t in ts}
    assert {"thumbnail-bold", "editor-youtube", "editor-shorts"} <= ids and all(t["builtin"] for t in ts)
    assert {t["kind"] for t in client.get("/templates", params={"kind": "editor"}).json()} == {"editor"}
    made = client.post("/templates", json={"name": "Bìa của tôi", "kind": "thumbnail", "config": {"brief": {"aspect": "1:1", "count": 2}}})
    assert made.status_code == 201 and made.json()["id"] == "bia-cua-toi" and made.json()["builtin"] is False
    assert client.post("/templates", json={"name": "thumbnail bold", "kind": "thumbnail", "config": {}}).status_code in (201, 409)
    assert client.post("/templates", json={"name": "Thumbnail-Bold", "kind": "thumbnail", "config": {}}).json()["error"]["code"] == "TEMPLATE_BUILTIN"
    assert client.post("/templates", json={"name": "x", "kind": "weird", "config": {}}).status_code == 400
    assert client.delete("/templates/thumbnail-bold").status_code == 409
    assert client.delete("/templates/bia-cua-toi").status_code == 204
    assert client.get("/templates/bia-cua-toi").status_code == 404
    pid = client.post("/projects", json={"name": "T"}).json()["id"]
    t = client.get("/templates/thumbnail-story").json()
    r = client.post(f"/projects/{pid}/tools/thumbnail/commands", json={"type": "apply-template", "payload": {"template": t}})
    assert r.status_code == 200 and r.json()["state"]["brief"]["aspect"] == "9:16"
    t = client.get("/templates/editor-shorts").json()
    r = client.post(f"/projects/{pid}/tools/editor/commands", json={"type": "apply-template", "payload": {"template": t}})
    assert r.status_code == 200 and r.json()["state"]["settings"]["fit"] == "crop"
