"""Route công cụ Tóm tắt & Highlight."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .service import HighlightsService


class ExportBody(BaseModel):
    ids: list[str] | None = Field(default=None, max_length=50)


def build_router(svc: HighlightsService, dependencies: list) -> APIRouter:
    r = APIRouter(prefix="/projects/{pid}/highlights", dependencies=dependencies)

    @r.post("/analyze", status_code=202)
    async def analyze(pid: str):
        svc.repo.get_project(pid)
        return svc.start_analyze(pid)

    @r.post("/export", status_code=202)
    async def export(pid: str, body: ExportBody | None = None):
        svc.repo.get_project(pid)
        return svc.start_export(pid, (body or ExportBody()).ids)

    @r.post("/summary", status_code=202)
    async def summary(pid: str):
        svc.repo.get_project(pid)
        return svc.start_summary(pid)

    return r
