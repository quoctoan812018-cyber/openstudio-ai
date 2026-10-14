"""Hệ thống Template: `templates/<tên>/template.json` (+ `preview.png` tuỳ chọn).
Có sẵn (chỉ đọc) ở thư mục `templates/` của ứng dụng; của người dùng ở `<data>/templates/`. Template chỉ là cấu hình JSON (không chạy mã)."""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import Settings
from .errors import ApiError

KINDS = ("thumbnail", "editor")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}$")


def slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:48]


class TemplateStore:
    def __init__(self, settings: Settings):
        self.builtin = settings.builtin_templates_dir or settings.root / "templates"
        self.user = settings.data_dir / "templates"

    def _read(self, d: Path, builtin: bool) -> dict | None:
        try:
            t = json.loads((d / "template.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if t.get("kind") not in KINDS or not isinstance(t.get("name"), str):
            return None
        return {**t, "id": d.name, "builtin": builtin, "hasPreview": (d / "preview.png").is_file()}

    def list(self, kind: str | None = None) -> list[dict]:
        out = []
        for root, builtin in ((self.builtin, True), (self.user, False)):
            if root.is_dir():
                out += [t for d in sorted(root.iterdir()) if d.is_dir() and (t := self._read(d, builtin))]
        return [t for t in out if kind is None or t["kind"] == kind]

    def get(self, tid: str) -> dict:
        t = next((x for x in self.list() if x["id"] == tid), None)
        if not t:
            raise ApiError(404, "TEMPLATE_NOT_FOUND", "Không có template này")
        return t

    def save(self, name: str, kind: str, config: dict, description: str = "") -> dict:
        if kind not in KINDS:
            raise ApiError(400, "VALIDATION_FAILED", "kind phải là thumbnail hoặc editor")
        name = name.strip()
        tid = slug(name)
        if not name or len(name) > 80 or not NAME.match(tid):
            raise ApiError(400, "VALIDATION_FAILED", "Tên template 2–80 ký tự (chữ/số)")
        if any(t["id"] == tid and t["builtin"] for t in self.list()):
            raise ApiError(409, "TEMPLATE_BUILTIN", "Trùng tên template có sẵn; hãy đặt tên khác")
        if len(json.dumps(config)) > 20_000:
            raise ApiError(413, "PAYLOAD_TOO_LARGE", "Template quá lớn")
        d = self.user / tid
        d.mkdir(parents=True, exist_ok=True)
        (d / "template.json").write_text(json.dumps({"name": name, "kind": kind, "description": description[:300], **config}, ensure_ascii=False, indent=1), encoding="utf-8")
        return self.get(tid)

    def delete(self, tid: str) -> None:
        t = self.get(tid)
        if t["builtin"]:
            raise ApiError(409, "TEMPLATE_BUILTIN", "Template có sẵn không xoá được")
        shutil.rmtree(self.user / tid, ignore_errors=True)

    def preview(self, tid: str) -> Path:
        t = self.get(tid)
        p = (self.builtin if t["builtin"] else self.user) / tid / "preview.png"
        if not p.is_file():
            raise ApiError(404, "NOT_FOUND", "Template chưa có ảnh mẫu")
        return p


class SaveBody(BaseModel):
    name: str
    kind: str
    description: str = ""
    config: dict


def build_router(store: TemplateStore, dependencies: list) -> APIRouter:
    r = APIRouter(dependencies=dependencies)

    @r.get("/templates")
    async def list_templates(kind: str | None = None):
        return store.list(kind)

    @r.get("/templates/{tid}")
    async def get_template(tid: str):
        return store.get(tid)

    @r.get("/templates/{tid}/preview")
    async def preview(tid: str):
        return FileResponse(store.preview(tid))

    @r.post("/templates", status_code=201)
    async def save(body: SaveBody):
        return store.save(body.name, body.kind, body.config, body.description)

    @r.delete("/templates/{tid}", status_code=204)
    async def delete(tid: str):
        store.delete(tid)

    return r
