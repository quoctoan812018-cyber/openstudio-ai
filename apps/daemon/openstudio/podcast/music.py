"""Nhạc cho podcast: nhạc tổng hợp có sẵn (tự sinh bằng toán học → không dính bản quyền), thư viện nhạc người dùng
(bắt buộc ghi giấy phép), nhạc nền ducking theo giọng."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np

from ..db import new_id, now
from ..errors import ApiError
from ..media import probe
from ..tts import audio as A

SR = A.MIX_SR
BUILTIN = "builtin"
KINDS = ("intro", "outro", "bed")
BUILTIN_INFO = {"id": BUILTIN, "name": "Nhạc tổng hợp có sẵn (đơn giản, không bản quyền)", "kind": "all", "license": "Tự sinh bởi OpenStudio (CC0)",
                "builtin": True}


def _env(n: int, attack: float, release: float) -> np.ndarray:
    a, r = int(attack * SR), int(release * SR)
    e = np.ones(n, dtype=np.float32)
    if a:
        e[:a] = np.linspace(0, 1, min(a, n), dtype=np.float32)
    if r:
        e[-r:] *= np.linspace(1, 0, min(r, n), dtype=np.float32)
    return e


def _tone(freq: float, seconds: float, attack: float = 0.02, release: float = 0.6) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    wave = np.sin(2 * math.pi * freq * t) + 0.35 * np.sin(2 * math.pi * 2 * freq * t) + 0.15 * np.sin(2 * math.pi * 3 * freq * t)
    return (wave * _env(len(t), attack, release) * 0.25).astype(np.float32)


def _limit(x: np.ndarray, peak: float = 0.5) -> np.ndarray:
    """Các nốt chồng nhau cộng lại có thể vượt 1.0 → chuẩn hoá đỉnh để không bị méo."""
    m = float(np.abs(x).max()) if len(x) else 0.0
    return (x * (peak / m)).astype(np.float32) if m > peak else x


def builtin_intro(seconds: float = 6.0) -> np.ndarray:
    """Arpeggio la thứ đi lên rồi ngân."""
    out = np.zeros(int(seconds * SR), dtype=np.float32)
    for k, f in enumerate([220.0, 261.63, 329.63, 440.0, 523.25]):
        s = int(k * 0.35 * SR)
        tone = _tone(f, seconds - k * 0.35, 0.01, 1.8)
        out[s: s + len(tone)] += tone[: len(out) - s]
    return _limit(out)


def builtin_outro(seconds: float = 6.0) -> np.ndarray:
    out = np.zeros(int(seconds * SR), dtype=np.float32)
    for k, f in enumerate([523.25, 440.0, 329.63, 261.63, 220.0]):
        s = int(k * 0.4 * SR)
        tone = _tone(f, seconds - k * 0.4, 0.01, 1.6)
        out[s: s + len(tone)] += tone[: len(out) - s]
    return _limit(out)


def builtin_bed(seconds: float) -> np.ndarray:
    """Pad hợp âm la thứ, biên độ dao động chậm, liền mạch cả bài (không cần loop)."""
    t = np.arange(int(seconds * SR)) / SR
    pad = sum(np.sin(2 * math.pi * f * t + p) for f, p in ((110.0, 0.0), (220.0, 1.0), (261.63, 2.0), (329.63, 0.5)))
    lfo = 0.75 + 0.25 * np.sin(2 * math.pi * 0.07 * t)
    return _limit((pad * lfo * 0.12).astype(np.float32))


def loop_to(data: np.ndarray, seconds: float, crossfade: float = 1.5) -> np.ndarray:
    """Lặp một đoạn nhạc cho đủ độ dài, nối bằng crossfade để không bị 'cạch'."""
    n = int(seconds * SR)
    if len(data) == 0:
        return np.zeros(n, dtype=np.float32)
    if len(data) >= n:
        return data[:n].copy()
    cf = min(int(crossfade * SR), len(data) // 3)
    out = data.copy()
    while len(out) < n:
        if cf:
            ramp = np.linspace(0, 1, cf, dtype=np.float32)
            out[-cf:] = out[-cf:] * (1 - ramp) + data[:cf] * ramp
            out = np.concatenate([out, data[cf:]])
        else:
            out = np.concatenate([out, data])
    return out[:n]


def fade_io(data: np.ndarray, fade_in: float = 0.0, fade_out: float = 0.0) -> np.ndarray:
    out = data.copy()
    a, b = int(fade_in * SR), int(fade_out * SR)
    if a:
        out[:a] *= np.linspace(0, 1, min(a, len(out)), dtype=np.float32)
    if b:
        out[-b:] *= np.linspace(1, 0, min(b, len(out)), dtype=np.float32)
    return out


def duck_envelope(voice: np.ndarray, depth_db: float = -12.0, attack: float = 0.06, release: float = 0.5, frame: float = 0.02,
                  threshold: float = 0.01) -> np.ndarray:
    """Đường gain (0–1) cho nhạc nền: hạ `depth_db` dB khi có giọng, lên lại sau `release` giây khi hết giọng."""
    hop = max(1, int(frame * SR))
    n = len(voice) // hop + 1
    rms = np.array([np.sqrt(np.mean(voice[i * hop:(i + 1) * hop] ** 2)) if i * hop < len(voice) else 0.0 for i in range(n)], dtype=np.float32)
    target = np.where(rms > threshold, 10 ** (depth_db / 20), 1.0).astype(np.float32)
    g = np.ones(n, dtype=np.float32)
    ka, kr = math.exp(-frame / max(attack, 1e-3)), math.exp(-frame / max(release, 1e-3))
    cur = 1.0
    for i in range(n):
        k = ka if target[i] < cur else kr   # giảm nhanh (attack), phục hồi chậm (release)
        cur = k * cur + (1 - k) * target[i]
        g[i] = cur
    return np.interp(np.arange(len(voice)), np.arange(n) * hop + hop / 2, g).astype(np.float32)


class MusicLibrary:
    """Nhạc người dùng thêm vào. Mỗi bài PHẢI kèm ghi chú giấy phép/nguồn (CC0, tự sáng tác, đã mua bản quyền…)."""

    def __init__(self, root: Path):
        self.root = root

    def _meta(self, mid: str) -> dict | None:
        p = self.root / mid / "meta.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    def list(self) -> list[dict]:
        out = [BUILTIN_INFO]
        if self.root.is_dir():
            for d in sorted(self.root.iterdir()):
                m = self._meta(d.name)
                if m:
                    out.append(m)
        return out

    def create(self, name: str, kind: str, license_note: str, data: bytes) -> dict:
        name, license_note = name.strip(), license_note.strip()
        if not name or len(name) > 80:
            raise ApiError(400, "VALIDATION_FAILED", "Tên bài 1–80 ký tự")
        if kind not in KINDS:
            raise ApiError(400, "VALIDATION_FAILED", "kind phải là intro, outro hoặc bed")
        if len(license_note) < 3 or len(license_note) > 300:
            raise ApiError(400, "LICENSE_REQUIRED", "Hãy ghi giấy phép/nguồn của bài nhạc (ví dụ CC0, tự sáng tác, đã mua bản quyền)")
        if not data:
            raise ApiError(400, "VALIDATION_FAILED", "File rỗng")
        mid = new_id("mus_")
        d = self.root / mid
        d.mkdir(parents=True)
        try:
            raw = d / "upload.bin"
            raw.write_bytes(data)
            info = probe(raw)
            if info["duration"] > 20 * 60:
                raise ApiError(400, "VALIDATION_FAILED", "Bài nhạc tối đa 20 phút")
            raw_wav = d / "audio48.wav"
            r = subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-y", "-v", "error", "-i", str(raw), "-vn", "-ac", "1", "-ar", str(SR),
                                "-c:a", "pcm_s16le", str(raw_wav)], capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode != 0:
                raise ApiError(422, "AUDIO_EXTRACT_FAILED", "Không đọc được file nhạc")
            raw.unlink()
            meta = {"id": mid, "name": name, "kind": kind, "license": license_note, "duration": round(info["duration"], 2), "createdAt": now(),
                    "builtin": False}
            (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            return meta
        except BaseException:
            shutil.rmtree(d, ignore_errors=True)
            raise

    def delete(self, mid: str) -> None:
        if not self._meta(mid):
            raise ApiError(404, "MUSIC_NOT_FOUND", "Không có bài nhạc này")
        shutil.rmtree(self.root / mid, ignore_errors=True)

    def load(self, mid: str) -> np.ndarray:
        if not self._meta(mid):
            raise ApiError(404, "MUSIC_NOT_FOUND", f"Không có bài nhạc '{mid}'")
        return A.read_mono(self.root / mid / "audio48.wav", SR)

    def resolve(self, choice: str | None, kind: str, seconds: float | None = None) -> np.ndarray | None:
        """None = không dùng; 'builtin' = nhạc tổng hợp; còn lại là id trong thư viện."""
        if not choice:
            return None
        if choice == BUILTIN:
            return {"intro": builtin_intro, "outro": builtin_outro}.get(kind, lambda: builtin_bed(seconds or 60))()
        return self.load(choice)
