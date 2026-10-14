import shutil
import subprocess

import httpx
import pytest

from openstudio.errors import ApiError
from openstudio.security import sign_file, verify_file_sig
from openstudio.subtitles import cues as C
from openstudio.subtitles.llm import LLMClient, extract_json_array, polish_cues, translate_cues
from openstudio.subtitles.segment import words_to_cues
from openstudio.subtitles.service import align_second, choose_stt_model, safe_filename
from openstudio.subtitles.state import reducer, initial_state

from conftest import TOKEN, wait_job

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="cần ffmpeg")


# ---------- định dạng ----------
def cue(s, e, t):
    return C.make_cue(s, e, t)


def test_srt_roundtrip_and_timestamps():
    cues = [cue(0, 1.5, "Xin chào"), cue(3723.456, 3725, "Dòng hai")]
    srt = C.to_srt(cues)
    assert "00:00:00,000 --> 00:00:01,500" in srt and "01:02:03,456 --> 01:02:05,000" in srt
    assert C.parse_subtitle(srt) == cues


def test_vtt_roundtrip():
    cues = [cue(1, 2, "A"), cue(2.5, 4, "B")]
    vtt = C.to_vtt(cues)
    assert vtt.startswith("WEBVTT") and "00:00:01.000 --> 00:00:02.000" in vtt
    assert C.parse_subtitle(vtt) == cues


def test_parse_subtitle_handles_bom_crlf_and_vtt_settings():
    text = "﻿WEBVTT\r\n\r\n1\r\n00:00:01.000 --> 00:00:02.000 align:start\r\nHello\r\nworld\r\n"
    assert C.parse_subtitle(text) == [cue(1, 2, "Hello world")]


def test_wrap_lines_balanced_and_vietnamese_safe():
    t = "Cà phê Việt Nam được người Pháp đưa vào nước ta từ năm một nghìn tám trăm"
    out = C.wrap_lines(t, 42)
    lines = out.split("\n")
    assert len(lines) == 2 and all(len(l) <= 42 for l in lines) and " ".join(lines) == t
    assert C.wrap_lines("ngắn", 42) == "ngắn"


def test_ass_bilingual_has_two_styles_and_escapes():
    a, b = [cue(0, 2, "Xin chào {x}")], [cue(0, 2, "Hello")]
    ass = C.to_ass(a, b, width=1080, height=1920)
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "{\\rDefault}Xin chào (x)\\N{\\rSecond}Hello" in ass
    top2 = C.to_ass(a, b, order="primary-bottom")
    assert "{\\rSecond}Hello\\N{\\rDefault}Xin chào (x)" in top2
    assert "0:00:00.00,0:00:02.00" in ass


def test_normalize_removes_overlap_and_empty_and_short():
    out = C.normalize([cue(0, 5, "a"), cue(2, 3, "b"), cue(3.0, 3.1, ""), cue(10, 10.1, "c")])
    assert [c["text"] for c in out] == ["a", "b", "c"]
    assert C.validate(out) == []
    assert out[2]["end"] - out[2]["start"] >= C.MIN_DURATION - 1e-6
    assert C.validate([cue(0, 2, "a"), cue(1, 3, "b")]) != []


# ---------- tách cue ----------
def W(words, start=0.0, step=0.3, gap_after=None):
    out, t = [], start
    for w in words:
        out.append({"start": t, "end": t + step - 0.05, "word": " " + w})
        t += step + (gap_after.get(w, 0) if gap_after else 0)
    return out


def test_segmentation_by_sentence_gap_and_length_never_drops_words():
    text = ("Xin chào các bạn. Hôm nay chúng ta tìm hiểu về cà phê Việt Nam, một chủ đề rất thú vị và có nhiều điều "
            "để nói, nên chúng ta sẽ đi từng phần một cách thật chậm rãi. Cảm ơn các bạn").split(" ")
    words = W(text, gap_after={"nay": 1.0})
    cues = words_to_cues(words)
    assert C.validate(cues) == []
    assert " ".join(c["text"] for c in cues).split() == text  # không mất, không thừa từ
    assert all(len(c["text"]) <= 84 + 15 for c in cues)
    assert cues[0]["text"] == "Xin chào các bạn."  # ngắt ở dấu chấm
    assert all(c["end"] - c["start"] <= 8 for c in cues)


