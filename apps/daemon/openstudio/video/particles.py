"""Lớp hạt chuyển động vẽ bằng code (KHÔNG phải AI sinh video): cánh hoa rơi, lắc lư, lật mặt, đáp xuống mặt bàn.

Mô phỏng tất định theo `seed` → cùng brief cho cùng video (dễ kiểm thử, dễ dựng lại phiên bản).
Mỗi khung là ảnh RGBA (numpy uint8) để FFmpeg `overlay` lên ảnh nền.
"""
from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

# Bảng màu cánh hoa tông "gouache" ấm: san hô, hồng, cam, vàng mơ
PETAL_COLORS = ((244, 124, 92), (240, 132, 178), (246, 150, 60), (247, 196, 92), (232, 96, 90))
LANDED_FADE = 1.2            # giây mờ dần trước khi cánh hoa đã đáp biến mất


@dataclass
class Petal:
    born: float              # thời điểm rời khỏi điểm phát (giây)
    x0: float                # vị trí xuất phát (px)
    y0: float
    vy: float                # tốc độ rơi (px/s)
    drift: float             # trôi ngang (px/s)
    sway: float              # biên độ lắc (px)
    freq: float              # tần số lắc (Hz)
    phase: float
    spin: float              # tốc độ lật (rad/s)
    size: float              # chiều dài cánh (px)
    color: tuple[int, int, int]
    floor_y: float | None    # None = rơi ra khỏi khung
    stay: float              # giây nằm trên bàn trước khi mờ đi
    rest: float = 0.0        # góc khi đã nằm trên bàn (rad, gần ngang)

    def pose(self, t: float) -> tuple[float, float, float, float, bool] | None:
        """(x, y, góc, hệ số lật 0..1, đã đáp) tại thời điểm t, None nếu chưa sinh/đã biến mất."""
        a = t - self.born
        if a < 0:
            return None
        if self.floor_y is not None:
            t_land = (self.floor_y - self.y0) / self.vy
            if a >= t_land:
                if a > t_land + self.stay + LANDED_FADE:
                    return None
                x = self._x(t_land)
                return x, self.floor_y, self.rest, 0.7, True             # nằm gần ngang mặt bàn, hơi dẹt do phối cảnh
        x = self._x(a)
        y = self.y0 + self.vy * a + 0.5 * 18.0 * min(a, 1.5) ** 2   # tăng tốc nhẹ lúc mới rời cành
        ang = self.phase + self.spin * a
        flip = 0.45 + 0.55 * abs(math.cos(ang * 0.7))                # cánh lật → bề rộng co giãn
        return x, y, ang, flip, False

    def _x(self, a: float) -> float:
        return self.x0 + self.drift * a + self.sway * math.sin(2 * math.pi * self.freq * a + self.phase)

    def alpha(self, t: float) -> float:
        a = t - self.born
        if a < 0:
            return 0.0
        fade_in = min(1.0, a / 0.25)
        if self.floor_y is None:
            return fade_in
        t_end = (self.floor_y - self.y0) / self.vy + self.stay
        return fade_in * max(0.0, min(1.0, 1 - (a - t_end) / LANDED_FADE))


def spawn(duration: float, w: int, h: int, *, density: float, origin: tuple[float, float] | None,
          floor: float | None, seed: int) -> list[Petal]:
    """Sinh danh sách cánh hoa. density ~ số cánh/giây; origin (tỉ lệ khung) = vùng hoa; floor = tỉ lệ chiều cao mặt bàn."""
    rng = np.random.default_rng(seed)
    n = max(1, int(round(density * duration)))
    unit = min(w, h)
    out = []
    for i in range(n):
        born = (i + rng.uniform(0, 1)) * duration / n - 0.3
        if origin is None:
            x0, y0 = rng.uniform(-0.05, 1.05) * w, -0.05 * h
        else:
            x0 = (origin[0] + rng.normal(0, 0.11)) * w            # trải theo bề ngang bó hoa
            y0 = (origin[1] + rng.normal(0, 0.04)) * h
        fy = None
        if floor is not None:
            fy = (floor + rng.uniform(0, 0.12)) * h
            if fy <= y0 + 0.05 * h:
                fy = y0 + 0.05 * h
        out.append(Petal(
            born=born, x0=x0, y0=y0, vy=rng.uniform(0.07, 0.13) * h, drift=rng.normal(0, 0.03) * w,
            sway=rng.uniform(0.01, 0.035) * w, freq=rng.uniform(0.25, 0.6), phase=rng.uniform(0, 2 * math.pi),
            spin=rng.uniform(0.8, 2.5) * rng.choice((-1, 1)), size=rng.uniform(0.05, 0.08) * unit,
            color=PETAL_COLORS[int(rng.integers(len(PETAL_COLORS)))], floor_y=fy, stay=rng.uniform(4.0, 8.0),
            rest=rng.normal(0, 0.35)))
    return out


