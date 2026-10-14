"""Route Tạo ảnh AI."""
from __future__ import annotations

from fastapi import APIRouter

from .service import ImageService


def build_router(svc: ImageService, dependencies: list) -> APIRouter:
    r = APIRouter(dependencies=dependencies)

    @r.get("/image/status")
    async def status():
        return svc.status()

    @r.post("/projects/{pid}/image/generate", status_code=202)
    async def generate(pid: str):
        svc.repo.get_project(pid)
        return svc.start(pid)

    return r
