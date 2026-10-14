import json
import sys
import time
from datetime import datetime

import pytest

from agent_harness import FAKE_MCP, ScriptedLLM, make_client, new_thread, send, wait_run
from openstudio.agent.mcp import McpError, McpManager
from openstudio.agent.scheduler import ScheduleStore, Scheduler, next_run, parse_cron, validate_interval
from openstudio.agent.skills import TEMPLATE, parse_skill
from openstudio.db import Database
from openstudio.errors import ApiError

VALID = TEMPLATE.replace("ten-skill-cua-ban", "bao-cao-tuan")


# ---------- Skills ----------
def test_builtin_skills_are_valid_and_reference_real_tools(client):
    skills = {s["name"]: s for s in client.get("/skills").json()}
    assert {"video-localization", "youtube-to-shorts", "podcast-from-article", "multi-market-campaign", "stickman-explainer"} <= set(skills)
    tool_names = {t["name"] for t in client.get("/agent/tools").json()}
    for s in skills.values():
        assert s["source"] == "builtin" and s["enabled"] and not s["warnings"], s
        assert set(s["tools"]) <= tool_names and s["steps"] and set(s["steps"]) <= set(s["tools"])
    assert skills["youtube-to-shorts"]["steps"][:3] == ["get_state", "subtitles_transcribe", "highlights_setup"]
    body = client.get("/skills/video-localization").json()["body"]
    assert "Tiêu chí đạt" in body and "dubbing_mix" in body


def test_stickman_skill_is_honest_about_missing_image_tools(client):
    body = client.get("/skills/stickman-explainer").json()["body"]
    assert "chưa có" in body and "GPU" in body


def test_skill_parse_errors():
    for md, frag in [("không có frontmatter", "frontmatter"), ("---\nname: Sai Ten\ndescription: mô tả đủ dài rồi nhé\ntools: []\n---\nnội dung", "name"),
                     ("---\nname: ok-skill\ndescription: ngắn\ntools: []\n---\nnội dung", "description"),
                     ("---\nname: ok-skill\ndescription: mô tả đủ dài rồi nhé\ntools: abc\n---\nnội dung", "tools"),
                     ("---\nname: ok-skill\ndescription: mô tả đủ dài rồi nhé\ntools: []\n---\n", "Nội dung"),
                     ("---\nname: [oops\n---\nx", "YAML")]:
        with pytest.raises(ApiError) as e:
            parse_skill(md, "user")
        assert frag in e.value.message, (md, e.value.message)
    with pytest.raises(ApiError) as e:
        parse_skill(VALID.replace("subtitles_translate", "xoa_o_cung"), "user", {"subtitles_transcribe"})
    assert "xoa_o_cung" in e.value.message


def test_user_skill_lifecycle_import_export_toggle_delete(client, settings):
    assert client.get("/skills/template").json()["markdown"].startswith("---")
    r = client.post("/skills", json={"markdown": VALID})
    assert r.status_code == 201 and r.json()["source"] == "user" and r.json()["steps"] == ["subtitles_transcribe", "subtitles_translate"]
    assert (settings.data_dir / "skills" / "bao-cao-tuan" / "SKILL.md").is_file()
    assert client.get("/skills/bao-cao-tuan/export").text == VALID.replace("\r\n", "\n")
    assert "attachment" in client.get("/skills/bao-cao-tuan/export").headers["content-disposition"]
    # tắt/bật được cả skill có sẵn lẫn skill của bạn; trạng thái được lưu
    assert client.put("/skills/youtube-to-shorts/enabled", json={"enabled": False}).json()["enabled"] is False
    assert json.loads((settings.data_dir / "skills.json").read_text())["disabled"] == ["youtube-to-shorts"]
    assert client.put("/skills/youtube-to-shorts/enabled", json={"enabled": True}).json()["enabled"] is True
    # không ghi đè skill có sẵn, không xoá skill có sẵn, tên rác bị từ chối
    assert client.post("/skills", json={"markdown": VALID.replace("bao-cao-tuan", "video-localization")}).status_code == 409
    assert client.delete("/skills/video-localization").status_code == 403
    assert client.post("/skills", json={"markdown": VALID.replace("bao-cao-tuan", "../etc")}).status_code == 400
    assert client.post("/skills", json={"markdown": VALID.replace("subtitles_transcribe", "khong_co")}).json()["error"]["code"] == "SKILL_INVALID"
    assert client.delete("/skills/bao-cao-tuan").status_code == 204 and client.get("/skills/bao-cao-tuan").status_code == 404


