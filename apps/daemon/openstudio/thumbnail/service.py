"""Dựng thumbnail bằng FFmpeg + ASS (font có đủ dấu tiếng Việt; libass tự chọn font dự phòng cho CJK)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..assets import AssetStore
from ..config import Settings
from ..errors import ApiError
from ..jobs import JobContext, JobRunner
from ..repo import Repo
from ..security import redact
from ..subtitles.cues import ass_escape
from .state import ASPECTS, PALETTES, TOOL, initial_state, new_variant_id, reducer

GRADIENTS = [("0x0f172a", "0x1d4ed8"), ("0x3b0764", "0xdb2777"), ("0x052e16", "0x16a34a"), ("0x431407", "0xea580c"), ("0x0c4a6e", "0x06b6d4"), ("0x1e1b4b", "0x7c3aed")]


def _bgr(hex_rgb: str, alpha: str = "00") -> str:
    return f"&H{alpha}{hex_rgb[5:7]}{hex_rgb[3:5]}{hex_rgb[1:3]}"


def _wrap(text: str, per_line: int, max_lines: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > per_line and len(lines) < max_lines - 1:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return [*lines, cur] if cur else lines


def thumb_ass(brief: dict, layout: str, palette: str, w: int, h: int) -> str:
    """ASS cho một biến thể. Tiêu đề lớn có hộp màu (BorderStyle 3) hoặc viền; phụ đề nhỏ hơn bên dưới."""
    pal = PALETTES[palette]
    portrait = h > w
    tsize = round(h * (0.062 if portrait else 0.11))
    ssize = round(tsize * 0.46)
    title_lines = _wrap(brief["title"], 14 if portrait else (18 if layout == "left" else 24), 3 if portrait else 2)
    sub_lines = _wrap(brief["subtitle"], 28 if portrait else 40, 2) if brief["subtitle"].strip() else []
    align, mx, mv = {"banner": (2, 0.05, 0.09), "center": (5, 0.07, 0.0), "left": (4, 0.06, 0.0), "top": (8, 0.05, 0.08)}[layout]
    boxed = layout in ("banner", "left")
    ml = round(w * mx)
    mr = round(w * (0.5 if layout == "left" and not portrait else mx))
    box_a = "&H20" if boxed else "&H00"
    head = ("[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
            f"PlayResX: {w}\nPlayResY: {h}\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Title,Arial,{tsize},{_bgr(pal['title'])},&H000000FF,{_bgr(pal['box'])},{box_a}{pal['box'][5:7]}{pal['box'][3:5]}{pal['box'][1:3]},-1,0,0,0,100,100,0,0,"
            f"{3 if boxed else 1},{round(tsize * (0.18 if boxed else 0.07))},0,{align},{ml},{mr},{round(h * mv)},1\n"
            f"Style: Sub,Arial,{ssize},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{max(2, ssize // 10)},0,{align},{ml},{mr},{round(h * mv)},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    lines = []
    ts = "\\N".join(ass_escape(x) for x in title_lines)
    if title_lines:
        ty = {"banner": 0.80, "center": 0.46, "left": 0.5, "top": 0.06}[layout]
        lines.append(f"Dialogue: 1,0:00:00.00,0:00:30.00,Title,,0,0,0,,{{\\pos({w // 2 if align in (2, 5, 8) else ml},{round(h * ty)})}}{ts}")
    if sub_lines:
        sy = {"banner": 0.92, "center": 0.66, "left": 0.72, "top": 0.38}[layout]
        lines.append(f"Dialogue: 1,0:00:00.00,0:00:30.00,Sub,,0,0,0,,{{\\pos({w // 2 if align in (2, 5, 8) else ml},{round(h * sy)})}}"
                     + "\\N".join(ass_escape(x) for x in sub_lines))
    return head + "\n".join(lines) + "\n"


def build_cmd(brief: dict, w: int, h: int, idx: int, bg_path: Path | None, brand_path: Path | None, ass_name: str, out_name: str) -> list[str]:
    ff = shutil.which("ffmpeg") or "ffmpeg"
    bg = brief["background"]
    dim = float(bg.get("dim", 0.35))
    cmd = [ff, "-y", "-v", "error"]
    # nền
    if bg["kind"] == "gradient" or bg_path is None:
        c0, c1 = GRADIENTS[idx % len(GRADIENTS)]
        cmd += ["-f", "lavfi", "-i", f"color=c={c0}:s={w}x{h}:d=1", "-f", "lavfi", "-i", f"color=c={c1}:s={w}x{h}:d=1"]
        base = "[0:v][1:v]blend=all_expr='A*(1-Y/H)+B*(Y/H)'[bg]"
        n_in = 2
    else:
        if bg["kind"] == "frame":
            at = float(bg.get("at", 1.0)) + 0.35 * idx          # mỗi biến thể lấy một khung hình khác nhau
            cmd += ["-ss", f"{at:.2f}"]
        else:
            cmd += ["-loop", "1"]
        # lệch vùng cắt giữa các biến thể (0, ±) để ảnh không giống hệt nhau
        shift = ((idx % 3) - 1) * 0.12
        cmd += ["-i", str(bg_path)]
        base = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}:x='(iw-{w})/2*(1+({shift}))':y='(ih-{h})/2',"
                f"eq=brightness=-{dim:.2f}:saturation=1.15[bg]")
        n_in = 1
    graph = [base]
    last = "bg"
    if brand_path is not None:
        cmd += ["-i", str(brand_path)]
        bw = max(16, int(w * float(brief["brand"]["width"])) // 2 * 2)
        pos = {"tl": "20:20", "tr": "W-w-20:20", "bl": "20:H-h-20", "br": "W-w-20:H-h-20"}[brief["brand"]["position"]]
        graph.append(f"[{n_in}:v]scale={bw}:-2,format=rgba[lg]")
        graph.append(f"[bg][lg]overlay={pos}[bl]")
        last = "bl"
    graph.append(f"[{last}]subtitles={ass_name}[out]")
    return [*cmd, "-filter_complex", ";".join(graph), "-map", "[out]", "-frames:v", "1", out_name]


class ThumbnailService:
    def __init__(self, settings: Settings, repo: Repo, runner: JobRunner, assets: AssetStore):
        self.s, self.repo, self.runner, self.assets = settings, repo, runner, assets
        repo.reducers[TOOL] = reducer
        runner.register("thumbnail.render", self._job)

    def state(self, pid: str) -> dict:
        st = self.repo.get_state(pid, TOOL)["state"]
        return {**initial_state(), **st} if st else initial_state()

    def commit(self, pid: str, type: str, payload: dict, author: str = "job") -> dict:
        return self.repo.apply_command(pid, TOOL, type, payload, None, author=author)

    def start(self, pid: str) -> dict:
        b = self.state(pid)["brief"]
        if not b["title"].strip():
            raise ApiError(409, "BRIEF_REQUIRED", "Hãy nhập tiêu đề thumbnail")
        for k in (b["background"].get("asset"), b["brand"].get("asset")):
            if k:
                self.assets.get(pid, k)
        return self.runner.submit("thumbnail.render", {}, pid, TOOL)

    def _job(self, ctx: JobContext) -> dict:
        pid = ctx.project_id
        base = self.s.projects_dir / pid
        b = self.state(pid)["brief"]
        w, h = ASPECTS[b["aspect"]]
        bg_asset = self.assets.get(pid, b["background"]["asset"]) if b["background"].get("asset") else None
        brand_asset = self.assets.get(pid, b["brand"]["asset"]) if b["brand"].get("asset") else None
        if b["background"]["kind"] == "frame" and bg_asset and bg_asset["kind"] != "video":
            raise ApiError(400, "VALIDATION_FAILED", "Nền 'khung hình' cần một video")
        out_dir = base / "exports" / "thumbnails"
        out_dir.mkdir(parents=True, exist_ok=True)
        # xoay vòng: biến thể i dùng layout i%L, palette i%P → đủ khác nhau mà không nhân tích Descartes
        picks = [(b["layouts"][i % len(b["layouts"])], b["palettes"][i % len(b["palettes"])]) for i in range(b["count"])]
        variants = []
        stamp = new_variant_id()
        for i, (lay, pal) in enumerate(picks):
            ctx.check_cancel()
            ctx.progress("render", 100 * i / len(picks), f"Biến thể {i + 1}/{len(picks)}", i, 0, len(picks))
            name = f"thumb_{stamp}_{i + 1}.png"
            ass_name = f"thumb_{stamp}_{i + 1}.ass"
            (out_dir / ass_name).write_text(thumb_ass(b, lay, pal, w, h), encoding="utf-8")
            cmd = build_cmd(b, w, h, i, (base / bg_asset["path"]) if bg_asset else None, (base / brand_asset["path"]) if brand_asset else None, ass_name, name)
            r = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True, encoding="utf-8", errors="replace")
            (out_dir / ass_name).unlink(missing_ok=True)
            if r.returncode != 0 or not (out_dir / name).is_file():
                raise ApiError(422, "THUMBNAIL_FAILED", "Không dựng được thumbnail: " + redact(r.stderr[-300:]))
            variants.append({"id": new_variant_id(), "file": f"exports/thumbnails/{name}", "layout": lay, "palette": pal, "width": w, "height": h})
        self.commit(pid, "_set-variants", {"variants": variants})
        ctx.progress("done", 100, "Hoàn tất")
        return {"variants": len(variants)}
