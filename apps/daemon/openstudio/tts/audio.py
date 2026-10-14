"""Xử lý audio cho TTS/lồng tiếng: đo thời lượng, co giãn tốc độ, ghép theo mốc thời gian, xuất file."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr

from ..errors import ApiError
from ..security import redact

MIX_SR = 48000


def _ffmpeg() -> str:
    p = shutil.which("ffmpeg")
    if not p:
        raise ApiError(424, "TOOL_MISSING", "Không tìm thấy ffmpeg. Hãy cài FFmpeg và thêm vào PATH.")
    return p


def _run(args: list[str]) -> None:
    r = subprocess.run([_ffmpeg(), "-y", "-v", "error", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise ApiError(422, "FFMPEG_FAILED", "FFmpeg lỗi: " + redact(r.stderr[-400:]))


def duration_of(path: Path) -> float:
    info = sf.info(str(path))
    return info.frames / info.samplerate


def read_mono(path: Path, sr: int = MIX_SR) -> np.ndarray:
    data, rate = sf.read(str(path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    return soxr.resample(mono, rate, sr) if rate != sr else mono


def write_wav(path: Path, data: np.ndarray, sr: int = MIX_SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.clip(data, -1.0, 1.0), sr, subtype="PCM_16")


def atempo_filter(tempo: float) -> str:
    """atempo chỉ nhận 0.5–2.0 mỗi bộ lọc; ghép chuỗi nếu cần."""
    parts, t = [], tempo
    while t > 2.0:
        parts.append("atempo=2.0")
        t /= 2.0
    while t < 0.5:
        parts.append("atempo=0.5")
        t /= 0.5
    parts.append(f"atempo={t:.4f}")
    return ",".join(parts)


def change_tempo(src: Path, dst: Path, tempo: float) -> None:
    """Đổi tốc độ giữ nguyên cao độ. tempo>1 là nhanh hơn."""
    if abs(tempo - 1.0) < 0.005:
        if src != dst:
            shutil.copyfile(src, dst)
        return
    _run(["-i", str(src), "-filter:a", atempo_filter(tempo), "-ar", str(MIX_SR), "-ac", "1", "-c:a", "pcm_s16le", str(dst)])


def trim_silence(data: np.ndarray, sr: int, threshold: float = 0.006, keep: float = 0.04) -> np.ndarray:
    """Cắt khoảng lặng đầu/cuối (giữ lại `keep` giây) để mốc thời gian khớp với lời nói thật."""
    idx = np.flatnonzero(np.abs(data) > threshold)
    if idx.size == 0:
        return data
    k = int(keep * sr)
    return data[max(0, idx[0] - k): min(len(data), idx[-1] + 1 + k)]


def fade(data: np.ndarray, sr: int, ms: float = 12.0) -> np.ndarray:
    n = min(int(sr * ms / 1000), len(data) // 2)
    if n <= 0:
        return data
    out = data.copy()
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    out[:n] *= ramp
    out[-n:] *= ramp[::-1]
    return out


def place_on_timeline(clips: list[tuple[np.ndarray, float]], total_seconds: float, sr: int = MIX_SR) -> np.ndarray:
    """Đặt từng đoạn (mảng mono sr, thời điểm bắt đầu giây) lên một timeline; đoạn chồng nhau thì cộng."""
    end = max([s + len(c) / sr for c, s in clips] + [total_seconds])
    out = np.zeros(int(end * sr) + 1, dtype=np.float32)
    for clip, start in clips:
        i = int(round(start * sr))
        out[i:i + len(clip)] += clip
    return out


def concat_with_gaps(clips: list[tuple[np.ndarray, float]], sr: int = MIX_SR) -> tuple[np.ndarray, list[tuple[float, float]]]:
    """Nối các đoạn, mỗi đoạn kèm khoảng lặng phía sau (giây). Trả về mảng + (start, end) từng đoạn."""
    parts, spans, t = [], [], 0.0
    for clip, gap in clips:
        spans.append((round(t, 3), round(t + len(clip) / sr, 3)))
        parts.append(clip)
        parts.append(np.zeros(int(gap * sr), dtype=np.float32))
        t += len(clip) / sr + gap
    return (np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)), spans


def export_audio(src: Path, dst: Path, *, loudnorm: bool = True, ai_label: bool = True, bitrate: str = "192k") -> None:
    """WAV hoặc MP3 (theo đuôi dst), chuẩn hoá âm lượng, ghi metadata 'nội dung tạo bởi AI'."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    args = ["-i", str(src)]
    if loudnorm:
        args += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000"]
    if ai_label:
        args += ["-metadata", "comment=AI-generated audio (OpenStudio AI)", "-metadata", "ai_generated=true"]
    if dst.suffix.lower() == ".mp3":
        args += ["-c:a", "libmp3lame", "-b:a", bitrate]
    elif dst.suffix.lower() == ".wav":
        args += ["-c:a", "pcm_s16le"]
    else:
        raise ApiError(400, "VALIDATION_FAILED", "Định dạng xuất phải là wav hoặc mp3")
    _run([*args, str(dst)])
