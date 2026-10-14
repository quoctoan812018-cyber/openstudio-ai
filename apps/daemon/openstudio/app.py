"""FastAPI app factory — Runtime API v1."""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from typing import Callable

import httpx
from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, hardware
from .config import Settings
from .db import Database
from .errors import ApiError
from .events import EventBus
from .jobs import JobRunner, demo_sleep_handler
from .models import ModelManager
from .repo import Repo
from .schemas import (JobCreate, ModelDownloadRequest, ProjectCreate, ProjectPatch, ToolCommand, UserSettings)
from .security import check_bearer, safe_join, sign_file, verify_file_sig
from .agent.api import build_router as agent_router
from .agent.loop import AgentLoop
from .agent.mcp import McpManager
from .agent.scheduler import ScheduleStore, Scheduler
from .agent.skills import SkillStore
from .agent.store import ThreadStore
from .agent.tools import Services, build_tools
from .dubbing.api import build_router as dubbing_router
from .dubbing.service import DubbingService
from .highlights.api import build_router as highlights_router
from .highlights.service import HighlightsService
from .doctor import run_checks
from .assets import AssetStore
from .editor.api import build_router as editor_router
from .editor.service import EditorService
from .templates import TemplateStore
from .templates import build_router as templates_router
from .thumbnail.api import build_router as thumbnail_router
from .thumbnail.service import ThumbnailService
from .avatar.api import build_router as avatar_router
from .avatar.library import AvatarLibrary
from .avatar.service import AvatarService
from .campaign.api import build_router as campaign_router
from .campaign.service import CampaignService
from .podcast.api import build_router as podcast_router
from .podcast.music import MusicLibrary
from .podcast.service import PodcastService
from .subtitles.api import build_router as subtitles_router
from .subtitles.llm import LLMClient
from .subtitles.service import SubtitleService
from .tts.api import build_router as tts_router
from .tts.service import TTSService
from .tts.voices import ConsentStore, VoiceLibrary
from .tools import list_tools


