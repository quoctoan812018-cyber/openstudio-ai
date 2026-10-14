"""Model Manager: đọc registry.yaml, báo trạng thái cài đặt, tải có tiến độ + checksum + cảnh báo license."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any, Callable

import httpx
import yaml

from .db import Database, now
from .errors import ApiError
from .jobs import JobContext, JobRunner
from .security import safe_join

NC_WARNING = "Mô hình này có license phi thương mại — chỉ dùng cho mục đích cá nhân/phi thương mại."


def flatten_registry(doc: dict) -> list[dict]:
    """Duyệt registry: mọi dict có khoá `id` là một mô hình. Trùng id → giữ mục đầu tiên."""
    seen: dict[str, dict] = {}

    def collect(node: Any, capability: str, role: str) -> None:
        if isinstance(node, dict) and "id" in node:
            seen.setdefault(node["id"], {**node, "capability": capability, "role": role})
        elif isinstance(node, list):
            for item in node:
                collect(item, capability, role)

    for capability, roles in (doc.get("capabilities") or {}).items():
        if isinstance(roles, dict):
            for role, node in roles.items():
                collect(node, capability, role)
    return list(seen.values())


class ModelManager:
    def __init__(self, registry_path: Path, models_dir: Path, db: Database, runner: JobRunner,
                 client_factory: Callable[[], httpx.Client] | None = None):
        self.registry_path, self.models_dir, self.db, self.runner = registry_path, models_dir, db, runner
        self._client_factory = client_factory or (lambda: httpx.Client(follow_redirects=True, timeout=60))
        runner.register("model.download", self._download_job)

    def _load(self) -> list[dict]:
        if not self.registry_path.is_file():
            return []
        return flatten_registry(yaml.safe_load(self.registry_path.read_text(encoding="utf-8")) or {})

    def get_entry(self, model_id: str) -> dict:
        for e in self._load():
            if e["id"] == model_id:
                return e
        raise ApiError(404, "MODEL_NOT_FOUND", f"Không có mô hình '{model_id}' trong registry")

    def _dest(self, entry: dict) -> Path | None:
        dl = entry.get("download")
        return safe_join(self.models_dir, dl["dest"]) if dl else None

    def _is_installed(self, entry: dict) -> bool:
        dest = self._dest(entry)
        if dest is None:
            return False
        for f in entry["download"]["files"]:
            p = dest / f["path"]
            if not p.is_file() or ("bytes" in f and p.stat().st_size != f["bytes"]):
                return False
        return True

    def describe(self, entry: dict) -> dict:
        dl = entry.get("download")
        active = self.db.one("SELECT id FROM job WHERE type='model.download' AND status IN ('queued','running') "
                             "AND tool=?", (entry["id"],))
        try:
            installed = self._is_installed(entry)
            invalid = False
        except ApiError:  # dest trong registry trỏ ra ngoài thư mục models
            installed, invalid = False, True
        status = "installed" if installed else "downloading" if active else "not_installed"
        if invalid:
            dl = None
        return {
            "id": entry["id"], "name": entry.get("name", entry["id"]), "capability": entry["capability"],
            "role": entry["role"], "tier": entry.get("tier"),
            "code_license": entry.get("code_license"), "weights_license": entry.get("weights_license"),
            "commercial_ok": entry.get("commercial_ok"), "non_commercial": bool(entry.get("non_commercial", False)),
            "verified": bool(entry.get("verified", False)), "notes": entry.get("notes"),
            "warning": NC_WARNING if entry.get("non_commercial") else None,
            "downloadable": bool(dl), "size_bytes": sum(f.get("bytes", 0) for f in dl["files"]) if dl else None,
            "status": status, "downloadJobId": active["id"] if active else None,
        }

    def list(self) -> list[dict]:
        return [self.describe(e) for e in self._load()]

    def start_download(self, model_id: str, acknowledge_non_commercial: bool = False) -> dict:
        entry = self.get_entry(model_id)
        if not entry.get("download"):
            raise ApiError(422, "MODEL_NOT_DOWNLOADABLE", "Mô hình này chưa có thông tin tải trong registry")
        if entry.get("non_commercial") and not acknowledge_non_commercial:
            raise ApiError(409, "NON_COMMERCIAL_CONFIRMATION_REQUIRED", NC_WARNING, {"modelId": model_id})
        if self._is_installed(entry):
            raise ApiError(409, "MODEL_ALREADY_INSTALLED", "Mô hình đã được cài")
        return self.runner.submit("model.download", {"model_id": model_id}, tool=model_id)

    def delete(self, model_id: str) -> None:
        entry = self.get_entry(model_id)
        dest = self._dest(entry)
        if dest and dest.exists():
            shutil.rmtree(dest)
        self.db.execute("DELETE FROM model WHERE id=?", (model_id,))

    def _download_job(self, ctx: JobContext) -> dict:
        entry = self.get_entry(ctx.params["model_id"])
        dest = self._dest(entry)
        files = entry["download"]["files"]
        total = sum(f.get("bytes", 0) for f in files) or 0
        done = 0
        last = 0.0
        dest.mkdir(parents=True, exist_ok=True)
        import time
        with self._client_factory() as client:
            for idx, f in enumerate(files):
                if not f["url"].startswith("https://"):
                    raise ApiError(422, "MODEL_URL_INVALID", "URL tải phải là https")
                target = safe_join(dest, f["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                part = target.with_suffix(target.suffix + ".part")
                h = hashlib.sha256()
                try:
                    with client.stream("GET", f["url"]) as r:
                        r.raise_for_status()
                        with part.open("wb") as out:
                            for chunk in r.iter_bytes(1024 * 256):
                                ctx.check_cancel()
                                out.write(chunk)
                                h.update(chunk)
                                done += len(chunk)
                                t = time.monotonic()
                                if t - last > 0.25:
                                    last = t
                                    ctx.progress("download", done / total * 100 if total else 0,
                                                 f"{f['path']}", idx, 0, len(files))
                    size = part.stat().st_size
                    if "bytes" in f and size != f["bytes"]:
                        raise ApiError(422, "MODEL_SIZE_MISMATCH", f"{f['path']}: sai kích thước ({size} ≠ {f['bytes']})")
                    if f.get("sha256") and h.hexdigest() != f["sha256"].lower():
                        raise ApiError(422, "MODEL_CHECKSUM_MISMATCH", f"{f['path']}: sai checksum SHA-256")
                    part.replace(target)
                except BaseException:
                    part.unlink(missing_ok=True)
                    raise
        self.db.execute(
            "INSERT OR REPLACE INTO model(id, version, path, bytes, status, installed_at) VALUES(?,?,?,?,?,?)",
            (entry["id"], str(entry.get("version", "")), str(dest), done, "installed", now()),
        )
        ctx.progress("download", 100, "Hoàn tất", len(files), 0, len(files))
        return {"modelId": entry["id"], "bytes": done}
