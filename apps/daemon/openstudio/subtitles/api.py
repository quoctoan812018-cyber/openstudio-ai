"""Route của công cụ Phụ đề & Dịch."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..errors import ApiError
from ..security import safe_join
from .service import MEDIA_EXT, SubtitleService, safe_filename

Lang = Field(pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")


class FetchBody(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


class TranscribeBody(BaseModel):
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")
    model: str | None = None
    polish: bool | None = None


class TranslateBody(BaseModel):
    targets: list[str] = Field(min_length=1, max_length=20)
    tone: Literal["neutral", "formal", "casual"] | None = None
    market: str | None = Field(default=None, max_length=40)


class ExportBody(BaseModel):
    lang: str = Lang
    format: Literal["srt", "vtt", "ass"] = "srt"
    second: str | None = None
    order: Literal["primary-top", "primary-bottom"] = "primary-top"
    layout: Literal["horizontal", "vertical"] = "horizontal"


class BurnBody(BaseModel):
    lang: str = Lang
    second: str | None = None
    order: Literal["primary-top", "primary-bottom"] = "primary-top"
    layout: Literal["horizontal", "vertical"] = "horizontal"
    fit: Literal["pad", "crop"] = "pad"
    font: str = Field(default="Arial", max_length=60, pattern=r"^[\w .\-]+$")
    size: int | None = Field(default=None, ge=12, le=300)


def build_router(svc: SubtitleService, dependencies: list) -> APIRouter:
    r = APIRouter(prefix="/projects/{pid}/subtitles", dependencies=dependencies)

    @r.put("/upload", status_code=202)
    async def upload(pid: str, filename: str, request: Request):
        svc.repo.get_project(pid)
        name = safe_filename(filename)
        if not any(name.endswith(e) for e in MEDIA_EXT):
            raise ApiError(400, "VALIDATION_FAILED", "Định dạng media không được hỗ trợ")
        dest = safe_join(svc.project_dir(pid), f"source/{name}")
        dest.parent.mkdir(exist_ok=True)
        size = 0
        with dest.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                f.write(chunk)
        if size == 0:
            dest.unlink(missing_ok=True)
            raise ApiError(400, "VALIDATION_FAILED", "File rỗng")
        return svc.start_prepare(pid, f"source/{name}", {"type": "upload", "filename": filename})

    @r.post("/fetch", status_code=202)
    async def fetch(pid: str, body: FetchBody):
        svc.repo.get_project(pid)
        return svc.start_fetch(pid, body.url)

    @r.post("/transcribe", status_code=202)
    async def transcribe(pid: str, body: TranscribeBody):
        return svc.start_transcribe(pid, body.language, body.model, body.polish)

    @r.post("/translate", status_code=202)
    async def translate(pid: str, body: TranslateBody):
        return svc.start_translate(pid, body.targets, body.tone, body.market)

    @r.post("/export")
    async def export(pid: str, body: ExportBody):
        return svc.export(pid, body.lang, body.format, body.second, body.order, body.layout)

    @r.post("/burn", status_code=202)
    async def burn(pid: str, body: BurnBody):
        return svc.start_burn(pid, body.model_dump())

    return r