def test_broken_skill_file_is_listed_not_fatal(client, settings):
    d = settings.data_dir / "skills" / "hong"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("không phải skill", encoding="utf-8")
    listed = {s["name"]: s for s in client.get("/skills").json()}
    assert listed["hong"]["enabled"] is False and listed["hong"]["warnings"] and "video-localization" in listed


def test_skill_is_injected_with_checklist_and_marks_done_steps(settings, tmp_path):
    from agent_harness import project_with_source
    llm = ScriptedLLM([{"tool": "get_state", "args": {"tool": "subtitles"}}, {"tool": "ask_user", "args": {"question": "Bạn có link video không?"}}])
    with make_client(settings, llm) as c:
        pid = project_with_source(c, tmp_path)
        tid = new_thread(c, pid, skill="video-localization")
        send(c, tid, "dịch video sang tiếng Anh")
        wait_run(c, tid)
        first_sys = llm.prompts[0][0]
        assert "Skill to follow — video-localization" in first_sys and "Tiêu chí đạt" in first_sys
        assert "[ ] 1. get_state" in llm.prompts[0][1]
        assert any("[x] 1. get_state" in p[1] for p in llm.prompts[1:])             # sau khi gọi get_state, checklist đánh dấu xong
        assert c.get(f"/threads/{tid}").json()["messages"][1]["kind"] == "skill"


def test_skill_chosen_by_llm_or_by_slash_and_disabled_skill_ignored(settings, tmp_path):
    llm = ScriptedLLM([{"tool": "final", "message": "ok"}], skill_pick="youtube-to-shorts")
    with make_client(settings, llm) as c:
        pid = c.post("/projects", json={"name": "x"}).json()["id"]
        t1 = new_thread(c, pid)
        send(c, t1, "cắt 3 clip tiktok từ video này")
        wait_run(c, t1)
        assert "Skill to follow — youtube-to-shorts" in llm.prompts[0][0]
        n = len(llm.prompts)
        t2 = new_thread(c, pid)
        send(c, t2, "/podcast-from-article làm podcast về cà phê")
        wait_run(c, t2)
        assert "Skill to follow — podcast-from-article" in llm.prompts[n][0]
        c.put("/skills/youtube-to-shorts/enabled", json={"enabled": False})
        n = len(llm.prompts)
        t3 = new_thread(c, pid)
        send(c, t3, "cắt clip")
        wait_run(c, t3)
        assert "Skill to follow — youtube-to-shorts" not in llm.prompts[n][0]


# ---------- Cron & lịch ----------
def test_cron_parsing_and_next_run():
    base = datetime(2026, 10, 14, 9, 0)          # thứ Tư
    assert next_run("0 8 * * *", base) == datetime(2026, 10, 15, 8, 0)
    assert next_run("*/15 * * * *", base) == datetime(2026, 10, 14, 9, 15)
    assert next_run("30 6 1 * *", base) == datetime(2026, 11, 1, 6, 30)
    assert next_run("0 9 * * 1", base) == datetime(2026, 10, 19, 9, 0)             # thứ Hai
    assert next_run("0 9 * * 7", base) == datetime(2026, 10, 18, 9, 0)             # 7 = Chủ nhật
    assert next_run("0 9 15 * 1", base) == datetime(2026, 10, 15, 9, 0)   # ngày 15 HOẶC thứ Hai (chuẩn cron): 15/10 đến trước
    assert next_run("0 0 29 2 *", datetime(2026, 3, 1)) == datetime(2028, 2, 29, 0, 0)
    assert next_run("5,35 10-11 * * *", base) == datetime(2026, 10, 14, 10, 5)
    for bad in ("", "* * * *", "61 * * * *", "* 24 * * *", "*/0 * * * *", "a b c d e", "* * 32 * *"):
        with pytest.raises(ApiError) as e:
            parse_cron(bad)
        assert e.value.code == "CRON_INVALID"
    with pytest.raises(ApiError):
        next_run("0 0 31 2 *", base)                                               # không bao giờ tồn tại
    with pytest.raises(ApiError) as e:
        validate_interval("* * * * *")
    assert e.value.code == "CRON_TOO_FREQUENT"
    validate_interval("*/5 * * * *")


