import json
import shutil
import subprocess
import sys
import zipfile

import pytest

from openstudio.errors import ApiError
from openstudio.image import engine as E
from openstudio.image.state import dims, initial_state, reducer
from openstudio.video import service as VS
from openstudio.video.state import reducer as vreducer
from openstudio.video.state import initial_state as vinit

from conftest import wait_job

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="cần ffmpeg")

FAKE_SD = r'''
import sys, zlib, struct, time
a = sys.argv
out = a[a.index("-o") + 1]
w, h = int(a[a.index("-W") + 1]), int(a[a.index("-H") + 1])
seed = int(a[a.index("-s") + 1])
for i in range(1, 5):
    sys.stderr.write(f"\r  |=====>   | {i}/4 - 0.01s/it\x1b[K")
    sys.stderr.flush()
    time.sleep(0.02)
sys.stderr.write("\n")
raw = b"".join(b"\x00" + bytes([(seed + x) % 256, 90, 160]) * w for x in range(h))
def chunk(t, d):
    c = struct.pack(">I", len(d)) + t + d
    return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
open(out, "wb").write(png)
open(out + ".args", "w").write(" ".join(a[1:]))
'''


# ---------- thuần ----------
def test_dims_are_multiples_of_16_and_respect_aspect():
    assert dims("1:1", "draft") == (512, 512) and dims("16:9", "standard") == (768, 432) and dims("9:16", "high") == (576, 1024)
    for a in ("1:1", "16:9", "9:16", "4:3", "3:4"):
        for q in ("draft", "standard", "high"):
            w, h = dims(a, q)
            assert w % 16 == 0 and h % 16 == 0


def test_image_brief_validation():
    s = reducer(initial_state(), "set-brief", {"brief": {"prompt": "tách cà phê", "aspect": "16:9", "count": 2, "seed": 5}})
    assert s["brief"]["count"] == 2 and s["brief"]["seed"] == 5
    for bad in ({"count": 9}, {"count": 0}, {"aspect": "2:1"}, {"quality": "ultra"}, {"seed": -1}, {"prompt": "x" * 2000}, {"zzz": 1}):
        with pytest.raises(ApiError):
            reducer(s, "set-brief", {"brief": bad})


def test_parse_step_ignores_download_progress_lines():
    assert E.parse_step("  |=====>   | 2/4 - 51.20s/it") == (2, 4)
    assert E.parse_step("  |####  | 45/298 - 945.04MB/s") is None


def test_build_cmd_flags():
    from pathlib import Path
    cmd = E.build_cmd(Path("sd-cli"), {"diffusion": Path("d.gguf"), "vae": Path("v.st"), "llm": Path("q.gguf")}, "a cat", 1024, 576, 3, Path("o.png"), Path("ref.png"))
    j = " ".join(cmd)
    assert "--steps 4" in j and "--cfg-scale 1.0" in j and "-W 1024 -H 576" in j and "--vae-tiling" in j and "-r ref.png" in j
    assert "--vae-tiling" not in " ".join(E.build_cmd(Path("sd-cli"), {"diffusion": Path("d"), "vae": Path("v"), "llm": Path("q")}, "x", 512, 512, 1, Path("o.png")))


def test_cli_extraction_blocks_zip_slip_and_flattens(tmp_path):
    exe = "sd-cli.exe" if sys.platform == "win32" else "sd-cli"
    eid = "sd-cpp-test"
    d = tmp_path / "engines" / eid
    d.mkdir(parents=True)
    with zipfile.ZipFile(d / "sd.zip", "w") as z:
        z.writestr(f"nested/{exe}", "bin")
        z.writestr("nested/lib.dll", "dll")
    assert E.cli_path(tmp_path, eid).parent == d / "bin" and (d / "bin" / "lib.dll").is_file()
    d2 = tmp_path / "engines" / "evil"
    d2.mkdir(parents=True)
    with zipfile.ZipFile(d2 / "sd.zip", "w") as z:
        z.writestr("../../escape.txt", "x")
    with pytest.raises(ApiError):
        E.cli_path(tmp_path, "evil")
    with pytest.raises(ApiError) as e:
        E.cli_path(tmp_path, "missing")
    assert e.value.code == "MODEL_MISSING"


def test_motion_filter_covers_all_presets():
    for p in ("zoom-in", "zoom-out", "pan-left", "pan-right", "pan-up", "pan-down"):
        f = VS.zoompan_filter(p, 150, 1280, 720, 25, 0.25)
        assert "zoompan" in f and "s=1280x720" in f and "d=150" in f
    b = vreducer(vinit(), "set-brief", {"brief": {"preset": "pan-left", "duration": 8}})["brief"]
    assert b["preset"] == "pan-left" and b["duration"] == 8
    for bad in ({"preset": "spin"}, {"duration": 0.2}, {"duration": 99}, {"aspect": "4:3"}, {"strength": 2}):
        with pytest.raises(ApiError):
            vreducer(vinit(), "set-brief", {"brief": bad})


# ---------- API ----------
def ff(*a):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *a], check=True)


