"""Dựng lệnh FFmpeg từ dòng thời gian (hàm thuần: dễ kiểm thử, không chạy ffmpeg)."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..subtitles.cues import ass_escape, fmt_ass
from .state import ASPECTS, seg_duration, timeline_duration

XFADE_MAX_ATEMPO = 2.0


def canvas(settings: dict, preview: bool) -> tuple[int, int]:
    short = 360 if preview else int(settings["quality"])
    a, b = ASPECTS[settings["aspect"]]
    w, h = (short * a // min(a, b), short * b // min(a, b))
    return w - w % 2, h - h % 2


def atempo_chain(speed: float) -> str:
    """atempo chỉ nhận 0.5–2.0 mỗi lần → ghép nhiều bước."""
    if abs(speed - 1.0) < 1e-6:
        return ""
    parts, s = [], speed
    while s > XFADE_MAX_ATEMPO + 1e-9:
        parts.append(f"atempo={XFADE_MAX_ATEMPO}")
        s /= XFADE_MAX_ATEMPO
    while s < 0.5 - 1e-9:
        parts.append("atempo=0.5")
        s /= 0.5
    parts.append(f"atempo={s:.5f}")
    return ",".join(parts) + ","


def _ass_color(hex_rgb: str) -> str:
    r, g, b = hex_rgb[1:3], hex_rgb[3:5], hex_rgb[5:7]
    return f"&H00{b}{g}{r}"


def texts_to_ass(texts: list[dict], w: int, h: int, watermark: str | None = None, total: float = 0.0) -> str:
    head = ("[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
            f"PlayResX: {w}\nPlayResY: {h}\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: T,Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,0,2,40,40,40,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    an = {"top": 8, "center": 5, "bottom": 2}
    lines = []
    for t in texts:
        fs = round(h * t["size"] / 100)
        tag = f"{{\\an{an[t['position']]}\\fs{fs}\\c{_ass_color(t['color'])}\\b{1 if t['bold'] else 0}\\bord{max(2, fs // 14)}}}"
        lines.append(f"Dialogue: 1,{fmt_ass(t['start'])},{fmt_ass(t['end'])},T,,{round(w * 0.05)},{round(w * 0.05)},{round(h * 0.07)},,{tag}{_wrap(t['text'], w, fs)}")
    if watermark and total > 0:
        fs = max(14, round(h * 0.025))
        lines.append(f"Dialogue: 2,{fmt_ass(0)},{fmt_ass(total)},T,,20,20,20,,{{\\an9\\fs{fs}\\c&H00FFFFFF&\\alpha&H60&\\bord1}}{ass_escape(watermark)}")
    return head + "\n".join(lines) + "\n"


def _wrap(text: str, w: int, fs: int) -> str:
    per_line = max(8, int(w * 0.9 / (fs * 0.55)))
    words, lines, cur = text.replace("\n", " ").split(), [], ""
    for wd in words:
        if cur and len(cur) + 1 + len(wd) > per_line:
            lines.append(cur)
            cur = wd
        else:
            cur = f"{cur} {wd}".strip()
    lines.append(cur)
    return "\\N".join(ass_escape(x) for x in lines)


@dataclass
class Plan:
    inputs: list[str] = field(default_factory=list)
    graph: str = ""
    total: float = 0.0
    ass: str | None = None
    out_map: tuple[str, str] = ("[v]", "[a]")


def build(tl: dict, paths: dict[str, str], *, preview: bool, ass_name: str | None, watermark: str | None = None) -> Plan:
    """tl: state editor; paths: asset id → đường dẫn tuyệt đối. Trả Plan (inputs ffmpeg + filter_complex)."""
    st = tl["settings"]
    w, h = canvas(st, preview)
    fps = int(st["fps"])
    fit = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black" if st["fit"] == "pad"
           else f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}")
    plan = Plan()
    parts: list[str] = []
    segs = tl["segments"]
    if not segs:
        raise ValueError("Dòng thời gian trống")

    # 1) từng đoạn → [v{i}] [a{i}] (cùng kích thước/fps/âm thanh stereo 48k)
    n_in = 0
    for i, s in enumerate(segs):
        d = seg_duration(s)
        p = paths[s["asset"]]
        if s["kind"] == "image":
            plan.inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{d:.3f}", "-i", p]
            parts.append(f"[{n_in}:v]{fit},setsar=1,fps={fps},format=yuv420p[v{i}]")
            parts.append(f"anullsrc=channel_layout=stereo:sample_rate=48000,atrim=duration={d:.3f},asetpts=PTS-STARTPTS[a{i}]")
        else:
            plan.inputs += ["-i", p]
            parts.append(f"[{n_in}:v]trim=start={s['in']:.3f}:end={s['out']:.3f},setpts=(PTS-STARTPTS)/{s['speed']:.5f},{fit},setsar=1,fps={fps},format=yuv420p[v{i}]")
            if s["hasAudio"]:
                vol = s["volume"] / 100
                parts.append(f"[{n_in}:a]atrim=start={s['in']:.3f}:end={s['out']:.3f},asetpts=PTS-STARTPTS,{atempo_chain(s['speed'])}"
                             f"volume={vol:.3f},aresample=48000,aformat=channel_layouts=stereo[a{i}]")
            else:
                parts.append(f"anullsrc=channel_layout=stereo:sample_rate=48000,atrim=duration={d:.3f},asetpts=PTS-STARTPTS[a{i}]")
        n_in += 1

    # 2) nối lần lượt: concat (không chuyển cảnh) hoặc xfade + acrossfade
    cur_v, cur_a, dur = "v0", "a0", seg_duration(segs[0])
    for i in range(1, len(segs)):
        d, tr = seg_duration(segs[i]), segs[i]["transition"]
        nv, na = f"j{i}v", f"j{i}a"
        if tr["type"] == "none" or tr["duration"] <= 0:
            parts.append(f"[{cur_v}][{cur_a}][v{i}][a{i}]concat=n=2:v=1:a=1[{nv}][{na}]")
            dur += d
        else:
            t = tr["duration"]
            parts.append(f"[{cur_v}][v{i}]xfade=transition={tr['type']}:duration={t:.3f}:offset={dur - t:.3f}[{nv}]")
            parts.append(f"[{cur_a}][a{i}]acrossfade=d={t:.3f}[{na}]")
            dur += d - t
        cur_v, cur_a = nv, na
    plan.total = dur
    assert abs(dur - timeline_duration(segs)) < 0.01

    # 3) lớp chèn (ảnh/video) theo thời gian kết quả
    for k, o in enumerate(tl["overlays"]):
        p = paths[o["asset"]]
        span = o["end"] - o["start"]
        ow = max(2, int(w * o["width"]) // 2 * 2)
        if o["kind"] == "image":
            plan.inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{span:.3f}", "-i", p]
            parts.append(f"[{n_in}:v]scale={ow}:-2,format=yuva420p,setpts=PTS-STARTPTS+{o['start']:.3f}/TB[ov{k}]")
        else:
            plan.inputs += ["-t", f"{span:.3f}", "-i", p]
            parts.append(f"[{n_in}:v]scale={ow}:-2,format=yuva420p,setpts=PTS-STARTPTS+{o['start']:.3f}/TB[ov{k}]")
        n_in += 1
        parts.append(f"[{cur_v}][ov{k}]overlay=x={o['x']:.4f}*(W-w):y={o['y']:.4f}*(H-h):enable='between(t,{o['start']:.3f},{o['end']:.3f})':eof_action=pass[ovo{k}]")
        cur_v = f"ovo{k}"

    # 4) chữ (+ watermark AI nếu bật) bằng ASS
    if ass_name and (tl["texts"] or watermark):
        parts.append(f"[{cur_v}]subtitles={ass_name}[vt]")
        cur_v = "vt"
        plan.ass = texts_to_ass(tl["texts"], w, h, watermark, plan.total)

    # 5) nhạc nền
    m = tl["music"]
    if m.get("asset"):
        plan.inputs += ["-stream_loop", "-1", "-i", paths[m["asset"]]]
        fo = min(float(m.get("fadeOut", 2.0)), plan.total)
        fade = f",afade=t=out:st={max(0.0, plan.total - fo):.3f}:d={fo:.3f}" if fo > 0 else ""
        parts.append(f"[{n_in}:a]atrim=duration={plan.total:.3f},asetpts=PTS-STARTPTS,volume={m['volumeDb']}dB,aresample=48000,aformat=channel_layouts=stereo{fade}[mu]")
        n_in += 1
        if m.get("duck"):
            parts.append(f"[{cur_a}]asplit=2[am][as]")
            parts.append("[mu][as]sidechaincompress=threshold=0.04:ratio=8:attack=20:release=400[md]")
            parts.append("[am][md]amix=inputs=2:normalize=0:duration=first[ao]")
        else:
            parts.append(f"[{cur_a}][mu]amix=inputs=2:normalize=0:duration=first[ao]")
        cur_a = "ao"

    parts.append(f"[{cur_v}]null[v]")
    parts.append(f"[{cur_a}]alimiter=limit=0.97[a]")
    plan.graph = ";".join(parts)
    return plan