def create_app(settings: Settings, token: str, client_factory: Callable[[], httpx.Client] | None = None,
               stt_cmd: list[str] | None = None,
               llm_client_factory: Callable[[], httpx.Client] | None = None,
               sep_engine: str = "demucs", agent_opts: dict | None = None) -> FastAPI:
    settings.ensure_dirs()
    db = Database(settings.db_path)
    bus = EventBus(db)
    runner = JobRunner(db, bus)
    runner.register("demo.sleep", demo_sleep_handler)
    models = ModelManager(settings.registry_path, settings.models_dir, db, runner, client_factory)
    repo = Repo(db, bus, settings.projects_dir)
    hw = hardware.detect()
    llm = LLMClient(settings.llm_base_url, settings.llm_model, client_factory=llm_client_factory,
                    provider=settings.llm_provider, num_ctx=settings.llm_num_ctx)
    subtitles = SubtitleService(settings, repo, runner, models, llm, hw, stt_cmd)
    consents = ConsentStore(db, settings.data_dir / "consent")
    tts = TTSService(settings, repo, runner, models, hw, VoiceLibrary(settings.voices_dir, consents), consents)
    dubbing = DubbingService(settings, repo, runner, models, subtitles, tts, llm, sep_engine)
    highlights = HighlightsService(settings, repo, runner, subtitles, tts, llm)
    music = MusicLibrary(settings.data_dir / "music")
    podcast = PodcastService(settings, repo, runner, tts, llm, music)
    campaign = CampaignService(settings, repo, runner, subtitles, llm)
    assets = AssetStore(settings)
    editor = EditorService(settings, repo, runner, assets)
    thumbnail = ThumbnailService(settings, repo, runner, assets)
    avatar = AvatarService(settings, repo, runner, assets, AvatarLibrary(settings.avatars_dir, consents), subtitles)
    template_store = TemplateStore(settings)

    # ---- Agent: dùng ĐÚNG các service ở trên (cùng state machine với giao diện) ----
    ao = {"scheduler": True, "approval_timeout": 24 * 3600.0, "max_steps": 14, "mcp": settings.mcp_servers, **(agent_opts or {})}
    services = Services(settings, repo, runner, models, subtitles, tts, dubbing, highlights, podcast, music, llm, campaign, thumbnail, editor, avatar, assets)
    mcp = McpManager(ao["mcp"])
    agent_tools = {**build_tools(services), **mcp.specs()}
    thread_store = ThreadStore(db, bus)
    skill_store = SkillStore(settings.skills_dir, settings.data_dir / "skills", settings.data_dir / "skills.json", lambda: set(agent_tools))
    agent = AgentLoop(services, agent_tools, thread_store, skill_store, llm, runner, ao["approval_timeout"], ao["max_steps"])
    schedule_store = ScheduleStore(db)

    def run_schedule(sch: dict) -> str | None:
        """Lịch đến hạn → tạo hội thoại mới và chạy Agent (cùng đường với người dùng gõ tin nhắn)."""
        th = thread_store.create(sch["projectId"], f"Lịch: {sch['message'][:50]}", sch["skill"], sch["autoApprove"])
        agent.start(th["id"], sch["message"], sch["skill"], sch["autoApprove"])
        return th["id"]

    scheduler = Scheduler(schedule_store, run_schedule)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        bus.loop = asyncio.get_running_loop()
        if ao["scheduler"]:
            scheduler.start()
        yield
        scheduler.stop()
        mcp.stop()
        runner.shutdown()
        db.close()

    app = FastAPI(title="OpenStudio AI Runtime", version=__version__, lifespan=lifespan)
    app.state.db, app.state.bus, app.state.runner, app.state.models, app.state.repo = db, bus, runner, models, repo
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.web_origins, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["authorization", "content-type", "last-event-id"],
    )

    # ---- lỗi thống nhất {error:{code,message,details?}} ----
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError):
        return JSONResponse(e.body(), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        errs = [{"loc": list(x["loc"]), "msg": x["msg"]} for x in e.errors()]
        return JSONResponse(ApiError(400, "VALIDATION_FAILED", "Dữ liệu không hợp lệ", {"errors": errs}).body(), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(e.status_code, "HTTP_ERROR")
        return JSONResponse(ApiError(e.status_code, code, str(e.detail)).body(), status_code=e.status_code)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    async def auth(request: Request):
        check_bearer(request, token)

    api = APIRouter(dependencies=[Depends(auth)])

    # ---- hệ thống ----
    @api.get("/system/hardware")
    async def system_hardware():
        return hw

    def read_prefs() -> UserSettings:
        try:
            return UserSettings(**json.loads(settings.settings_file.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return UserSettings()

    @api.get("/system/doctor")
    async def system_doctor():
        return await run_in_threadpool(run_checks, settings, llm)

    @api.get("/settings")
    async def get_settings():
        return {**read_prefs().model_dump(), "data_dir": str(settings.data_dir), "version": __version__,
                "llm": {"base_url": settings.llm_base_url, "model": settings.llm_model}}

    @api.put("/settings")
    async def put_settings(body: UserSettings):
        settings.settings_file.write_text(body.model_dump_json(indent=2), encoding="utf-8")
        return body

    # ---- mô hình ----
    @api.get("/models")
    async def list_models():
        return models.list()

    @api.post("/models/{model_id}/download", status_code=202)
    async def download_model(model_id: str, body: ModelDownloadRequest | None = None):
        return models.start_download(model_id, (body or ModelDownloadRequest()).acknowledge_non_commercial)

    @api.delete("/models/{model_id}", status_code=204)
    async def delete_model(model_id: str):
        models.delete(model_id)

    # ---- project ----
    @api.get("/projects")
    async def list_projects():
        return repo.list_projects()

    @api.post("/projects", status_code=201)
    async def create_project(body: ProjectCreate):
        return repo.create_project(body.name)

    @api.get("/projects/{pid}")
    async def get_project(pid: str):
        return repo.get_project(pid)

    @api.patch("/projects/{pid}")
    async def patch_project(pid: str, body: ProjectPatch):
        return repo.rename_project(pid, body.name)

    @api.delete("/projects/{pid}", status_code=204)
    async def delete_project(pid: str, confirm: bool = False):
        if not confirm:
            raise ApiError(409, "DELETE_CONFIRMATION_REQUIRED", "Xoá project sẽ xoá toàn bộ file; thêm ?confirm=true")
        repo.delete_project(pid)

    # ---- công cụ / state machine / phiên bản ----
    @api.get("/tools")
    async def tools():
        return list_tools(hw["tier"])

    @api.get("/projects/{pid}/tools/{tool}/state")
    async def tool_state(pid: str, tool: str):
        return repo.get_state(pid, tool)

    @api.post("/projects/{pid}/tools/{tool}/commands")
    async def tool_command(pid: str, tool: str, body: ToolCommand):
        if body.type.startswith("_"):
            raise ApiError(400, "VALIDATION_FAILED", "Lệnh nội bộ không dùng được qua API")
        return repo.apply_command(pid, tool, body.type, body.payload, body.expectedRevision)

    @api.get("/projects/{pid}/tools/{tool}/revisions")
    async def revisions(pid: str, tool: str):
        return repo.list_revisions(pid, tool)

    @api.get("/projects/{pid}/artifacts")
    async def artifacts(pid: str):
        return repo.list_artifacts(pid)

    # ---- job ----
    @api.get("/jobs")
    async def list_jobs(projectId: str | None = None):
        return runner.list(projectId)

    @api.post("/jobs", status_code=202)
    async def create_job(body: JobCreate):
        return runner.submit(body.type, body.params, body.projectId)

    @api.get("/jobs/{job_id}")
    async def get_job(job_id: str):
        job = runner.get(job_id)
        if not job:
            raise ApiError(404, "JOB_NOT_FOUND", "Không có job này")
        return job

    @api.post("/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        return runner.cancel(job_id)

    # ---- SSE ----
    @api.get("/events")
    async def events(request: Request, projectId: str | None = None, jobId: str | None = None,
                     lastEventId: int = Query(0), replayOnly: bool = False,
                     last_event_id: str | None = Header(None)):
        start = int(last_event_id) if last_event_id and last_event_id.isdigit() else lastEventId

        async def gen():
            async for ev in bus.stream(projectId, jobId, start, replayOnly):
                if await request.is_disconnected():
                    return
                if ev is None:
                    yield ": ping\n\n"
                else:
                    yield f"id: {ev['id']}\nevent: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---- thư viện file ----
    @api.get("/library")
    async def library(projectId: str | None = None):
        return repo.library(projectId)

    @api.post("/projects/{pid}/file-url")
    async def file_url(pid: str, body: dict):
        """URL ký sẵn, hết hạn sau 1 giờ, chỉ dùng được cho đúng file này."""
        repo.get_project(pid)
        path = str(body.get("path", ""))
        p = safe_join(settings.projects_dir / pid, path)
        if not p.is_file():
            raise ApiError(404, "FILE_NOT_FOUND", "Không có file này")
        exp = int(time.time()) + 3600
        return {"url": f"/files/{pid}/{path}?exp={exp}&sig={sign_file(token, pid, path, exp)}"}

    @api.get("/llm/status")
    async def llm_status():
        return {**llm.status(), "base_url": settings.llm_base_url}

    @app.get("/files/{pid}/{path:path}")
    async def get_file(request: Request, pid: str, path: str, exp: int | None = None, sig: str | None = None):
        if not (exp is not None and sig and verify_file_sig(token, pid, path, exp, sig, time.time())):
            check_bearer(request, token)
        repo.get_project(pid)
        p = safe_join(settings.projects_dir / pid, path)
        if not p.is_file():
            raise ApiError(404, "FILE_NOT_FOUND", "Không có file này")
        return FileResponse(p)

    app.include_router(subtitles_router(subtitles, [Depends(auth)]))
    app.include_router(tts_router(tts, [Depends(auth)]))
    app.include_router(dubbing_router(dubbing, [Depends(auth)]))
    app.include_router(highlights_router(highlights, [Depends(auth)]))
    app.include_router(podcast_router(podcast, music, [Depends(auth)]))
    app.include_router(campaign_router(campaign, [Depends(auth)]))
    app.include_router(editor_router(assets, editor, [Depends(auth)]))
    app.include_router(thumbnail_router(thumbnail, [Depends(auth)]))
    app.include_router(avatar_router(avatar, hw["tier"], [Depends(auth)]))
    app.include_router(templates_router(template_store, [Depends(auth)]))
    app.state.tts = tts
    app.include_router(agent_router(agent, thread_store, skill_store, schedule_store, mcp, repo, run_schedule, [Depends(auth)]))
    app.state.agent, app.state.scheduler, app.state.skills = agent, scheduler, skill_store
    app.include_router(api)
    if settings.web_dist and (settings.web_dist / "index.html").is_file():   # chế độ web/Docker: cùng origin nên không cần CORS
        app.mount("/", StaticFiles(directory=settings.web_dist, html=True), name="web")
    return app
