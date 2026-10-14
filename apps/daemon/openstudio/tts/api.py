"""Route: giọng đọc, nhân bản giọng, bản ghi đồng ý."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..errors import ApiError
from .engines import ENGINES, preset_voices
from .service import TTSService

MAX_SAMPLE_BYTES = 60 * 1024 * 1024


class ConsentBody(BaseModel):
    kind: Literal["voice", "face"] = "voice"
    subject: str = Field(min_length=1, max_length=120)
    confirmed: bool
    projectId: str | None = None


class PreviewBody(BaseModel):
    voice: str = Field(min_length=3, max_length=120)
    text: str = Field(min_length=1, max_length=400)
    lang: str = Field(default="vi", pattern=r"^[a-z]{2,3}$")


def build_router(svc: TTSService, dependencies: list) -> APIRouter:
    r = APIRouter(dependencies=dependencies)

    @r.get("/tts/engines")
    async def engines():
        return svc.engine_status()

    @r.get("/voices")
    async def voices(lang: str | None = None):
        return [*preset_voices(lang), *svc.voices.list(lang)]

    @r.post("/consents", status_code=201)
    async def create_consent(body: ConsentBody):
        return svc.consents.create(body.kind, body.subject, body.confirmed, body.projectId)

    @r.get("/consents")
    async def list_consents():
        return svc.consents.list()

    @r.put("/voices/clone", status_code=201)
    async def clone(request: Request, name: str, consentId: str, engine: str = "vieneu"):
        spec = ENGINES.get(engine)
        if not spec or not spec["clone"] or spec.get("hidden") and not svc.s.dev_fake_tts:
            raise ApiError(400, "VALIDATION_FAILED", "Engine này không hỗ trợ nhân bản giọng")
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_SAMPLE_BYTES:
                raise ApiError(413, "PAYLOAD_TOO_LARGE", "Mẫu giọng quá lớn")
        return svc.voices.create(name, engine, consentId, bytes(data), spec["languages"])

    @r.delete("/voices/{voice_id}", status_code=204)
    async def delete_voice(voice_id: str):
        svc.voices.delete(voice_id.removeprefix("clone:"))

    @r.post("/projects/{pid}/tts/synthesize", status_code=202)
    async def synthesize(pid: str):
        svc.repo.get_project(pid)
        return svc.start_synthesize(pid)

    @r.post("/projects/{pid}/tts/preview", status_code=202)
    async def preview(pid: str, body: PreviewBody):
        return svc.start_preview(pid, body.voice, body.text, body.lang)

    return r
