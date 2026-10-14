"""Route Podcast + thư viện nhạc."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..errors import ApiError
from .music import MusicLibrary
from .service import PodcastService

MAX_MUSIC_BYTES = 80 * 1024 * 1024


def build_router(svc: PodcastService, library: MusicLibrary, dependencies: list) -> APIRouter:
    r = APIRouter(dependencies=dependencies)

    @r.post("/projects/{pid}/podcast/script", status_code=202)
    async def script(pid: str):
        svc.repo.get_project(pid)
        return svc.start_script(pid)

    @r.post("/projects/{pid}/podcast/produce", status_code=202)
    async def produce(pid: str):
        svc.repo.get_project(pid)
        return svc.start_produce(pid)

    @r.get("/music")
    async def list_music():
        return library.list()

    @r.put("/music", status_code=201)
    async def add_music(request: Request, name: str, kind: str, license: str):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_MUSIC_BYTES:
                raise ApiError(413, "PAYLOAD_TOO_LARGE", "File nhạc quá lớn")
        return library.create(name, kind, license, bytes(data))

    @r.delete("/music/{music_id}", status_code=204)
    async def delete_music(music_id: str):
        library.delete(music_id)

    return r
