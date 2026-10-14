"""Route Avatar AI."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..errors import ApiError
from .library import MAX_IMAGE
from .service import AvatarService, engines


class UpdateBody(BaseModel):
    name: str | None = None
    mouth: dict | None = None


def build_router(svc: AvatarService, machine_tier: str, dependencies: list) -> APIRouter:
    r = APIRouter(dependencies=dependencies)

    @r.get("/avatar/engines")
    async def list_engines():
        return engines(machine_tier)

    @r.get("/avatars")
    async def list_avatars():
        return svc.lib.list()

    @r.put("/avatars", status_code=201)
    async def create(request: Request, name: str, realPerson: bool | None = None, consentId: str | None = None,
                     mouthX: float = 0.5, mouthY: float = 0.72, mouthW: float = 0.18):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_IMAGE:
                raise ApiError(413, "PAYLOAD_TOO_LARGE", "Ảnh quá lớn (tối đa 15 MB)")
        return svc.lib.create(name, bytes(data), realPerson, consentId, {"x": mouthX, "y": mouthY, "w": mouthW})

    @r.patch("/avatars/{aid}")
    async def update(aid: str, body: UpdateBody):
        return svc.lib.update(aid, body.name, body.mouth)

    @r.delete("/avatars/{aid}", status_code=204)
    async def delete(aid: str):
        svc.lib.delete(aid)

    @r.get("/avatars/{aid}/image")
    async def image(aid: str):
        return FileResponse(svc.lib.image_path(aid), media_type="image/png")

    @r.post("/projects/{pid}/avatar/render", status_code=202)
    async def render(pid: str):
        svc.repo.get_project(pid)
        return svc.start(pid)

    return r