def test_segmentation_empty_and_whitespace():
    assert words_to_cues([]) == []
    assert words_to_cues([{"start": 0, "end": 1, "word": "  "}]) == []


# ---------- LLM ----------
def make_llm(fake):
    return LLMClient("http://llm.test/v1", "qwen3:4b", client_factory=lambda: httpx.Client(transport=httpx.MockTransport(fake.handler)))


def test_extract_json_array_variants():
    assert extract_json_array('```json\n["a","b"]\n```') == ["a", "b"]
    assert extract_json_array('Đây: ["a"] xong') == ["a"]
    assert extract_json_array("không có") is None
    assert extract_json_array("[1,") is None


def test_translate_keeps_count_timing_and_strips_think(fake_llm):
    src = [cue(i, i + 1, f"dòng {i}") for i in range(40)]
    out = translate_cues(make_llm(fake_llm), src, source="vi", target="en", tone="formal", market="en-US")
    assert len(out) == 40 and out[3]["text"] == "EN:dòng 3"
    assert [(c["start"], c["end"]) for c in out] == [(c["start"], c["end"]) for c in src]
    assert len(fake_llm.calls) == 3  # 16 + 16 + 8
    sys_prompt = fake_llm.calls[0]["messages"][0]["content"]
    assert "Vietnamese to English" in sys_prompt and "formal" in sys_prompt and "en-US" in sys_prompt
    assert sys_prompt.rstrip().endswith("/no_think")
    assert "Context" in fake_llm.calls[1]["messages"][-1]["content"]


def test_translate_recovers_when_llm_returns_wrong_length(fake_llm):
    fake_llm.mode = "wrong_length"
    llm = make_llm(fake_llm)
    src = [cue(i, i + 1, f"x{i}") for i in range(5)]
    out = translate_cues(llm, src, source="vi", target="en")
    assert len(out) == 5
    # lô nhiều dòng luôn sai → chia đôi tới từng dòng (1 dòng thì trả đúng) nên vẫn dịch đủ
    assert [c["text"] for c in out] == [f"EN:x{i}" for i in range(5)]


def test_translate_falls_back_to_source_when_garbage(fake_llm):
    fake_llm.mode = "garbage"
    llm = make_llm(fake_llm)
    out = translate_cues(llm, [cue(0, 1, "abc"), cue(1, 2, "def")], source="vi", target="en")
    assert [c["text"] for c in out] == ["abc", "def"] and llm.stats["fallbacks"] == 2


def test_glossary_in_prompt_and_miss_counted(fake_llm):
    llm = make_llm(fake_llm)
    gl = [{"src": "cà phê", "dst": "coffee"}]
    translate_cues(llm, [cue(0, 1, "Cà phê ngon")], source="vi", target="en", glossary=gl)
    assert '"cà phê" => "coffee"' in fake_llm.calls[0]["messages"][0]["content"]
    assert llm.stats["glossary_misses"] == 1  # fake LLM không dùng thuật ngữ → phát hiện được


def test_polish_fixes_text_keeps_timing_and_rejects_rewrites(fake_llm):
    llm = make_llm(fake_llm)
    src = [cue(0, 2, "ca phe viet"), cue(2, 4, "giữ nguyên")]
    out = polish_cues(llm, src, language="vi")
    assert out[0]["text"] == "cà phê viet" and out[1]["text"] == "giữ nguyên"
    assert [(c["start"], c["end"]) for c in out] == [(0, 2), (2, 4)]


def test_llm_status(fake_llm):
    s = make_llm(fake_llm).status()
    assert s["available"] and s["model_installed"]
    bad = LLMClient("http://x/v1", "nope", client_factory=lambda: httpx.Client(transport=httpx.MockTransport(fake_llm.handler)))
    with pytest.raises(ApiError) as e:
        bad.require()
    assert e.value.code == "LLM_MODEL_MISSING"


