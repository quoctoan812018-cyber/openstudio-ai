"""Thư viện avatar do người dùng tạo. Ảnh người thật BẮT BUỘC có bản ghi đồng ý (consent kind=face), mỗi bản ghi chỉ dùng cho một avatar.
Không có avatar dựng sẵn từ người thật/người nổi tiếng."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from ..db import new_id, now
from ..errors import ApiError
from ..media import _exe
from ..tts.voices import ConsentStore
from ..assets import probe_any

MAX_IMAGE = 15 * 1024 * 1024
DEFAULT_MOUTH = {"x": 0.5, "y": 0.72, "w": 0.18}


def validate_mouth(m: dict) -> dict:
    try:
        x, y, w = float(m["x"]), float(m["y"]), float(m["w"])
    except (KeyError, TypeError, ValueError):
        raise ApiError(400, "VALIDATION_FAILED", "mouth cần x, y, w (tỉ lệ 0–1 so với ảnh)")
    if not (0.05 <= x <= 0.95 and 0.05 <= y <= 0.95 and 0.04 <= w <= 0.5):
        raise ApiError(400, "VALIDATION_FAILED", "mouth: x,y trong 0,05–0,95; w trong 0,04–0,5")
    return {"x": x, "y": y, "w": w}


class AvatarLibrary:
    def __init__(self, root: Path, consents: ConsentStore):
        self.root, self.consents = root, consents

    def _meta(self, aid: str) -> dict | None:
        p = self.root / aid / "meta.json"
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    @staticmethod
    def public(m: dict) -> dict:
        return {k: m[k] for k in ("id", "name", "realPerson", "subject", "consentId", "mouth", "width", "height", "createdAt")}

    def list(self) -> list[dict]:
        if not self.root.is_dir():
            return []
        return [self.public(m) for d in sorted(self.root.iterdir()) if (m := self._meta(d.name))]

    def get(self, aid: str) -> dict:
        m = self._meta(aid)
        if not m:
            raise ApiError(404, "AVATAR_NOT_FOUND", "Không có avatar này")
        return m

    def image_path(self, aid: str) -> Path:
        self.get(aid)
        return self.root / aid / "image.png"

    def create(self, name: str, data: bytes, real_person: bool | None, consent_id: str | None, mouth: dict | None = None) -> dict:
        name = name.strip()
        if not name or len(name) > 60:
            raise ApiError(400, "VALIDATION_FAILED", "Tên avatar 1–60 ký tự")
        if real_person is None:
            raise ApiError(400, "VALIDATION_FAILED", "Hãy nói rõ ảnh có phải người thật không (realPerson=true/false)")
        if not data or len(data) > MAX_IMAGE:
            raise ApiError(400, "VALIDATION_FAILED", "Ảnh rỗng hoặc lớn hơn 15 MB")
        subject = None
        if real_person:
            if not consent_id:
                self.consents.consume("", "face", "-", {})                     # ném CONSENT_REQUIRED kèm câu xác nhận
            c = self.consents.get(consent_id)
            if not c or c["kind"] != "face" or c["usedBy"]:
                self.consents.consume(consent_id, "face", "-", {})             # ném đúng lỗi (sai loại / đã dùng)
            subject = c["subject"]
        mouth = validate_mouth(mouth or DEFAULT_MOUTH)
        aid = new_id("av_")
        d = self.root / aid
        d.mkdir(parents=True)
        try:
            raw = d / "upload.bin"
            raw.write_bytes(data)
            info = probe_any(raw)
            if info["kind"] != "image":
                raise ApiError(400, "VALIDATION_FAILED", "File phải là ảnh (PNG/JPG/WebP)")
            r = subprocess.run([_exe("ffmpeg"), "-y", "-v", "error", "-i", str(raw), "-vf", "scale='min(1600,iw)':-2", "-frames:v", "1", str(d / "image.png")],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            raw.unlink(missing_ok=True)
            if r.returncode != 0 or not (d / "image.png").is_file():
                raise ApiError(422, "MEDIA_UNREADABLE", "Không đọc được ảnh")
            w, h = (int(x) for x in _size(d / "image.png"))
            meta = {"id": aid, "name": name, "realPerson": bool(real_person), "subject": subject, "consentId": consent_id if real_person else None,
                    "mouth": mouth, "width": w, "height": h, "sha256": hashlib.sha256(data).hexdigest(), "createdAt": now()}
            (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            if real_person:
                self.consents.consume(consent_id, "face", aid, {"avatarId": aid, "imageSha256": meta["sha256"]})
            return self.public(meta)
        except BaseException:
            shutil.rmtree(d, ignore_errors=True)
            raise

    def update(self, aid: str, name: str | None, mouth: dict | None) -> dict:
        m = self.get(aid)
        if name is not None:
            if not name.strip() or len(name) > 60:
                raise ApiError(400, "VALIDATION_FAILED", "Tên avatar 1–60 ký tự")
            m["name"] = name.strip()
        if mouth is not None:
            m["mouth"] = validate_mouth(mouth)
        (self.root / aid / "meta.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.public(m)

    def delete(self, aid: str) -> None:
        self.get(aid)
        shutil.rmtree(self.root / aid, ignore_errors=True)       # bản ghi đồng ý giữ lại làm bằng chứng


def _size(p: Path) -> tuple[int, int]:
    out = subprocess.run([_exe("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True, check=True).stdout.strip().split(",")
    return int(out[0]), int(out[1])