def _stamp(buf: np.ndarray, x: float, y: float, ang: float, flip: float, size: float,
           color: tuple[int, int, int], alpha: float, shadow: bool) -> None:
    """Vẽ một cánh hoa (giọt nước bo mềm, gốc đậm hơn) vào buf RGBA float32 [0..1], trộn 'over'."""
    if alpha <= 0.01:
        return
    r = size * 0.75
    x0, x1 = int(max(0, math.floor(x - r - 2))), int(min(buf.shape[1], math.ceil(x + r + 3)))
    y0, y1 = int(max(0, math.floor(y - r - 2))), int(min(buf.shape[0], math.ceil(y + r + 3)))
    if x0 >= x1 or y0 >= y1:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    dx, dy = xx - x, yy - y
    c, s = math.cos(ang), math.sin(ang)
    u = (dx * c + dy * s) / (size * 0.5)                        # trục dọc cánh, -1..1
    v = (-dx * s + dy * c) / (size * 0.42 * max(flip, 0.15))    # trục ngang, co theo độ lật
    taper = 0.45 + 0.55 * np.clip((u + 1) / 2, 0, 1) ** 0.6     # đầu tròn to, gốc thon
    d = u * u + (v / taper) ** 2
    a = np.clip((1.0 - d) / 0.25, 0, 1) * alpha * 0.95          # mép mềm kiểu cọ, hơi trong
    if shadow:                                                   # bóng đổ dưới cánh đã đáp
        sh = np.roll(np.roll(a, 2, axis=0), 2, axis=1) * 0.35
        _over(buf[y0:y1, x0:x1], np.zeros(3, np.float32), sh)
    base = np.array(color, np.float32) / 255
    shade = (0.72 + 0.28 * np.clip((u + 1) / 2, 0, 1) - 0.08 * np.clip(d, 0, 1))[..., None]   # gốc đậm, đầu sáng, viền hơi tối
    _over(buf[y0:y1, x0:x1], base * shade, a)


def _over(dst: np.ndarray, rgb: np.ndarray, a: np.ndarray) -> None:
    da = dst[..., 3]
    out_a = a + da * (1 - a)
    safe = np.where(out_a > 1e-6, out_a, 1)[..., None]
    dst[..., :3] = (rgb * a[..., None] + dst[..., :3] * (da * (1 - a))[..., None]) / safe
    dst[..., 3] = out_a


def frames(petals: list[Petal], w: int, h: int, fps: int, count: int) -> Iterator[bytes]:
    """Từng khung RGBA (bytes, w*h*4) theo thứ tự thời gian; cánh đã đáp vẽ trước (nằm dưới cánh đang rơi)."""
    for i in range(count):
        t = i / fps
        buf = np.zeros((h, w, 4), np.float32)
        live = []
        for p in petals:
            pose = p.pose(t)
            if pose is not None:
                live.append((pose, p))
        live.sort(key=lambda it: not it[0][4])
        for (x, y, ang, flip, landed), p in live:
            _stamp(buf, x, y, ang, flip, p.size, p.color, p.alpha(t), landed)
        yield (np.clip(buf, 0, 1) * 255).astype(np.uint8).tobytes()
