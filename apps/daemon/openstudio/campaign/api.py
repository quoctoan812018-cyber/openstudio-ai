"""Route Chiến dịch nội dung."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .catalog import MARKETS, PLATFORMS
from .service import CampaignService


class AssetsBody(BaseModel):
    postIds: list[str] | None = None
    force: bool = False
    renderVideos: bool = False
    autoTranslate: bool = True


class ExportBody(BaseModel):
    includeVideos: bool = Field(False, description="Chép cả video vào gói (nặng)")


def build_router(svc: CampaignService, dependencies: list) -> APIRouter:
    r = APIRouter(dependencies=dependencies)

    @r.get("/campaign/catalog")
    async def catalog():
        return {"markets": {k: {"name": v["name"], "lang": v["lang"], "currency": v["currency"], "tz": v["tz"]} for k, v in MARKETS.items()},
                "platforms": {k: {"name": v["name"], "formats": list(v["aspect"])} for k, v in PLATFORMS.items()}}

    @r.post("/projects/{pid}/campaign/plan", status_code=202)
    async def plan(pid: str):
        svc.repo.get_project(pid)
        return svc.start_plan(pid)

    @r.post("/projects/{pid}/campaign/assets", status_code=202)
    async def assets(pid: str, body: AssetsBody | None = None):
        svc.repo.get_project(pid)
        b = body or AssetsBody()
        return svc.start_assets(pid, b.postIds, b.force, b.renderVideos, b.autoTranslate)

    @r.post("/projects/{pid}/campaign/export")
    async def export(pid: str, body: ExportBody | None = None):
        svc.repo.get_project(pid)
        return svc.export(pid, (body or ExportBody()).includeVideos)

    return r
