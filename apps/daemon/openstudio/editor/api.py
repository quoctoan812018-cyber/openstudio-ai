"""Route kho tài nguyên + Chỉnh sửa video."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..assets import AssetStore
from ..errors import ApiError
from .service import EditorService

MAX_BYTES = 4 * 1024**3


class AttachBody(BaseModel):
    kind: str
    assetId: str
    params: dict = Field(default_factory=dict)


class RegisterBody(BaseModel):
    path: str
    name: str | None = None


class RenderBody(BaseModel):
    preview: bool = False


def build_router(assets: AssetStore, svc: EditorService, dependencies: list) -> APIRouter:
    r = APIRouter(dependencies=dependencies)

    @r.put("/projects/{pid}/assets", status_code=201)
    async def upload(pid: str, filename: str, request: Request):
        svc.repo.get_project(pid)
        dest = assets.target(pid, filename)
        size = 0
        with dest.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BYTES:
                    f.close()
                    dest.unlink(missing_ok=True)
                    raise ApiError(413, "PAYLOAD_TOO_LARGE", "File quá lớn (tối đa 4 GB)")
                f.write(chunk)
        if size == 0:
            dest.unlink(missing_ok=True)
            raise ApiError(400, "VALIDATION_FAILED", "File rỗng")
        return assets.add_file(pid, filename, dest)

    @r.get("/projects/{pid}/assets")
    async def list_assets(pid: str):
        svc.repo.get_project(pid)
        return assets.list(pid)

    @r.post("/projects/{pid}/assets/register", status_code=201)
    async def register(pid: str, body: RegisterBody):
        svc.repo.get_project(pid)
        return assets.register_existing(pid, body.path, body.name)

    @r.delete("/projects/{pid}/assets/{aid}", status_code=204)
    async def delete_asset(pid: str, aid: str):
        svc.repo.get_project(pid)
        assets.remove(pid, aid)

    @r.post("/projects/{pid}/editor/attach")
    async def attach(pid: str, body: AttachBody):
        svc.repo.get_project(pid)
        return svc.attach(pid, body.kind, body.assetId, body.params)

    @r.post("/projects/{pid}/editor/render", status_code=202)
    async def render(pid: str, body: RenderBody | None = None):
        svc.repo.get_project(pid)
        return svc.start_render(pid, (body or RenderBody()).preview)

    return r