@pytest.fixture
def sched(tmp_path):
    db = Database(tmp_path / "s.db")
    db.execute("INSERT INTO project(id, name, created_at) VALUES('p1','P',0)")
    return db, ScheduleStore(db)


def test_scheduler_fires_once_when_due_and_advances(sched):
    db, store = sched
    t0 = datetime(2026, 10, 14, 7, 59)
    s = store.create("p1", "tạo clip buổi sáng", "0 8 * * *", "youtube-to-shorts", False, at=t0)
    assert datetime.fromtimestamp(s["nextRunAt"]) == datetime(2026, 10, 14, 8, 0)
    fired = []
    clock = {"now": t0}
    sch = Scheduler(store, lambda sc: fired.append(sc["id"]) or "thr_1", clock=lambda: clock["now"])
    assert sch.tick() == []                                                         # chưa tới giờ
    clock["now"] = datetime(2026, 10, 14, 8, 0, 20)
    assert sch.tick() == [s["id"]] and fired == [s["id"]]
    after = store.get(s["id"])
    assert after["lastThreadId"] == "thr_1" and datetime.fromtimestamp(after["nextRunAt"]) == datetime(2026, 10, 15, 8, 0)
    assert sch.tick() == []                                                         # không chạy lặp trong cùng phút


def test_scheduler_catch_up_window_disabled_and_deleted_project(sched):
    db, store = sched
    t0 = datetime(2026, 10, 14, 7, 0)
    a = store.create("p1", "việc A", "0 8 * * *", None, False, at=t0)
    b = store.create("p1", "việc B", "0 8 * * *", None, False, at=t0, enabled=False)
    ran = []
    clock = {"now": datetime(2026, 10, 14, 8, 30)}                                  # daemon bật lại muộn 30' → chạy bù một lần
    Scheduler(store, lambda sc: ran.append(sc["message"]) or "t", clock=lambda: clock["now"]).tick()
    assert ran == ["việc A"]                                                        # B đang tắt → không chạy
    c = store.create("p1", "việc C", "0 8 * * *", None, False, at=t0)
    ran.clear()
    clock["now"] = datetime(2026, 10, 14, 11, 0)                                    # muộn 3 giờ → bỏ qua lần đó, không chạy bù
    Scheduler(store, lambda sc: ran.append(sc["message"]), clock=lambda: clock["now"]).tick()
    assert ran == [] and datetime.fromtimestamp(store.get(c["id"])["nextRunAt"]) == datetime(2026, 10, 15, 8, 0)

    def gone(_):
        raise ApiError(404, "PROJECT_NOT_FOUND", "x")
    d = store.create("p1", "việc D", "0 12 * * *", None, False, at=datetime(2026, 10, 14, 11, 0))
    clock["now"] = datetime(2026, 10, 14, 12, 0, 10)
    Scheduler(store, gone, clock=lambda: clock["now"]).tick()
    assert store.get(d["id"])["enabled"] is False                                   # project đã xoá → tự tắt lịch

    def flaky(_):
        raise ApiError(424, "LLM_UNAVAILABLE", "x")
    e = store.create("p1", "việc E", "0 13 * * *", None, False, at=datetime(2026, 10, 14, 12, 30))
    clock["now"] = datetime(2026, 10, 14, 13, 0, 5)
    Scheduler(store, flaky, clock=lambda: clock["now"]).tick()
    assert store.get(e["id"])["enabled"] and store.get(e["id"])["nextRunAt"] == pytest.approx(clock["now"].timestamp() + 300, abs=1)   # thử lại sau 5 phút


