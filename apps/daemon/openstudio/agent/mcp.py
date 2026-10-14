"""MCP client tối giản (stdio, JSON-RPC mỗi dòng một thông điệp) để cắm công cụ ngoài vào Agent.

Mặc định KHÔNG cấu hình server nào. Server khai báo trong config.toml (tệp của chính người dùng):
    [[mcp.servers]]
    name = "files"
    command = ["python", "server.py"]
Mọi tool MCP đều qua cổng phê duyệt (category `external`, không bao giờ tự duyệt) và kết quả luôn bị coi là dữ liệu không tin cậy."""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
from typing import Any

from ..errors import ApiError
from ..security import redact
from .tools import AgentCtx, ToolSpec

APPROVAL_EXTERNAL = "external"
PROTOCOL = "2024-11-05"
TIMEOUT = 30.0
SAFE = re.compile(r"[^a-z0-9_]+")


class McpError(RuntimeError):
    pass


class McpServer:
    def __init__(self, name: str, command: list[str], env: dict[str, str] | None = None, timeout: float = TIMEOUT):
        self.name, self.command, self.timeout = name, command, timeout
        self.env = env
        self.proc: subprocess.Popen | None = None
        self._id = 0
        self._lock = threading.Lock()
        self._responses: dict[int, queue.Queue] = {}
        self.tools: list[dict] = []
        self.error: str | None = None

    def start(self) -> None:
        self.proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                     bufsize=1, env={**os.environ, **(self.env or {})}, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=self._reader, daemon=True, name=f"mcp-{self.name}").start()
        self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "openstudio-ai", "version": "0.1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.tools = self.request("tools/list", {}).get("tools", [])

    def _send(self, msg: dict) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def _reader(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            q = self._responses.get(msg.get("id")) if isinstance(msg, dict) else None
            if q is not None:
                q.put(msg)

    def request(self, method: str, params: dict) -> dict:
        with self._lock:
            self._id += 1
            rid = self._id
            q: queue.Queue = queue.Queue()
            self._responses[rid] = q
        try:
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            try:
                msg = q.get(timeout=self.timeout)
            except queue.Empty:
                raise McpError(f"MCP '{self.name}' không phản hồi {method} trong {self.timeout:.0f}s")
        finally:
            self._responses.pop(rid, None)
        if "error" in msg:
            raise McpError(str(msg["error"].get("message", msg["error"]))[:300])
        return msg.get("result", {})

    def call(self, tool: str, arguments: dict) -> dict:
        res = self.request("tools/call", {"name": tool, "arguments": arguments})
        text = "\n".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        return {"text": text[:4000], "isError": bool(res.get("isError"))}

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.kill()


def _validate(schema: dict, args: dict) -> dict:
    """Kiểm tra tối thiểu theo JSON schema của MCP: đủ trường bắt buộc và đúng kiểu cơ bản."""
    if not isinstance(args, dict):
        raise ApiError(400, "BAD_ARGS", "Tham số phải là object")
    types = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
    props = schema.get("properties", {})
    for k in schema.get("required", []):
        if k not in args:
            raise ApiError(400, "BAD_ARGS", f"Thiếu tham số bắt buộc '{k}'")
    for k, v in args.items():
        t = props.get(k, {}).get("type")
        if t in types and not isinstance(v, types[t]) or (t in ("integer", "number") and isinstance(v, bool)):
            raise ApiError(400, "BAD_ARGS", f"Tham số '{k}' phải có kiểu {t}")
    return args


class McpManager:
    def __init__(self, servers_cfg: list[dict]):
        self.servers: list[McpServer] = []
        self.status: list[dict] = []
        for c in servers_cfg:
            name, cmd = str(c.get("name", "")), c.get("command")
            if not name or not isinstance(cmd, list) or not cmd:
                self.status.append({"name": name or "?", "ok": False, "error": "cấu hình thiếu name/command", "tools": 0})
                continue
            srv = McpServer(SAFE.sub("_", name.lower()), [str(x) for x in cmd])
            try:
                srv.start()
                self.servers.append(srv)
                self.status.append({"name": srv.name, "ok": True, "error": None, "tools": len(srv.tools)})
            except (McpError, OSError) as e:
                srv.stop()
                self.status.append({"name": srv.name, "ok": False, "error": redact(str(e))[:200], "tools": 0})

    def specs(self) -> dict[str, ToolSpec]:
        out: dict[str, ToolSpec] = {}
        for srv in self.servers:
            for t in srv.tools:
                name = f"mcp_{srv.name}_{SAFE.sub('_', str(t['name']).lower())}"
                schema = t.get("inputSchema") or {"type": "object", "properties": {}}

                def handler(args: Any, ctx: AgentCtx, srv=srv, tool=t["name"]) -> dict:
                    try:
                        res = srv.call(tool, args)
                    except McpError as e:
                        raise ApiError(502, "MCP_FAILED", str(e))
                    return {"untrusted": True, "text": res["text"], "ok": not res["isError"]}

                out[name] = ToolSpec(name, f"[MCP {srv.name}] {str(t.get('description', ''))[:200]}", None, handler, APPROVAL_EXTERNAL,
                                     schema_override=schema, parser=lambda a, schema=schema: _validate(schema, a))
        return out

    def stop(self) -> None:
        for s in self.servers:
            s.stop()
