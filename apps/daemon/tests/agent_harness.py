"""Khung kiểm thử Agent: LLM có kịch bản (quyết định từng bước) bọc quanh FakeLLM cho các prompt không phải của Agent."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from conftest import FAKE_STT, TOKEN, FakeLLM, _handler, wait_job
from openstudio.app import create_app

FAKE_MCP = str(Path(__file__).parent / "fake_mcp_server.py")


class ScriptedLLM:
    """script: danh sách bước. Mỗi bước {"tool": tên|"final", "args": dict | [dict,...], "message": văn bản (nếu final)}.
    Bước chỉ được tiến lên khi tham số hợp lệ cuối cùng đã được trả (args là list → trả lần lượt, để mô phỏng LLM điền sai rồi sửa)."""

    def __init__(self, script: list[dict], skill_pick: str = "none"):
        self.base = FakeLLM()
        self.script, self.i, self.k = list(script), 0, 0
        self.skill_pick = skill_pick
        self.prompts: list[tuple[str, str]] = []   # (system, user) của mọi lời gọi thuộc Agent
        self.bad_choice_once = False

    @staticmethod
    def _reply(obj: dict) -> httpx.Response:
        return httpx.Response(200, json={"message": {"role": "assistant", "content": json.dumps(obj, ensure_ascii=False)}})

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return self.base.handler(request)
        body = json.loads(request.content)
        sys0, user = body["messages"][0]["content"], body["messages"][-1]["content"]
        if "Pick the skill that best matches" in sys0:
            return self._reply({"skill": self.skill_pick})
        if "production assistant" not in sys0:
            return self.base.handler(request)
        self.prompts.append((sys0, user))
        step = self.script[min(self.i, len(self.script) - 1)]
        if "Decide the next step" in user:
            return self._reply({"thought": "bước tiếp theo", "tool": step["tool"]})
        if "Write the final answer" in user:
            self.i += 1
            return self._reply({"message": step.get("message", "Xong.")})
        if "Fill in the arguments" in user:
            seq = step["args"] if isinstance(step.get("args"), list) else [step.get("args", {})]
            out = seq[min(self.k, len(seq) - 1)]
            self.k += 1
            if self.k >= len(seq):
                self.i, self.k = self.i + 1, 0
            return self._reply(out)
        raise AssertionError("prompt Agent không nhận diện được: " + user[:120])

    def calls_with(self, text: str) -> list[tuple[str, str]]:
        return [p for p in self.prompts if text in p[1] or text in p[0]]


def make_client(settings, llm: ScriptedLLM, **agent_opts):
    opts = {"scheduler": False, "approval_timeout": 20.0, **agent_opts}
    app = create_app(settings, TOKEN, lambda: httpx.Client(transport=httpx.MockTransport(_handler)), stt_cmd=FAKE_STT,
                     llm_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(llm.handler)), sep_engine="fake", agent_opts=opts)
    return TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"})


def make_wav(path: Path, seconds: int = 4) -> bytes:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", str(path)], check=True)
    return path.read_bytes()


def project_with_source(c: TestClient, tmp_path: Path, name: str = "Agent") -> str:
    pid = c.post("/projects", json={"name": name}).json()["id"]
    wait_job(c, c.put(f"/projects/{pid}/subtitles/upload?filename=a.wav", content=make_wav(tmp_path / "a.wav")).json()["id"], 30)
    wait_job(c, c.post("/models/faster-whisper-tiny/download").json()["id"])
    return pid


def new_thread(c: TestClient, pid: str, **kw) -> str:
    return c.post(f"/projects/{pid}/threads", json=kw).json()["id"]


def send(c: TestClient, tid: str, text: str, **kw) -> dict:
    r = c.post(f"/threads/{tid}/messages", json={"text": text, **kw})
    assert r.status_code == 202, r.text
    return r.json()


def wait_run(c: TestClient, tid: str, timeout: float = 60) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        t = c.get(f"/threads/{tid}").json()
        if t["run"] and t["run"]["status"] in ("succeeded", "failed", "cancelled"):
            return t
        time.sleep(0.1)
    raise AssertionError("lượt chạy Agent không kết thúc: " + json.dumps(c.get(f"/threads/{tid}").json()["messages"][-3:], ensure_ascii=False)[:600])


def wait_pending(c: TestClient, tid: str, timeout: float = 30) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        p = c.get(f"/threads/{tid}").json()["pendingApprovals"]
        if p:
            return p[0]
        time.sleep(0.1)
    raise AssertionError("không có yêu cầu phê duyệt")


def kinds(thread: dict) -> list[str]:
    return [m["kind"] for m in thread["messages"]]


def tool_results(thread: dict) -> list[dict]:
    return [m["content"] for m in thread["messages"] if m["kind"] == "tool_result"]
