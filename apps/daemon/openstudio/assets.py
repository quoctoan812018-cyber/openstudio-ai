"""Kho tài nguyên của project (video/ảnh/audio người dùng đưa vào) dùng chung cho Chỉnh sửa video, Thumbnail, Avatar.
File nằm ở `<project>/assets/`, mô tả (đã dò bằng ffprobe) ở `assets/index.json`. Đường dẫn trả về luôn tương đối với project."""
from __future__ import annotations

import json
import subprocess
import threading
import uuid
from pathlib import Path

from .config import Settings
from .errors import ApiError
from .media import _exe
from .security import redact, safe_join
from .subtitles.service import safe_filename

VIDEO_EXT = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".opus"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
MAX_BYTES = 4 * 1024**3
_lock = threading.Lock()


def probe_any(path: Path) -> dict:
    """Dò video / ảnh / audio. `kind`: video | image | audio."""
    try:
        out = subprocess.run([_exe("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=True).stdout
    except subprocess.CalledProcessError as e:
        raise ApiError(422, "MEDIA_UNREADABLE", "Không đọc được file: " + redact(e.stderr[-300:]))
    d = json.loads(out)
    v = next((s for s in d.get("streams", []) if s["codec_type"] == "video"), None)
    a = next((s for s in d.get("streams", []) if s["codec_type"] == "audio"), None)
    ext = path.suffix.lower()
    if v is None and a is None:
        raise ApiError(422, "MEDIA_UNREADABLE", "File không có hình hoặc tiếng")
    still = ext in IMAGE_EXT or (v is not None and a is None and v.get("codec_name") in ("png", "mjpeg", "webp", "bmp") and float(d["format"].get("duration") or 0) < 0.05)
    kind = "image" if still else ("video" if v is not None and ext not in AUDIO_EXT else "audio")
    return {"kind": kind, "duration": 0.0 if kind == "image" else float(d["format"].get("duration") or 0),
            "hasAudio": a is not None, "width": int(v["width"]) if v else None, "height": int(v["height"]) if v else None}


class AssetStore:
    def __init__(self, settings: Settings):
        self.s = settings

    def dir(self, pid: str) -> Path:
        d = self.s.projects_dir / pid / "assets"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _index(self, pid: str) -> dict:
        p = self.dir(pid) / "index.json"
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, pid: str, idx: dict) -> None:
        (self.dir(pid) / "index.json").write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")

    def list(self, pid: str) -> list[dict]:
        idx = self._index(pid)
        return [{"id": k, **v} for k, v in idx.items() if (self.s.projects_dir / pid / v["path"]).is_file()]

    def add_file(self, pid: str, filename: str, path: Path) -> dict:
        """Ghi nhận file đã nằm trong assets/ (sau upload). Dò media; file hỏng bị xoá."""
        try:
            info = probe_any(path)
        except ApiError:
            path.unlink(missing_ok=True)
            raise
        with _lock:
            idx = self._index(pid)
            aid = "a" + uuid.uuid4().hex[:8]
            rel = path.relative_to(self.s.projects_dir / pid).as_posix()
            idx[aid] = {"name": filename, "path": rel, **info}
            self._save(pid, idx)
        return {"id": aid, **idx[aid]}

    def register_existing(self, pid: str, rel: str, name: str | None = None) -> dict:
        """Đưa file đã có trong project (vd. exports/…mp4, source/…) vào kho mà không chép."""
        p = safe_join(self.s.projects_dir / pid, rel)
        if not p.is_file():
            raise ApiError(404, "FILE_NOT_FOUND", "Không có file này trong project")
        info = probe_any(p)
        with _lock:
            idx = self._index(pid)
            for k, v in idx.items():
                if v["path"] == rel:
                    return {"id": k, **v}
            aid = "a" + uuid.uuid4().hex[:8]
            idx[aid] = {"name": name or p.name, "path": rel, **info}
            self._save(pid, idx)
        return {"id": aid, **idx[aid]}

    def get(self, pid: str, aid: str) -> dict:
        a = self._index(pid).get(aid)
        if not a or not (self.s.projects_dir / pid / a["path"]).is_file():
            raise ApiError(404, "ASSET_NOT_FOUND", f"Không có tài nguyên {aid}")
        return {"id": aid, **a}

    def remove(self, pid: str, aid: str) -> None:
        with _lock:
            idx = self._index(pid)
            a = idx.pop(aid, None)
            if a is None:
                raise ApiError(404, "ASSET_NOT_FOUND", f"Không có tài nguyên {aid}")
            if a["path"].startswith("assets/"):
                (self.s.projects_dir / pid / a["path"]).unlink(missing_ok=True)
            self._save(pid, idx)

    def target(self, pid: str, filename: str) -> Path:
        name = safe_filename(filename)
        ext = Path(name).suffix.lower()
        if ext not in VIDEO_EXT | AUDIO_EXT | IMAGE_EXT:
            raise ApiError(400, "VALIDATION_FAILED", "Định dạng không được hỗ trợ (video, ảnh hoặc audio phổ biến)")
        dest = self.dir(pid) / f"{uuid.uuid4().hex[:6]}_{name}"
        return safe_join(self.s.projects_dir / pid, dest.relative_to(self.s.projects_dir / pid).as_posix())
