import hashlib
import json
import re
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from openstudio.app import create_app
from openstudio.config import Settings

TOKEN = "test-token"
PAYLOAD = b"x" * 5000
SHA = hashlib.sha256(PAYLOAD).hexdigest()

REGISTRY = f"""
schema_version: 1
capabilities:
  stt:
    default:
      id: tiny-test
      name: Tiny test
      tier: cpu
      weights_license: MIT
      verified: true
      download:
        dest: stt/tiny-test
        files:
          - {{ url: "https://example.test/model.bin", path: model.bin, bytes: {len(PAYLOAD)}, sha256: "{SHA}" }}
    small:
      id: faster-whisper-tiny
      download:
        dest: stt/faster-whisper-tiny
        files:
          - {{ url: "https://example.test/model.bin", path: model.bin, bytes: {len(PAYLOAD)}, sha256: "{SHA}" }}
    fallback:
      id: bad-checksum
      download:
        dest: stt/bad
        files:
          - {{ url: "https://example.test/model.bin", path: model.bin, bytes: {len(PAYLOAD)}, sha256: "{'0' * 64}" }}
    excluded:
      - id: nc-model
        non_commercial: true
        download:
          dest: stt/nc
          files:
            - {{ url: "https://example.test/model.bin", path: model.bin, bytes: {len(PAYLOAD)} }}
      - id: evil-path
        download:
          dest: ../../outside
          files:
            - {{ url: "https://example.test/model.bin", path: model.bin }}
  tts:
    default: {{ ref: stt.default }}
"""


def _handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=PAYLOAD)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    reg = tmp_path / "registry.yaml"
    reg.write_text(REGISTRY, encoding="utf-8")
    return Settings(root=tmp_path, data_dir=tmp_path / "data", registry_path=reg, dev_fake_tts=True,
                    builtin_skills_dir=Path(__file__).resolve().parents[3] / "skills", builtin_templates_dir=Path(__file__).resolve().parents[3] / "templates")


FAKE_STT = [sys.executable, str(Path(__file__).parent / "fake_stt_worker.py")]


class FakeLLM:
    """Giả lập Ollama: /models và /chat/completions. `mode` điều khiển hành vi để test các nhánh lỗi."""

    def __init__(self):
        self.mode = "ok"
        self.calls: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen3:4b"}]})
        body = json.loads(request.content)
        native = request.url.path.endswith("/api/chat")
        self.calls.append(body)
        user = body["messages"][-1]["content"]
        sys0 = body["messages"][0]["content"]
        if "short-video editor" in sys0:  # chấm điểm đoạn hay: "bí mật" → 9 điểm, còn lại 3
            ids = [int(x) for x in re.findall(r"id=(\d+)", user)]
            texts = dict(re.findall(r"id=(\d+) \([^)]*\): (.*)", user))
            wins = [{"id": i, "score": 9 if "bí mật" in texts.get(str(i), "").lower() else 3, "title": f"Tiêu đề {i}", "hook": f"Móc câu {i}",
                     "reason": "giả lập"} for i in ids]
            return self._reply(json.dumps({"windows": wins}, ensure_ascii=False), native)
        if "narration for a summary video" in sys0:
            title = re.search(r"Clip title: (.*)", user).group(1)
            return self._reply(json.dumps({"narration": f"Phần này nói về {title}."}, ensure_ascii=False), native)
        if "podcast producer" in sys0:  # dàn ý
            return self._reply(json.dumps({"title": "Cà phê Việt", "summary": "Tập nói về cà phê Việt Nam.", "takeaways": ["Robusta đậm", "Arabica thơm"],
                                           "sections": [{"title": "Mở đầu", "points": ["chào"]}, {"title": "Hạt cà phê", "points": ["Robusta", "Arabica"]},
                                                        {"title": "Kết", "points": ["tóm tắt"]}]}, ensure_ascii=False), native)
        if "write dialogue for a podcast" in sys0:  # lượt nói: lấy tên người dẫn từ "hosted by A, B"
            hosts = [h.strip() for h in re.search(r"hosted by (.*?)\. Write", sys0).group(1).split(",")]
            sec = re.search(r"Current section: (.*)", user).group(1)
            turns = [{"speaker": hosts[i % len(hosts)], "text": f"{('**' if i == 0 else '')}{hosts[(i + 1) % len(hosts)] if i == 1 else ''}{': ' if i == 1 else ''}Lượt {i + 1} của chương {sec} nói về cà phê."} for i in range(4)]
            return self._reply(json.dumps({"turns": turns}, ensure_ascii=False), native)
        if "social media strategist" in sys0:
            n = int(re.search(r"Give exactly (\d+) new ideas", user).group(1))
            used = [t for t in re.search(r"Already used titles \(do not repeat\): (.*)", user).group(1).split(", ") if t != "(none)"]
            ideas = [{"title": f"Mẹo cà phê số {len(used) + i + 1}", "hook": f"Bạn đã biết mẹo {len(used) + i + 1}?", "angle": "Giải thích ngắn một mẹo pha cà phê."} for i in range(n)]
            return self._reply(json.dumps({"ideas": ideas}, ensure_ascii=False), native)
        if "social-media copywriter" in sys0:
            lang = re.search(r"Write EVERYTHING in ([A-Za-z ]+?) \(natural", sys0).group(1)
            idx = re.search(r"title \"Mẹo cà phê số (\d+)\"", user)
            k = idx.group(1) if idx else "0"
            price = re.search(r"use exactly\): (.*)", user)
            base = {"English": f"Coffee tip {k}: brew it right", "Japanese": f"コーヒーのコツ {k}: おいしく淹れよう", "Simplified Chinese": f"咖啡小贴士 {k}：冲泡技巧",
                    "Korean": f"커피 팁 {k}: 맛있게 내리기"}.get(lang, f"Mẹo cà phê {k}: pha đúng cách")
            cap = base + (f" ({price.group(1)})" if price else "")
            return self._reply(json.dumps({"title": base, "caption": cap, "hashtags": ["#coffee", "Coffee", "tips tip!"], "script": "HOOK: " + base + " BODY: ... CTA: ...",
                                           "thumbnail_text": base[:20]}, ensure_ascii=False), native)
        tail = user[user.index("Input JSON array"):]
        items = json.loads(tail[tail.index("\n") + 1:])
        system = body["messages"][0]["content"]
        if self.mode == "wrong_length" and len(items) > 1:
            out = items[:-1]
        elif self.mode == "garbage":
            return self._reply("xin lỗi, tôi không thể", native)
        elif "proofreader" in system:
            out = [i.replace("ca phe", "cà phê") for i in items]
        elif "shorten" in system.lower():  # giữ nửa đầu số từ
            out = [" ".join(i.split()[: max(1, len(i.split()) // 2)]) for i in items]
        else:
            out = [f"EN:{i}" for i in items]
        if self.mode == "bare_array":
            content = "<think>nghĩ...</think>```json\n" + json.dumps(out, ensure_ascii=False) + "\n```"
        else:
            content = json.dumps({"lines": out}, ensure_ascii=False)
        return self._reply(content, native)

    @staticmethod
    def _reply(content: str, native: bool) -> httpx.Response:
        if native:
            return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def client(settings, fake_llm):
    app = create_app(settings, TOKEN, lambda: httpx.Client(transport=httpx.MockTransport(_handler)),
                     stt_cmd=FAKE_STT, llm_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(fake_llm.handler)),
                     sep_engine="fake")
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        c.app_state = app.state
        yield c


def wait_job(client, job_id: str, timeout: float = 5.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError("job không kết thúc kịp")
