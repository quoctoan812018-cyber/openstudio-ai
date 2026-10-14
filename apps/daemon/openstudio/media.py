"""Bao FFmpeg/ffprobe. Luôn gọi bằng danh sách đối số (không qua shell)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .errors import ApiError
from .security import redact
from .workers.runner import run_process


def _exe(name: str) -> str:
    p = shutil.which(name)
    if not p:
        raise ApiError(424, "TOOL_MISSING", f"Không tìm thấy {name}. Hãy cài FFmpeg và thêm vào PATH.")
    return p


def probe(path: Path) -> dict:
    try:
        out = subprocess.run(
            [_exe("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=True).stdout
    except subprocess.CalledProcessError as e:
        raise ApiError(422, "MEDIA_UNREADABLE", "Không đọc được file media: " + redact(e.stderr[-300:]))
    data = json.loads(out)
    v = next((s for s in data.get("streams", []) if s["codec_type"] == "video" and s.get("disposition", {}).get("attached_pic") != 1), None)
    a = next((s for s in data.get("streams", []) if s["codec_type"] == "audio"), None)
    if not a:
        raise ApiError(422, "NO_AUDIO", "File không có luồng âm thanh")
    return {
        "duration": float(data["format"].get("duration") or a.get("duration") or 0),
        "hasVideo": v is not None,
        "width": int(v["width"]) if v else None,
        "height": int(v["height"]) if v else None,
    }


def extract_audio(src: Path, dst: Path) -> None:
    """Âm thanh mono 16 kHz PCM — định dạng Whisper cần."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([_exe("ffmpeg"), "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
                        "-c:a", "pcm_s16le", str(dst)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise ApiError(422, "AUDIO_EXTRACT_FAILED", "Không tách được âm thanh: " + redact(r.stderr[-300:]))


def run_ffmpeg(args: list[str], duration: float, cwd: Path, *, on_progress: Callable[[float], None],
               cancelled: Callable[[], bool]) -> None:
    """Chạy ffmpeg với -progress, báo tiến độ 0..100, huỷ được."""
    cmd = [_exe("ffmpeg"), "-y", "-v", "error", "-nostats", "-progress", "pipe:1", *args]
    def on_line(line: str) -> None:
        if line.startswith("out_time_us=") and duration > 0:
            try:
                on_progress(min(99.0, int(line.split("=", 1)[1]) / 1e6 / duration * 100))
            except ValueError:
                pass
    code, tail = run_process(cmd, cwd=cwd, on_line=on_line, cancelled=cancelled)
    if code != 0:
        raise ApiError(422, "FFMPEG_FAILED", "FFmpeg lỗi: " + redact(tail[-400:]))
