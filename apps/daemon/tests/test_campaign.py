import csv
import shutil
import zipfile

import pytest

from openstudio.campaign import catalog as K
from openstudio.campaign.state import initial_state, reducer
from openstudio.errors import ApiError

from conftest import wait_job

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="cần ffmpeg")


# ---------- thuần ----------
def test_local_price_needs_user_fx_never_invents():
    assert K.local_price(100000, {}, "USD") is None
    assert K.local_price(None, {"USD": 25000}, "USD") is None
    assert K.local_price(100000, {"USD": 25000}, "USD") is not None
    assert "100" in K.local_price(100000, {}, "VND")


def test_schedule_counts_and_timezones():
    from datetime import date
    n = K.ideas_needed(["vn", "us"], ["tiktok", "youtube"], 7)
    sched = K.build_schedule({"vn": n, "us": n}, ["vn", "us"], ["tiktok", "youtube"], 7, date(2030, 1, 7))
    assert sched and {p["market"] for p in sched} == {"vn", "us"} and len({p["id"] for p in sched}) == len(sched)
    assert all(date(2030, 1, 7) <= date.fromisoformat(p["date"]) <= date(2030, 1, 13) for p in sched)
    assert K.to_utc("2030-01-07", "12:00", "Asia/Ho_Chi_Minh").startswith("2030-01-07T05:00")


def test_reducer_validates_brief_and_blocks_bad_status():
    s = reducer(initial_state(), "set-brief", {"brief": {"goal": "Bán cà phê", "markets": ["vn", "us"], "platforms": ["tiktok"], "days": 7}})
    assert s["brief"]["markets"] == ["vn", "us"]
    for bad in ({"markets": ["xx"]}, {"days": 5}, {"platforms": []}, {"fx": {"USD": -1}}, {"priceVnd": 0}, {"startDate": "13/13"}):
        with pytest.raises(ApiError):
            reducer(s, "set-brief", {"brief": bad})
    with pytest.raises(ApiError):
        reducer(s, "set-brief", {"brief": {"unknown": 1}})
    s["posts"] = [{"id": "p001", "platform": "tiktok", "status": "planned", "caption": "", "hashtags": [], "date": "2030-01-01", "time": "12:00"}]
    with pytest.raises(ApiError) as e:
        reducer(s, "set-post", {"id": "p001", "status": "approved"})
    assert e.value.code == "STATUS_TRANSITION"
    with pytest.raises(ApiError):
        reducer(s, "set-post", {"id": "p001", "caption": "x" * 5000})


# ---------- API ----------
def cmd(client, pid, type, payload):
    r = client.post(f"/projects/{pid}/tools/campaign/commands", json={"type": type, "payload": payload})
    assert r.status_code == 200, r.text
    return r.json()


def state(client, pid):
    return client.get(f"/projects/{pid}/tools/campaign/state").json()["state"]


def run(client, resp, timeout=60):
    assert resp.status_code == 202, resp.text
    done = wait_job(client, resp.json()["id"], timeout)
    assert done["status"] == "succeeded", done
    return done


@pytest.fixture
def camp(client):
    pid = client.post("/projects", json={"name": "Chiến dịch"}).json()["id"]
    cmd(client, pid, "set-brief", {"brief": {"goal": "Ra mắt cà phê rang xay", "product": "Cà phê Đà Lạt", "facts": "Rang xay tươi mỗi tuần",
                                             "markets": ["vn", "us", "jp"], "platforms": ["tiktok", "facebook"], "days": 7, "startDate": "2030-03-04",
                                             "priceVnd": 120000, "fx": {"USD": 25000}}})
    return pid


def test_plan_requires_goal_and_internal_commands_blocked(client):
    pid = client.post("/projects", json={"name": "x"}).json()["id"]
    assert client.post(f"/projects/{pid}/campaign/plan").json()["error"]["code"] == "BRIEF_REQUIRED"
    assert client.post(f"/projects/{pid}/campaign/assets").json()["error"]["code"] == "PLAN_REQUIRED"
    r = client.post(f"/projects/{pid}/tools/campaign/commands", json={"type": "_set-plan", "payload": {"plan": {}, "posts": []}})
    assert r.status_code >= 400


def test_plan_schedule_is_deterministic_and_covers_markets(client, camp):
    done = run(client, client.post(f"/projects/{camp}/campaign/plan"))
    st = state(client, camp)
    posts = st["posts"]
    assert done["result"]["posts"] == len(posts) > 0
    assert {p["market"] for p in posts} == {"vn", "us", "jp"} and {p["platform"] for p in posts} == {"tiktok", "facebook"}
    assert all(p["status"] == "planned" and p["title"] for p in posts)
    assert all("2030-03-04" <= p["date"] <= "2030-03-10" for p in posts)
    assert any("JPY" in w for w in st["plan"]["warnings"])           # thiếu tỷ giá JPY → cảnh báo, không bịa


@needs_ffmpeg
def test_assets_localized_per_market_and_export_package(client, camp, settings):
    run(client, client.post(f"/projects/{camp}/campaign/plan"))
    done = run(client, client.post(f"/projects/{camp}/campaign/assets"), 120)
    assert done["result"]["failed"] == 0
    posts = state(client, camp)["posts"]
    assert all(p["status"] == "ready" and p["caption"] and p["thumbnail"] for p in posts)
    us = next(p for p in posts if p["market"] == "us")
    jp = next(p for p in posts if p["market"] == "jp")
    vn = next(p for p in posts if p["market"] == "vn")
    assert "Coffee" in us["caption"] and "$" in us["caption"]                # có tỷ giá USD → giá quy đổi
    assert "コーヒー" in jp["caption"] and "¥" not in jp["caption"]            # không có tỷ giá JPY → không nhắc giá
    assert "cà phê" in vn["caption"].lower()
    assert all(not h.startswith("#") for p in posts for h in p["hashtags"]) and all(len(p["hashtags"]) <= 5 for p in posts if p["platform"] == "tiktok")
    ex = client.post(f"/projects/{camp}/campaign/export").json()
    assert ex["posts"] == len(posts) and ex["files"] > 0
    root = settings.projects_dir / camp
    assert (root / ex["csv"]).is_file()
    with (root / ex["csv"]).open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len(posts) and {"utc", "timezone", "thumbnail"} <= set(rows[0])
    assert all(r["thumbnail"] and (root / ex["folder"] / r["thumbnail"]).is_file() for r in rows)
    with zipfile.ZipFile(root / ex["zip"]) as z:
        names = z.namelist()
    assert "schedule.csv" in names and "README.md" in names and any(n.endswith("caption.txt") for n in names)
    assert state(client, camp)["export"]["posts"] == len(posts)


def test_export_without_assets_is_rejected(client, camp):
    run(client, client.post(f"/projects/{camp}/campaign/plan"))
    assert client.post(f"/projects/{camp}/campaign/export").json()["error"]["code"] == "NOTHING_TO_EXPORT"


def test_english_copy_drops_vietnamese_diacritics_but_keeps_other_languages():
    from openstudio.campaign.service import plain_latin
    assert plain_latin("Tây Nguyên coffee, Đà Lạt", "en") == "Tay Nguyen coffee, Da Lat"
    assert plain_latin("Tây Nguyên", "vi") == "Tây Nguyên" and plain_latin("コーヒー", "ja") == "コーヒー"
