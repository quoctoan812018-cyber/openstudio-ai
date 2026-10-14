"""Route Thumbnail."""
from __future__ import annotations

from fastapi import APIRouter

from .service import ThumbnailService


def build_router(svc: ThumbnailService, dependencies: list) -> APIRouter:
    r = APIRouter(dependencies=dependencies)

    @r.post("/projects/{pid}/thumbnail/render", status_code=202)
    async def render(pid: str):
        svc.repo.get_project(pid)
        return svc.start(pid)

    return r