# ---------- state ----------
SRC = {"path": "source/a.wav", "filename": "a.wav", "audio": "work/audio.wav", "duration": 10}


def test_reducer_track_rules_and_stale():
    s = reducer(initial_state(), "set-source", {"source": SRC})
    with pytest.raises(ApiError):
        reducer(s, "set-track", {"lang": "en", "kind": "translation", "cues": []})  # chưa có transcript
    s = reducer(s, "set-track", {"lang": "vi", "kind": "transcript", "cues": [cue(0, 2, "a"), cue(1, 3, "b")]})
    assert s["sourceLang"] == "vi" and C.validate(s["tracks"]["vi"]["cues"]) == []  # tự chuẩn hoá chồng lấn
    s = reducer(s, "set-track", {"lang": "en", "kind": "translation", "cues": [cue(0, 2, "a")]})
    assert s["tracks"]["en"]["stale"] is False
    s = reducer(s, "set-track", {"lang": "vi", "kind": "transcript", "cues": [cue(0, 2, "sửa")]})
    assert s["tracks"]["en"]["stale"] is True  # bản gốc đổi → bản dịch cũ bị đánh dấu cũ
    with pytest.raises(ApiError):
        reducer(s, "set-track", {"lang": "en!", "cues": []})
    with pytest.raises(ApiError):
        reducer(s, "set-track", {"lang": "en", "cues": [{"start": "x"}]})


def test_reducer_new_source_clears_tracks_but_keeps_glossary():
    s = reducer(initial_state(), "set-source", {"source": SRC})
    s = reducer(s, "set-glossary", {"glossary": [{"src": "Robusta", "dst": "Robusta"}, {"src": " ", "dst": "x"}]})
    s = reducer(s, "set-track", {"lang": "vi", "kind": "transcript", "cues": [cue(0, 2, "a")]})
    s2 = reducer(s, "set-source", {"source": {**SRC, "path": "source/b.wav"}})
    assert s2["tracks"] == {} and len(s2["glossary"]) == 1
    with pytest.raises(ApiError):
        reducer(s2, "set-options", {"options": {"evil": 1}})


def test_choose_stt_model():
    hw = {"tier": "cpu", "ram_gb": 15.5}
    assert choose_stt_model(hw, {"faster-whisper-small", "faster-whisper-large-v3-turbo"}) == "faster-whisper-large-v3-turbo"
    assert choose_stt_model({"tier": "cpu", "ram_gb": 8}, {"faster-whisper-small", "faster-whisper-large-v3-turbo"}) == "faster-whisper-small"
    assert choose_stt_model(hw, set()) is None
    assert choose_stt_model(hw, {"faster-whisper-small"}, "faster-whisper-tiny") is None


def test_safe_filename_and_align():
    assert safe_filename("../../x/Bài giảng #1?.MP4") == "Bài giảng _1.mp4"
    p = [cue(0, 2, "a"), cue(2, 4, "b")]
    s = [cue(0.1, 1.9, "A"), cue(2.1, 2.8, "B1"), cue(2.9, 3.9, "B2")]
    assert [c["text"] for c in align_second(p, s)] == ["A", "B1 B2"]


def test_signed_url_rules():
    sig = sign_file("t", "p1", "a/b.mp4", 2000)
    assert verify_file_sig("t", "p1", "a/b.mp4", 2000, sig, 1000)
    assert not verify_file_sig("t", "p1", "a/b.mp4", 2000, sig, 3000)  # hết hạn
    assert not verify_file_sig("t", "p1", "a/c.mp4", 2000, sig, 1000)  # sai file
    assert not verify_file_sig("other", "p1", "a/b.mp4", 2000, sig, 1000)


# ---------- API đầu-cuối với STT/LLM giả ----------
def make_wav(path, seconds=4):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", str(path)], check=True)
    return path.read_bytes()


@pytest.fixture
def project(client):
    return client.post("/projects", json={"name": "Phụ đề"}).json()["id"]


@pytest.fixture
def with_source(client, project, tmp_path):
    data = make_wav(tmp_path / "in.wav")
    job = client.put(f"/projects/{project}/subtitles/upload?filename=B%C3%A0i%20h%E1%BB%8Dc.wav", content=data).json()
    assert wait_job(client, job["id"], 20)["status"] == "succeeded"
    return project