def test_schedule_api_and_run_now_uses_the_agent(settings, tmp_path):
    llm = ScriptedLLM([{"tool": "final", "message": "Đã chạy theo lịch."}])
    with make_client(settings, llm) as c:
        pid = c.post("/projects", json={"name": "Lịch"}).json()["id"]
        r = c.post("/schedules", json={"projectId": pid, "message": "mỗi sáng tạo 1 clip từ video mới", "cron": "0 8 * * *", "skill": "youtube-to-shorts"})
        assert r.status_code == 201 and r.json()["enabled"] and r.json()["nextRunAt"] > time.time()
        sid = r.json()["id"]
        assert c.post("/schedules", json={"projectId": pid, "message": "abc", "cron": "* * * * *"}).json()["error"]["code"] == "CRON_TOO_FREQUENT"
        assert c.post("/schedules", json={"projectId": "prj_nope", "message": "abc xyz", "cron": "0 8 * * *"}).status_code == 404
        assert c.post("/schedules", json={"projectId": pid, "message": "abc xyz", "cron": "0 8 * * *", "skill": "khong-co"}).status_code == 404
        assert c.patch(f"/schedules/{sid}", json={"enabled": False}).json()["enabled"] is False
        assert c.patch(f"/schedules/{sid}", json={"cron": "bậy bạ"}).status_code in (400, 422)
        run = c.post(f"/schedules/{sid}/run-now")
        assert run.status_code == 202
        t = wait_run(c, run.json()["threadId"])
        assert t["thread"]["skill"] == "youtube-to-shorts" and t["messages"][0]["content"]["text"].startswith("mỗi sáng") and t["run"]["status"] == "succeeded"
        assert c.get(f"/schedules?projectId={pid}").json()[0]["id"] == sid
        assert c.delete(f"/schedules/{sid}").status_code == 204 and c.get(f"/schedules?projectId={pid}").json() == []


# ---------- MCP ----------
def test_mcp_client_lists_and_calls_tools_and_cleans_up():
    m = McpManager([{"name": "Tài liệu!", "command": [sys.executable, FAKE_MCP]}])
    try:
        assert m.status == [{"name": "t_i_li_u_", "ok": True, "error": None, "tools": 2}] or m.status[0]["ok"]
        specs = m.specs()
        assert set(specs) == {f"mcp_{m.servers[0].name}_echo", f"mcp_{m.servers[0].name}_lookup"}
        echo = specs[f"mcp_{m.servers[0].name}_echo"]
        assert echo.approval == "external" and echo.schema()["required"] == ["text"]
        assert echo.handler(echo.parse({"text": "xin chào"}), None)["text"] == "echo: xin chào"
        with pytest.raises(ApiError):
            echo.parse({})                                              # thiếu tham số bắt buộc
        with pytest.raises(ApiError):
            echo.parse({"text": 5})                                     # sai kiểu
    finally:
        m.stop()


def test_mcp_bad_command_and_silent_server_do_not_crash():
    m = McpManager([{"name": "hong", "command": ["lenh-khong-ton-tai-xyz"]}, {"name": "thieu"}, {"command": ["x"]}])
    assert [s["ok"] for s in m.status] == [False, False, False] and m.specs() == {}
    srv = McpManager([{"name": "im", "command": [sys.executable, FAKE_MCP, "silent"]}])
    try:
        s = srv.servers[0]
        s.timeout = 0.6
        with pytest.raises(McpError):
            s.call("echo", {"text": "a"})
    finally:
        srv.stop()


def test_mcp_servers_empty_by_default_and_listed_in_api(client):
    assert client.get("/mcp/servers").json() == []
    assert not [t for t in client.get("/agent/tools").json() if t["name"].startswith("mcp_")]
