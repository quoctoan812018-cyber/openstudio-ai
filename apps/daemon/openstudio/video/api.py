"""Route Tạo video (ảnh → video chuyển động)."""
from __future__ import annotations

from fastapi import APIRouter

from .service import VideoService, engines


def build_router(svc: VideoService, machine_tier: str, dependencies: list) -> APIRouter:
    r = APIRouter(dependencies=dependencies)

    @r.get("/video/engines")
    async def list_engines():
        return engines(machine_tier)

    @r.post("/projects/{pid}/video/render", status_code=202)
    async def render(pid: str):
        svc.repo.get_project(pid)
        return svc.start(pid)

    return r