def state(client, pid):
    return client.get(f"/projects/{pid}/tools/subtitles/state").json()


@needs_ffmpeg
def test_upload_prepares_source_and_audio(client, with_source, settings):
    st = state(client, with_source)["state"]
    assert st["source"]["filename"] == "Bài học.wav" and 3.5 < st["source"]["duration"] < 4.5
    assert st["source"]["hasVideo"] is False
    assert (settings.projects_dir / with_source / "work" / "audio.wav").is_file()


def test_upload_rejects_bad_type_and_empty(client, project):
    assert client.put(f"/projects/{project}/subtitles/upload?filename=x.exe", content=b"abc").status_code == 400
    assert client.put(f"/projects/{project}/subtitles/upload?filename=x.wav", content=b"").status_code == 400


def test_fetch_rejects_non_http(client, project):
    assert client.post(f"/projects/{project}/subtitles/fetch", json={"url": "file:///etc/passwd"}).status_code == 400


@needs_ffmpeg
def test_transcribe_needs_model_then_runs(client, with_source, fake_llm):
    r = client.post(f"/projects/{with_source}/subtitles/transcribe", json={"language": "vi", "polish": False})
    assert r.status_code == 424 and r.json()["error"]["code"] == "MODEL_MISSING"
    assert r.json()["error"]["details"]["modelId"].startswith("faster-whisper")
    wait_job(client, client.post("/models/faster-whisper-tiny/download").json()["id"])
    job = client.post(f"/projects/{with_source}/subtitles/transcribe", json={"language": "vi", "polish": False}).json()
    done = wait_job(client, job["id"], 20)
    assert done["status"] == "succeeded", done
    st = state(client, with_source)
    tr = st["state"]["tracks"]["vi"]
    assert st["state"]["sourceLang"] == "vi" and tr["kind"] == "transcript" and tr["meta"]["model"] == "faster-whisper-tiny"
    assert C.validate(tr["cues"]) == [] and tr["cues"][0]["text"] == "Xin chào các bạn."
    assert len(tr["cues"]) >= 4


@needs_ffmpeg
def test_full_flow_polish_translate_edit_export(client, with_source, fake_llm, settings):
    pid = with_source
    wait_job(client, client.post("/models/faster-whisper-tiny/download").json()["id"])
    j = client.post(f"/projects/{pid}/subtitles/transcribe", json={"language": "vi", "polish": True}).json()
    assert wait_job(client, j["id"], 20)["status"] == "succeeded"
    assert state(client, pid)["state"]["tracks"]["vi"]["meta"]["polished"] is True
    # dịch nhiều ngôn ngữ cùng lúc
    r = client.post(f"/projects/{pid}/subtitles/translate", json={"targets": ["en", "ja", "vi"], "tone": "casual"})
    assert r.status_code == 202
    assert wait_job(client, r.json()["id"], 20)["status"] == "succeeded"
    tracks = state(client, pid)["state"]["tracks"]
    assert set(tracks) == {"vi", "en", "ja"}  # "vi" (ngôn ngữ gốc) bị loại khỏi đích
    assert len(tracks["en"]["cues"]) == len(tracks["vi"]["cues"]) and tracks["en"]["meta"]["tone"] == "casual"
    # sửa bản gốc → bản dịch thành cũ, và có phiên bản mới (không ghi đè)
    rev_before = state(client, pid)["revision"]
    cues = tracks["vi"]["cues"]
    cues[0]["text"] = "Chào mọi người."
    ok = client.post(f"/projects/{pid}/tools/subtitles/commands",
                     json={"type": "set-track", "payload": {"lang": "vi", "kind": "transcript", "cues": cues},
                           "expectedRevision": rev_before})
    assert ok.status_code == 200 and ok.json()["state"]["tracks"]["en"]["stale"] is True
    revs = client.get(f"/projects/{pid}/tools/subtitles/revisions").json()
    assert len(revs) == rev_before + 1 and revs[1]["state"]["tracks"]["vi"]["cues"][0]["text"] != "Chào mọi người."
    # xuất
    for fmt in ("srt", "vtt", "ass"):
        e = client.post(f"/projects/{pid}/subtitles/export", json={"lang": "vi", "format": fmt}).json()
        assert (settings.projects_dir / pid / e["path"]).is_file()
    bil = client.post(f"/projects/{pid}/subtitles/export", json={"lang": "vi", "second": "en", "format": "srt"}).json()
    text = (settings.projects_dir / pid / bil["path"]).read_text(encoding="utf-8-sig")
    assert "Chào mọi người.\nEN:" in text
    assert client.post(f"/projects/{pid}/subtitles/export", json={"lang": "zz", "format": "srt"}).status_code == 404
    assert client.post(f"/projects/{pid}/subtitles/export", json={"lang": "vi", "format": "doc"}).status_code == 400


