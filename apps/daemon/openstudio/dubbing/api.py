"""Route công cụ Lồng tiếng."""
from __future__ import annotations

from fastapi import APIRouter

from .service import DubbingService


def build_router(svc: DubbingService, dependencies: list) -> APIRouter:
    r = APIRouter(prefix="/projects/{pid}/dubbing", dependencies=dependencies)

    @r.post("/plan")
    async def plan(pid: str):
        svc.repo.get_project(pid)
        return svc.build_plan(pid)

    @r.post("/synthesize", status_code=202)
    async def synthesize(pid: str):
        svc.repo.get_project(pid)
        return svc.start_synthesize(pid)

    @r.post("/mix", status_code=202)
    async def mix(pid: str):
        svc.repo.get_project(pid)
        return svc.start_mix(pid)

    return r
