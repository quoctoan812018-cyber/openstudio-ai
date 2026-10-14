import json

import pytest
from fastapi.testclient import TestClient

from openstudio.app import create_app
from openstudio.config import ConfigError, load_settings
from openstudio.hardware import tier_allows, tier_for_vram
from openstudio.security import redact
from openstudio.tools import list_tools

from conftest import TOKEN, wait_job


# ---- bảo mật ----
def test_healthz_is_public_and_others_need_token(settings):
    app = create_app(settings, TOKEN)
    with TestClient(app) as c:
        assert c.get("/healthz").json() == {"ok": True}
        r = c.get("/projects")
        assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"
        assert c.get("/projects", headers={"Authorization": "Bearer nope"}).status_code == 401
        assert c.get("/projects", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


def test_daemon_refuses_non_loopback_host(tmp_path):
    (tmp_path / "config.toml").write_text("")
    with pytest.raises(ConfigError):
        load_settings(tmp_path, {"OPENSTUDIO_HOST": "0.0.0.0", "OPENSTUDIO_ROOT": str(tmp_path)})


def test_redaction():
    s = redact("Authorization: Bearer abc.def-123 key sk-ABCDEFGH12345 api_key=SECRET1 ?token=zzz&x=1")
    assert "abc.def" not in s and "ABCDEFGH" not in s and "SECRET1" not in s and "zzz" not in s


def test_unknown_route_uses_error_envelope(client):
    r = client.get("/nope")
    assert r.status_code == 404 and "error" in r.json()


def test_validation_error_envelope(client):
    r = client.post("/projects", json={"name": ""})
    assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_FAILED"


# ---- phần cứng & công cụ ----
def test_tiers():
    assert tier_for_vram(None) == "cpu" and tier_for_vram(8) == "gpu8" and tier_for_vram(12) == "gpu12"
    assert tier_for_vram(24) == "gpu16plus" and tier_for_vram(4) == "cpu"
    assert tier_allows("gpu12", "gpu8") and not tier_allows("cpu", "gpu8")


def test_tools_locked_with_reason():
    tools = {t["id"]: t for t in list_tools("cpu")}
    assert tools["subtitles"]["available"] and tools["subtitles"]["locked_reason"] is None
    # mọi công cụ hiện chạy được trên CPU; phần cần GPU (lip-sync AI, sinh video AI) khoá ở từng trang, cơ chế khoá theo hạng vẫn hoạt động:
    assert all(t["available"] for t in list_tools("cpu")) and not tier_allows("cpu", "gpu16plus") and tier_allows("gpu12", "gpu8")
    assert all(t["available"] for t in list_tools("gpu16plus"))


def test_hardware_endpoint(client):
    hw = client.get("/system/hardware").json()
    assert hw["tier"] in ("cpu", "gpu8", "gpu12", "gpu16plus") and hw["ram_gb"] > 0


# ---- project / phiên bản ----
def test_project_crud_and_delete_requires_confirm(client):
    p = client.post("/projects", json={"name": "Demo"}).json()
    assert client.patch(f"/projects/{p['id']}", json={"name": "Mới"}).json()["name"] == "Mới"
    assert client.delete(f"/projects/{p['id']}").status_code == 409
    assert client.delete(f"/projects/{p['id']}?confirm=true").status_code == 204
    assert client.get(f"/projects/{p['id']}").status_code == 404


def test_versions_never_overwrite(client):
    pid = client.post("/projects", json={"name": "V"}).json()["id"]
    url = f"/projects/{pid}/tools/agent/commands"
    r1 = client.post(url, json={"type": "set-config", "payload": {"config": {"lang": "en"}}, "expectedRevision": 0}).json()
    r2 = client.post(url, json={"type": "set-config", "payload": {"config": {"lang": "ja"}}, "expectedRevision": 1}).json()
    assert (r1["revision"], r2["revision"]) == (1, 2)
    revs = client.get(f"/projects/{pid}/tools/agent/revisions").json()
    assert [r["n"] for r in revs] == [2, 1] and revs[1]["state"] == {"config": {"lang": "en"}}
    # quay lại bản 1 = tạo bản 3, bản 1 và 2 còn nguyên
    r3 = client.post(url, json={"type": "select-revision", "payload": {"revisionId": revs[1]["id"]}, "expectedRevision": 2}).json()
    assert r3["revision"] == 3 and r3["state"]["config"] == {"lang": "en"}
    assert len(client.get(f"/projects/{pid}/tools/agent/revisions").json()) == 3


def test_revision_conflict(client):
    pid = client.post("/projects", json={"name": "C"}).json()["id"]
    url = f"/projects/{pid}/tools/agent/commands"
    client.post(url, json={"type": "set-config", "payload": {"config": {}}, "expectedRevision": 0})
    r = client.post(url, json={"type": "set-config", "payload": {"config": {}}, "expectedRevision": 0})
    assert r.status_code == 409 and r.json()["error"]["code"] == "REVISION_CONFLICT"


def test_unknown_tool(client):
    pid = client.post("/projects", json={"name": "T"}).json()["id"]
    assert client.get(f"/projects/{pid}/tools/ghost/state").status_code == 404


# ---- job & sự kiện ----
def test_job_progress_and_events(client):
    pid = client.post("/projects", json={"name": "J"}).json()["id"]
    job = client.post("/jobs", json={"type": "demo.sleep", "params": {"steps": 3, "delay": 0.01}, "projectId": pid}).json()
    done = wait_job(client, job["id"])
    assert done["status"] == "succeeded" and done["progress"]["percent"] == 100.0
    raw = client.get(f"/events?projectId={pid}&replayOnly=true").text
    types = [l.split(": ", 1)[1] for l in raw.splitlines() if l.startswith("event: ")]
    assert types[:2] == ["project.created", "job.queued"] and "job.progress" in types and types[-1] == "job.succeeded"
    first_progress = next(json.loads(l[6:]) for l in raw.splitlines() if l.startswith("data: ") and '"job.progress"' in l)
    assert set(first_progress["data"]) == {"phase", "percent", "message", "completed", "failed", "total"}


def test_events_resume_after_last_id(client):
    client.post("/projects", json={"name": "a"})
    client.post("/projects", json={"name": "b"})
    ids = [int(l[4:]) for l in client.get("/events?replayOnly=true").text.splitlines() if l.startswith("id: ")]
    rest = client.get(f"/events?replayOnly=true&lastEventId={ids[0]}").text
    assert f"id: {ids[0]}\n" not in rest and f"id: {ids[1]}" in rest


def test_job_cancel(client):
    job = client.post("/jobs", json={"type": "demo.sleep", "params": {"steps": 200, "delay": 0.05}}).json()
    client.post(f"/jobs/{job['id']}/cancel")
    assert wait_job(client, job["id"])["status"] == "cancelled"


def test_only_demo_job_type_public(client):
    assert client.post("/jobs", json={"type": "model.download"}).status_code == 400


# ---- Model Manager ----
def test_registry_listing_and_nc_flag(client):
    models = {m["id"]: m for m in client.get("/models").json()}
    assert {"tiny-test", "bad-checksum", "nc-model"} <= set(models)
    assert models["nc-model"]["non_commercial"] and models["nc-model"]["warning"]
    assert models["tiny-test"]["status"] == "not_installed"


def test_real_registry_parses():
    from pathlib import Path
    from openstudio.models import flatten_registry
    import yaml
    reg = Path(__file__).resolve().parents[3] / "models" / "registry.yaml"
    entries = {e["id"]: e for e in flatten_registry(yaml.safe_load(reg.read_text(encoding="utf-8")))}
    assert "faster-whisper-tiny" in entries and entries["f5-tts"]["non_commercial"] is True
    assert entries["musicgen"]["non_commercial"] is True


def test_model_download_verifies_and_installs(client, settings):
    job = client.post("/models/tiny-test/download").json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    assert (settings.models_dir / "stt/tiny-test/model.bin").read_bytes().startswith(b"xxxx")
    assert not list(settings.models_dir.rglob("*.part"))
    assert next(m for m in client.get("/models").json() if m["id"] == "tiny-test")["status"] == "installed"
    assert client.post("/models/tiny-test/download").status_code == 409
    assert client.delete("/models/tiny-test").status_code == 204
    assert not (settings.models_dir / "stt/tiny-test").exists()


def test_model_download_rejects_bad_checksum(client, settings):
    job = client.post("/models/bad-checksum/download").json()
    done = wait_job(client, job["id"])
    assert done["status"] == "failed" and done["error"]["code"] == "MODEL_CHECKSUM_MISMATCH"
    assert not (settings.models_dir / "stt/bad/model.bin").exists()
    assert not list(settings.models_dir.rglob("*.part"))


def test_non_commercial_requires_acknowledgement(client):
    r = client.post("/models/nc-model/download")
    assert r.status_code == 409 and r.json()["error"]["code"] == "NON_COMMERCIAL_CONFIRMATION_REQUIRED"
    r = client.post("/models/nc-model/download", json={"acknowledge_non_commercial": True})
    assert r.status_code == 202


def test_model_dest_cannot_escape_models_dir(client):
    job = client.post("/models/evil-path/download")
    # dest nằm ngoài models_dir → bị chặn ngay khi mô tả/tải
    assert job.status_code in (400, 500) or wait_job(client, job.json()["id"])["status"] == "failed"


def test_unknown_model(client):
    assert client.post("/models/ghost/download").status_code == 404


# ---- thư viện & file ----
def test_library_and_file_traversal(client, settings):
    pid = client.post("/projects", json={"name": "L"}).json()["id"]
    (settings.projects_dir / pid / "out").mkdir(parents=True, exist_ok=True)
    (settings.projects_dir / pid / "out" / "a.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
    lib = client.get(f"/library?projectId={pid}").json()
    assert lib[0]["path"] == "out/a.srt" and lib[0]["kind"] == "subtitle"
    assert client.get(f"/files/{pid}/out/a.srt").status_code == 200
    assert client.get(f"/files/{pid}/..%2F..%2Fopenstudio.db").status_code in (400, 404)
    assert client.get(f"/files/{pid}/../../openstudio.db").status_code in (400, 404)


def test_settings_roundtrip(client):
    s = client.get("/settings").json()
    assert s["language"] == "vi" and s["cloud_providers_enabled"] is False
    client.put("/settings", json={"language": "en", "ai_label_metadata": True, "ai_label_watermark": True,
                                  "cloud_providers_enabled": False})
    assert client.get("/settings").json()["language"] == "en"


def test_interrupted_jobs_recovered_on_restart(settings):
    app = create_app(settings, TOKEN)
    db = app.state.db
    db.execute("INSERT INTO job(id, type, status, created_at) VALUES('j1','demo.sleep','running',0)")
    db.close()
    app2 = create_app(settings, TOKEN)
    assert app2.state.db.one("SELECT status FROM job WHERE id='j1'")["status"] == "failed"


def test_remote_bind_only_for_containers_and_needs_own_token(tmp_path):
    (tmp_path / "config.toml").write_text("")
    base = {"OPENSTUDIO_ROOT": str(tmp_path), "OPENSTUDIO_HOST": "0.0.0.0"}
    with pytest.raises(ConfigError):
        load_settings(tmp_path, base)                                                             # thiếu cờ
    with pytest.raises(ConfigError):
        load_settings(tmp_path, {**base, "OPENSTUDIO_ALLOW_REMOTE_BIND": "1"})                    # thiếu token tự đặt
    with pytest.raises(ConfigError):
        load_settings(tmp_path, {**base, "OPENSTUDIO_HOST": "192.168.1.5", "OPENSTUDIO_ALLOW_REMOTE_BIND": "1", "OPENSTUDIO_TOKEN": "t"})  # chỉ 0.0.0.0
    s = load_settings(tmp_path, {**base, "OPENSTUDIO_ALLOW_REMOTE_BIND": "1", "OPENSTUDIO_TOKEN": "t"})
    assert s.remote_bind and s.host == "0.0.0.0"


def test_every_route_requires_token_except_allowlist(client):
    """Quét toàn bộ route: mọi đường dẫn (trừ danh sách cho phép) phải trả 401 khi không có token."""
    from fastapi.routing import APIRoute
    allow = {"/healthz", "/files/{pid}/{path:path}", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    anon = client.__class__(client.app, raise_server_exceptions=False)   # cùng app, không header Authorization
    checked = 0
    def walk(routes):
        for r in routes:
            inner = getattr(r, "original_router", None)
            yield from walk(inner.routes) if inner is not None else [r]

    for r in walk(client.app.routes):
        if not isinstance(r, APIRoute) or r.path in allow:
            continue
        path = r.path.replace("{pid}", "p").replace("{job_id}", "j").replace("{path:path}", "x")
        path = __import__("re").sub(r"\{[^}]+\}", "x", path)
        for m in r.methods - {"HEAD", "OPTIONS"}:
            res = anon.request(m, path)
            assert res.status_code == 401, f"{m} {r.path} → {res.status_code}"
            checked += 1
    assert checked > 50


def test_doctor_reports_checks(client):
    res = client.get("/system/doctor").json()
    ids = {c["id"] for c in res["checks"]}
    assert {"ffmpeg", "ffprobe", "data_dir", "disk", "llm"} <= ids
    assert all({"ok", "required", "detail"} <= set(c) for c in res["checks"])


def test_serves_web_dist_same_origin(tmp_path, settings):
    import httpx
    from fastapi.testclient import TestClient
    from openstudio.app import create_app
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>OpenStudio</html>")
    settings.web_dist = dist
    app = create_app(settings, TOKEN, lambda: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))))
    with TestClient(app) as c:
        assert "OpenStudio" in c.get("/").text
        assert c.get("/projects").status_code == 401                 # API vẫn cần token