@needs_ffmpeg
def test_translate_requires_transcript_and_llm(client, with_source, fake_llm):
    assert client.post(f"/projects/{with_source}/subtitles/translate", json={"targets": ["en"]}).status_code == 409


@needs_ffmpeg
def test_translate_reports_llm_unavailable(settings, tmp_path):
    from fastapi.testclient import TestClient
    from conftest import FAKE_STT, _handler
    from openstudio.app import create_app

    def down(_req):
        raise httpx.ConnectError("refused")
    app = create_app(settings, TOKEN, lambda: httpx.Client(transport=httpx.MockTransport(_handler)), stt_cmd=FAKE_STT,
                     llm_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(down)))
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        pid = c.post("/projects", json={"name": "x"}).json()["id"]
        data = make_wav(tmp_path / "a.wav", 2)
        wait_job(c, c.put(f"/projects/{pid}/subtitles/upload?filename=a.wav", content=data).json()["id"], 20)
        wait_job(c, c.post("/models/faster-whisper-tiny/download").json()["id"])
        wait_job(c, c.post(f"/projects/{pid}/subtitles/transcribe", json={"polish": True}).json()["id"], 20)
        # polish đã thất bại mềm: vẫn có transcript thô
        assert c.get(f"/projects/{pid}/tools/subtitles/state").json()["state"]["tracks"]["vi"]["meta"]["polished"] is False
        r = c.post(f"/projects/{pid}/subtitles/translate", json={"targets": ["en"]})
        assert r.status_code == 424 and r.json()["error"]["code"] == "LLM_UNAVAILABLE"


def test_llm_status_endpoint(client):
    s = client.get("/llm/status").json()
    assert s["available"] and s["model"] == "qwen3:4b"


# ---------- URL ký ----------
def test_signed_file_url_flow(client, project, settings):
    (settings.projects_dir / project / "exports").mkdir(parents=True, exist_ok=True)
    (settings.projects_dir / project / "exports" / "a.srt").write_text("x")
    url = client.post(f"/projects/{project}/file-url", json={"path": "exports/a.srt"}).json()["url"]
    anon = {"Authorization": ""}
    assert client.get(url, headers=anon).status_code == 200  # không cần Bearer
    assert client.get(url.replace("a.srt", "b.srt"), headers=anon).status_code in (401, 404)  # sai file
    assert client.get(url.split("&sig=")[0] + "&sig=bad", headers=anon).status_code == 401
    assert client.get(f"/files/{project}/exports/a.srt", headers=anon).status_code == 401
    assert client.post(f"/projects/{project}/file-url", json={"path": "../x"}).status_code in (400, 404)


