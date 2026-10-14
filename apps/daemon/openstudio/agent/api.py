"""Route: hội thoại Agent, phê duyệt, Skills, lịch chạy, MCP."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ..errors import ApiError
from .loop import AgentLoop
from .mcp import McpManager
from .scheduler import ScheduleStore
from .skills import TEMPLATE, SkillStore
from .store import ThreadStore


class ThreadCreate(BaseModel):
    title: str = Field(default="", max_length=120)
    skill: str | None = Field(default=None, max_length=60)
    autoApprove: bool = False


class ThreadPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    autoApprove: bool | None = None
    skill: str | None = Field(default=None, max_length=60)


class MessageBody(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    skill: str | None = Field(default=None, max_length=60)
    autoApprove: bool | None = None


class Decision(BaseModel):
    decision: str = Field(pattern=r"^(approve|reject)$")


class EnabledBody(BaseModel):
    enabled: bool


class SkillBody(BaseModel):
    markdown: str = Field(min_length=20, max_length=40_000)


class ScheduleCreate(BaseModel):
    projectId: str
    message: str = Field(min_length=3, max_length=4000)
    cron: str = Field(min_length=9, max_length=60)
    skill: str | None = Field(default=None, max_length=60)
    autoApprove: bool = False
    enabled: bool = True


class SchedulePatch(BaseModel):
    message: str | None = Field(default=None, min_length=3, max_length=4000)
    cron: str | None = Field(default=None, min_length=9, max_length=60)
    skill: str | None = None
    autoApprove: bool | None = None
    enabled: bool | None = None


def build_router(loop: AgentLoop, store: ThreadStore, skills: SkillStore, schedules: ScheduleStore, mcp: McpManager, repo, run_schedule,
                 dependencies: list) -> APIRouter:
    r = APIRouter(dependencies=dependencies)

    @r.get("/agent/tools")
    async def tools():
        return [{"name": t.name, "description": t.description, "approval": t.approval, "schema": t.schema()} for t in loop.tools.values()]

    # ---- hội thoại ----
    @r.post("/projects/{pid}/threads", status_code=201)
    async def create_thread(pid: str, body: ThreadCreate):
        repo.get_project(pid)
        if body.skill:
            skills.get(body.skill)
        return store.create(pid, body.title, body.skill, body.autoApprove)

    @r.get("/projects/{pid}/threads")
    async def list_threads(pid: str):
        repo.get_project(pid)
        return store.list(pid)

    @r.get("/threads/{tid}")
    async def get_thread(tid: str):
        th = store.get(tid)
        run = loop.runner.get(th["runJobId"]) if th["runJobId"] else None
        return {"thread": th, "messages": store.messages(tid), "pendingApprovals": store.approvals(tid, "pending"), "run": run}

    @r.patch("/threads/{tid}")
    async def patch_thread(tid: str, body: ThreadPatch):
        store.get(tid)
        f = {}
        if body.title is not None:
            f["title"] = body.title
        if body.autoApprove is not None:
            f["auto_approve"] = body.autoApprove
        if body.skill is not None:
            if body.skill:
                skills.get(body.skill)
            f["skill"] = body.skill or None
        store.update(tid, **f)
        return store.get(tid)

    @r.post("/threads/{tid}/messages", status_code=202)
    async def send(tid: str, body: MessageBody):
        return loop.start(tid, body.text, body.skill, body.autoApprove)

    @r.post("/threads/{tid}/cancel")
    async def cancel(tid: str):
        return {"job": loop.cancel(tid)}

    # ---- phê duyệt ----
    @r.get("/approvals")
    async def approvals(threadId: str | None = None, status: str | None = None):
        return store.approvals(threadId, status)

    @r.post("/approvals/{aid}")
    async def decide(aid: str, body: Decision):
        return store.resolve(aid, body.decision)

    # ---- skills ----
    @r.get("/skills")
    async def list_skills():
        return [s.public() for s in skills.list()]

    @r.get("/skills/template")
    async def template():
        return {"markdown": TEMPLATE}

    @r.get("/skills/{name}")
    async def get_skill(name: str):
        return skills.get(name).public(with_body=True)

    @r.put("/skills/{name}/enabled")
    async def set_enabled(name: str, body: EnabledBody):
        return skills.set_enabled(name, body.enabled).public()

    @r.post("/skills", status_code=201)
    async def create_skill(body: SkillBody):
        return skills.create(body.markdown).public(with_body=True)

    @r.delete("/skills/{name}", status_code=204)
    async def delete_skill(name: str):
        skills.delete(name)

    @r.get("/skills/{name}/export")
    async def export_skill(name: str):
        return PlainTextResponse(skills.export(name), media_type="text/markdown; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="{name}.SKILL.md"'})

    # ---- lịch ----
    @r.get("/schedules")
    async def list_schedules(projectId: str | None = None):
        return schedules.list(projectId)

    @r.post("/schedules", status_code=201)
    async def create_schedule(body: ScheduleCreate):
        repo.get_project(body.projectId)
        if body.skill:
            skills.get(body.skill)
        return schedules.create(body.projectId, body.message, body.cron, body.skill, body.autoApprove, body.enabled)

    @r.patch("/schedules/{sid}")
    async def patch_schedule(sid: str, body: SchedulePatch):
        if body.skill:
            skills.get(body.skill)
        return schedules.update(sid, **body.model_dump(exclude_none=True))

    @r.delete("/schedules/{sid}", status_code=204)
    async def delete_schedule(sid: str):
        schedules.delete(sid)

    @r.post("/schedules/{sid}/run-now", status_code=202)
    async def run_now(sid: str):
        s = schedules.get(sid)
        tid = run_schedule(s)
        if not tid:
            raise ApiError(409, "RUN_FAILED", "Không khởi chạy được")
        return {"threadId": tid}

    @r.get("/mcp/servers")
    async def mcp_servers():
        return mcp.status

    return r
