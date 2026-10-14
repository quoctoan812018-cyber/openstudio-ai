"""Engine avatar "puppet" (CPU): hoạt hình ảnh chân dung theo biên độ giọng nói — KHÔNG phải lip-sync AI.

Ảnh tĩnh được tiền xử lý thành N mức "mở miệng": vùng quanh điểm miệng người dùng chọn được kéo giãn theo chiều dọc và
thêm một hình elip tối (khoang miệng) tỉ lệ với mức mở, kèm phóng to rất nhẹ (nhịp thở). Mỗi khung hình chỉ chọn mức theo
đường bao biên độ (đã làm mượt) rồi ghép lên nền → nhanh trên CPU. Phù hợp ảnh minh hoạ/hoạt hình/mascot; với ảnh chụp thật chỉ là hiệu ứng nói đơn giản."""
from __future__ import annotations

import subprocess

import numpy as np

from ..errors import ApiError
from ..media import _exe

LEVELS = 12
FPS = 25


def envelope(samples: np.ndarray, sr: int, fps: int = FPS, attack: float = 0.55, release: float = 0.25) -> np.ndarray:
    """Đường bao biên độ 0..1 mỗi khung hình: RMS cửa sổ ~40 ms, chuẩn hoá theo phân vị 95, làm mượt lên nhanh/xuống chậm, cổng ồn nền."""
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    n_frames = max(1, int(round(len(samples) / sr * fps)))
    hop = sr / fps
    rms = np.zeros(n_frames, dtype=np.float32)
    win = int(sr * 0.04)
    for i in range(n_frames):
        c = int(i * hop + hop / 2)
        seg = samples[max(0, c - win // 2): c + win // 2]
        rms[i] = float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0
    ref = float(np.percentile(rms, 95)) if rms.size else 0.0
    if ref < 1e-4:                                    # gần như im lặng → miệng đóng
        return np.zeros(n_frames, dtype=np.float32)
    e = np.clip(rms / ref, 0.0, 1.0)
    e = np.where(e < 0.08, 0.0, e) ** 0.8             # cổng ồn nền + nén nhẹ
    out = np.zeros_like(e)
    cur = 0.0
    for i, v in enumerate(e):
        cur += (v - cur) * (attack if v > cur else release)
        out[i] = cur
    return out.astype(np.float32)


def level_for(e: float, levels: int = LEVELS) -> int:
    return int(round(float(np.clip(e, 0, 1)) * (levels - 1)))


def ffmpeg_rgb(args: list[str], w: int, h: int) -> np.ndarray:
    """Chạy ffmpeg ghi một khung rgb24 ra stdout → mảng (h, w, 3)."""
    r = subprocess.run([_exe("ffmpeg"), "-v", "error", *args, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    if r.returncode != 0 or len(r.stdout) != w * h * 3:
        raise ApiError(422, "AVATAR_RENDER_FAILED", "Không xử lý được ảnh: " + r.stderr.decode("utf-8", "replace")[-200:])
    return np.frombuffer(r.stdout, np.uint8).reshape(h, w, 3).copy()


def fit_size(iw: int, ih: int, box_w: int, box_h: int) -> tuple[int, int]:
    s = min(box_w / iw, box_h / ih)
    return max(2, int(iw * s) // 2 * 2), max(2, int(ih * s) // 2 * 2)


def shape_mask(w: int, h: int, shape: str) -> np.ndarray | None:
    """Mặt nạ alpha 0..1 (h, w, 1) cho khung: rounded (bo góc) hoặc circle (cắt vuông giữa rồi tròn)."""
    if shape == "none":
        return None
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if shape == "circle":
        d = np.hypot((xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2))
        return np.clip((1.0 - d) * min(w, h) / 2, 0, 1)[..., None]
    r = min(w, h) * 0.08
    dx = np.maximum(np.abs(xx - w / 2) - (w / 2 - r), 0)
    dy = np.maximum(np.abs(yy - h / 2) - (h / 2 - r), 0)
    return np.clip(r - np.hypot(dx, dy) + 0.5, 0, 1)[..., None]


def mouth_levels(img: np.ndarray, mouth: dict, levels: int = LEVELS, style: str = "ellipse") -> list[np.ndarray]:
    """Sinh `levels` ảnh từ mức 0 (đóng) đến mức mở tối đa."""
    h, w, _ = img.shape
    mx, my, mw = mouth["x"] * w, mouth["y"] * h, max(6.0, mouth["w"] * w)
    reach = mw * 0.9                                                # vùng bị kéo giãn: ±reach quanh miệng (theo chiều dọc)
    y0, y1 = int(max(0, my - reach)), int(min(h, my + reach))
    ys = np.arange(y0, y1, dtype=np.float32)
    out = []
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    for k in range(levels):
        t = k / (levels - 1)
        frame = img.copy()
        if t > 0:
            s = 1.0 + 0.35 * t                                       # phóng to vùng miệng theo chiều dọc
            fall = np.clip(1 - np.abs(ys - my) / reach, 0, 1)        # giảm dần ra mép vùng để không lộ đường nối
            src = np.clip(my + (ys - my) / (1 + (s - 1) * fall), 0, h - 1).astype(np.int32)
            frame[y0:y1] = img[src]
            if style == "ellipse":
                rx, ry = mw * 0.30, max(0.5, mw * 0.22 * t)
                d = ((xx - mx) / rx) ** 2 + ((yy - my) / ry) ** 2
                a = np.clip((1.0 - d) * 3.0, 0, 1)[..., None] * 0.92
                frame = (frame * (1 - a) + np.array([60, 14, 20], np.float32) * a).astype(np.uint8)
        out.append(frame)
    return out


def zoom_center(img: np.ndarray, z: float) -> np.ndarray:
    """Phóng to nhẹ quanh tâm (nhịp thở) bằng chỉ số nguyên — rẻ, đủ cho z ≤ ~1.03."""
    if z <= 1.0005:
        return img
    h, w, _ = img.shape
    ys = np.clip(((np.arange(h) - h / 2) / z + h / 2).astype(np.int32), 0, h - 1)
    xs = np.clip(((np.arange(w) - w / 2) / z + w / 2).astype(np.int32), 0, w - 1)
    return img[ys][:, xs]


def compose_levels(background: np.ndarray, levels_imgs: list[np.ndarray], pos: tuple[int, int], mask: np.ndarray | None, border: int = 0) -> list[np.ndarray]:
    """Dựng sẵn mỗi mức thành một khung đầy đủ (nền + avatar) → vòng lặp xuất khung chỉ việc ghi bytes."""
    frames = []
    H, W, _ = background.shape
    x, y = pos
    for k, a in enumerate(levels_imgs):
        a = zoom_center(a, 1.0 + 0.012 * k / max(1, len(levels_imgs) - 1))
        f = background.copy()
        ah, aw, _ = a.shape
        region = f[y:y + ah, x:x + aw]
        if mask is None:
            region[:] = a
        else:
            region[:] = (a * mask + region * (1 - mask)).astype(np.uint8)
        if border and mask is not None:
            ring = np.clip(mask - shape_inner(mask, border), 0, 1)
            region[:] = (np.array([255, 255, 255], np.float32) * ring + region * (1 - ring)).astype(np.uint8)
        frames.append(np.ascontiguousarray(f))
    assert frames[0].shape[:2] == (H, W)
    return frames


def shape_inner(mask: np.ndarray, border: int) -> np.ndarray:
    """Xấp xỉ mặt nạ thu nhỏ `border` px (để vẽ viền trắng)."""
    h, w, _ = mask.shape
    m = mask[..., 0]
    shrunk = m.copy()
    for _ in range(border):
        p = np.pad(shrunk, 1, mode="edge")
        shrunk = np.minimum.reduce([p[1:-1, 1:-1], p[:-2, 1:-1], p[2:, 1:-1], p[1:-1, :-2], p[1:-1, 2:]])
    return shrunk[..., None]