# ---------- burn-in thật bằng ffmpeg ----------
def ffprobe_size(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout.strip()
    return tuple(int(x) for x in out.split(","))


@needs_ffmpeg
@pytest.mark.parametrize("layout,expected", [("horizontal", (320, 180)), ("vertical", (1080, 1920))])
def test_burn_in_video(client, project, settings, tmp_path, fake_llm, layout, expected):
    vid = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=300:duration=3", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(vid)], check=True)
    wait_job(client, client.put(f"/projects/{project}/subtitles/upload?filename=v.mp4", content=vid.read_bytes()).json()["id"], 20)
    st = state(client, project)
    cues = [cue(0.2, 1.5, "Xin chào thế giới"), cue(1.6, 2.8, "Tạm biệt")]
    client.post(f"/projects/{project}/tools/subtitles/commands",
                json={"type": "set-track", "payload": {"lang": "vi", "kind": "transcript", "cues": cues}, "expectedRevision": st["revision"]})
    client.post(f"/projects/{project}/tools/subtitles/commands",
                json={"type": "set-track", "payload": {"lang": "en", "kind": "translation", "cues": [cue(0.2, 1.5, "Hello world"), cue(1.6, 2.8, "Bye")]}})
    job = client.post(f"/projects/{project}/subtitles/burn", json={"lang": "vi", "second": "en", "layout": layout}).json()
    done = wait_job(client, job["id"], 60)
    assert done["status"] == "succeeded", done
    out = settings.projects_dir / project / "exports" / f"v.vi+en.{layout}.mp4"
    assert out.is_file() and ffprobe_size(out) == expected


@needs_ffmpeg
def test_burn_in_audio_only_makes_black_video(client, with_source, settings):
    client.post(f"/projects/{with_source}/tools/subtitles/commands",
                json={"type": "set-track", "payload": {"lang": "vi", "kind": "transcript", "cues": [cue(0.2, 2, "Chỉ có âm thanh")]}})
    job = client.post(f"/projects/{with_source}/subtitles/burn", json={"lang": "vi"}).json()
    assert wait_job(client, job["id"], 60)["status"] == "succeeded"
    out = next((settings.projects_dir / with_source / "exports").glob("*.horizontal.mp4"))
    assert ffprobe_size(out) == (1920, 1080)


def test_translate_accepts_bare_array_with_think_tags(fake_llm):
    fake_llm.mode = "bare_array"
    out = translate_cues(make_llm(fake_llm), [cue(0, 1, "a"), cue(1, 2, "b")], source="vi", target="en")
    assert [c["text"] for c in out] == ["EN:a", "EN:b"]


def test_openai_provider_uses_chat_completions_with_json_schema(fake_llm):
    llm = make_llm(fake_llm)
    llm.provider = "openai"
    translate_cues(llm, [cue(0, 1, "a")], source="vi", target="en")
    body = fake_llm.calls[-1]
    assert body["response_format"]["type"] == "json_schema" and "think" not in body


def test_ollama_provider_disables_thinking_and_constrains_output(fake_llm):
    translate_cues(make_llm(fake_llm), [cue(0, 1, "a")], source="vi", target="en")
    body = fake_llm.calls[-1]
    assert body["think"] is False and body["format"]["required"] == ["lines"] and body["options"]["num_predict"] > 0


def test_strip_foreign_script_keeps_cjk_languages_and_vietnamese():
    from openstudio.subtitles.llm import strip_foreign_script as sfs
    assert sfs("khi người Pháp引入 cây này", "vi") == "khi người Pháp cây này"
    assert sfs("Hello  世界 world", "en") == "Hello world"
    assert sfs("今日は天気がいい", "ja") == "今日は天気がいい" and sfs("你好", "zh-CN") == "你好"
    assert sfs("Tiếng Việt có dấu ạ ộ ữ", "vi") == "Tiếng Việt có dấu ạ ộ ữ"
    assert sfs("引入", "vi") == ""


def test_translate_and_polish_drop_stray_cjk_from_llm_output(fake_llm):
    class Leaky(type(fake_llm)):
        def handler(self, request):
            r = super().handler(request)
            return httpx.Response(200, json={**r.json(), "message": {"role": "assistant", "content": r.json()["message"]["content"].replace("EN:", "EN:引入")}}) \
                if "message" in r.json() else r
    leaky = Leaky()
    out = translate_cues(make_llm(leaky), [cue(0, 1, "a")], source="vi", target="en")
    assert out[0]["text"] == "EN:a"                                              # chữ Hán bị bỏ
    ja = translate_cues(make_llm(leaky), [cue(0, 1, "a")], source="vi", target="ja")
    assert "引入" in ja[0]["text"]                                                 # tiếng Nhật thì giữ
