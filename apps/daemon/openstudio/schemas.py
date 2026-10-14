"""Pydantic schemas — nguồn sự thật cho packages/protocol (sinh type TypeScript từ đây)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ApiErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ApiErrorResponse(BaseModel):
    error: ApiErrorBody


class Progress(BaseModel):
    phase: str
    percent: float
    message: str = ""
    completed: int = 0
    failed: int = 0
    total: int = 0


class Job(BaseModel):
    id: str
    projectId: str | None = None
    tool: str | None = None
    type: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    progress: Progress | None = None
    error: ApiErrorBody | None = None
    result: dict[str, Any] | None = None
    createdAt: float
    startedAt: float | None = None
    finishedAt: float | None = None


class Event(BaseModel):
    id: int
    type: str
    projectId: str | None = None
    jobId: str | None = None
    ts: float
    data: dict[str, Any] = Field(default_factory=dict)


class Gpu(BaseModel):
    name: str
    vram_gb: float
    driver: str | None = None
    vendor: str


class Hardware(BaseModel):
    os: str
    cpu: dict[str, Any]
    ram_gb: float
    gpus: list[Gpu]
    cuda_available: bool
    tier: Literal["cpu", "gpu8", "gpu12", "gpu16plus"]
    tier_label: str
    note: str | None = None


class Tool(BaseModel):
    id: str
    name: str
    description: str
    min_tier: Literal["cpu", "gpu8", "gpu12", "gpu16plus"]
    phase: int
    implemented: bool
    available: bool
    locked_reason: str | None = None


class ModelInfo(BaseModel):
    id: str
    name: str
    capability: str
    role: str
    tier: str | None = None
    code_license: str | None = None
    weights_license: str | None = None
    commercial_ok: bool | str | None = None
    non_commercial: bool
    verified: bool
    notes: str | None = None
    warning: str | None = None
    downloadable: bool
    size_bytes: int | None = None
    status: Literal["not_installed", "downloading", "installed"]
    downloadJobId: str | None = None


class Project(BaseModel):
    id: str
    name: str
    createdAt: float
    settings: dict[str, Any] = Field(default_factory=dict)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ProjectPatch(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ToolCommand(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    expectedRevision: int | None = None


class ModelDownloadRequest(BaseModel):
    acknowledge_non_commercial: bool = False


class JobCreate(BaseModel):
    type: Literal["demo.sleep"]
    params: dict[str, Any] = Field(default_factory=dict)
    projectId: str | None = None


class UserSettings(BaseModel):
    language: Literal["vi", "en"] = "vi"
    ai_label_metadata: bool = True
    ai_label_watermark: bool = False
    cloud_providers_enabled: bool = False


class LibraryFile(BaseModel):
    projectId: str
    path: str
    bytes: int
    modifiedAt: float
    kind: str