def test_status_and_missing_engine_is_explicit(client):
    st = client.get("/image/status").json()
    assert st["device"] == "cpu" and "modelInstalled" in st
    pid = client.post("/projects", json={"name": "I"}).json()["id"]
    assert client.post(f"/projects/{pid}/image/generate").json()["error"]["code"] == "BRIEF_REQUIRED"
    client.post(f"/projects/{pid}/tools/image/commands", json={"type": "set-brief", "payload": {"brief": {"prompt": "a cat"}}})
    assert client.post(f"/projects/{pid}/image/generate").json()["error"]["code"] in ("MODEL_MISSING", "ENGINE_UNSUPPORTED")
    assert client.post(f"/projects/{pid}/tools/image/commands", json={"type": "_add-results", "payload": {"results": []}}).status_code >= 400


def test_generate_with_fake_engine_registers_assets_and_label(client, settings, tmp_path, monkeypatch):
    wrapper_py = tmp_path / "fake_sd.py"
    wrapper_py.write_text(FAKE_SD, encoding="utf-8")
    if sys.platform == "win32":
        cli = tmp_path / "fake_sd.cmd"
        cli.write_text(f'@"{sys.executable}" "{wrapper_py}" %*\r\n', encoding="utf-8")
    else:
        cli = tmp_path / "fake_sd.sh"
        cli.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{wrapper_py}" "$@"\n', encoding="utf-8")
        cli.chmod(0o755)
    monkeypatch.setattr(E, "engine_id", lambda: "sd-cpp-fake")
    monkeypatch.setattr(E, "cli_path", lambda models_dir, eid: cli)
    monkeypatch.setattr(E, "model_paths", lambda models_dir: {"diffusion": tmp_path / "d", "vae": tmp_path / "v", "llm": tmp_path / "l"})
    pid = client.post("/projects", json={"name": "Img"}).json()["id"]
    cmd = lambda p: client.post(f"/projects/{pid}/tools/image/commands", json={"type": "set-brief", "payload": {"brief": p}})
    assert cmd({"prompt": "tach ca phe", "aspect": "16:9", "count": 2, "seed": 10, "translate": False}).status_code == 200
    j = wait_job(client, client.post(f"/projects/{pid}/image/generate").json()["id"], 60)
    assert j["status"] == "succeeded", j
    st = client.get(f"/projects/{pid}/tools/image/state").json()["state"]
    assert [r["seed"] for r in st["results"]] == [11, 10] or [r["seed"] for r in st["results"]] == [10, 11]
    assert all(r["width"] == 512 and r["height"] == 288 for r in st["results"])
    files = [settings.projects_dir / pid / r["file"] for r in st["results"]]
    assert all(f.stat().st_size > 100 for f in files) and len({f.read_bytes() for f in files}) == 2
    assert all(f.with_suffix(".png.json").is_file() and json.loads(f.with_suffix(".png.json").read_text(encoding="utf-8"))["ai_generated"] for f in files)
    assets = {a["id"]: a for a in client.get(f"/projects/{pid}/assets").json()}
    assert all(r["assetId"] in assets and assets[r["assetId"]]["kind"] == "image" for r in st["results"])   # dùng được ngay ở Thumbnail/Editor
    args = files[0].with_name(files[0].name + ".args").read_text()
    assert "--steps 4" in args and "-W 512 -H 288" in args


@needs_ffmpeg
def test_motion_video_from_image_with_audio(client, settings, tmp_path):
    ff("-f", "lavfi", "-i", "testsrc2=size=800x600:rate=1:duration=1", "-frames:v", "1", str(tmp_path / "pic.png"))
    ff("-f", "lavfi", "-i", "sine=f=330:d=10", str(tmp_path / "music.wav"))
    pid = client.post("/projects", json={"name": "Vid"}).json()["id"]
    up = lambda p: client.put(f"/projects/{pid}/assets", params={"filename": p.name}, content=p.read_bytes()).json()
    pic, mus = up(tmp_path / "pic.png"), up(tmp_path / "music.wav")
    cmd = lambda p: client.post(f"/projects/{pid}/tools/video/commands", json={"type": "set-brief", "payload": {"brief": p}})
    assert client.post(f"/projects/{pid}/video/render").json()["error"]["code"] == "ASSET_REQUIRED"
    assert cmd({"asset": mus["id"]}).status_code == 200
    assert client.post(f"/projects/{pid}/video/render").json()["error"]["code"] == "VALIDATION_FAILED"      # âm thanh không phải ảnh
    assert cmd({"asset": pic["id"], "audio": mus["id"], "duration": 3, "preset": "pan-right", "aspect": "9:16", "quality": 480}).status_code == 200
    j = wait_job(client, client.post(f"/projects/{pid}/video/render").json()["id"], 120)
    assert j["status"] == "succeeded", j and j.get("error")
    res = j["result"]
    d = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(settings.projects_dir / pid / res["path"])],
                                  capture_output=True, text=True, check=True).stdout)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (480, 852) and abs(float(d["format"]["duration"]) - 3.0) < 0.2 and any(s["codec_type"] == "audio" for s in d["streams"])
    assert res["generative"] is False and any(a["id"] == res["assetId"] and a["kind"] == "video" for a in client.get(f"/projects/{pid}/assets").json())
    es = {e["id"]: e for e in client.get("/video/engines").json()}
    assert es["motion"]["generative"] is False and es["wan2.2-ti2v-5b"]["implemented"] is False
