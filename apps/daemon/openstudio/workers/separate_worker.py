"""Tiến trình con tách giọng/nhạc nền bằng Demucs (htdemucs). Ghi `no_vocals.wav` (nhạc nền + tiếng động) và `vocals.wav`.

Đối số: JSON {"engine": "demucs"|"fake", "model_dir", "audio", "out_dir"}; audio nên là WAV 44.1 kHz stereo.
stdout: {"type":"progress","percent"} … {"type":"done","no_vocals","vocals"}
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import soundfile as sf

SIG = "955717e8"  # chữ ký của htdemucs; tên file trọng số là 955717e8-8726e21a.th (8726e21a = tiền tố SHA-256, demucs tự kiểm tra)


def emit(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


def main() -> None:
    args = json.loads(sys.argv[1])
    out_dir = args["out_dir"]
    os.makedirs(out_dir, exist_ok=True)
    nv, vo = os.path.join(out_dir, "no_vocals.wav"), os.path.join(out_dir, "vocals.wav")
    audio, sr = sf.read(args["audio"], dtype="float32", always_2d=True)

    if args.get("engine") == "fake":  # kiểm thử: coi toàn bộ là nhạc nền nhỏ
        sf.write(nv, audio * 0.4, sr, subtype="PCM_16")
        sf.write(vo, audio * 0.0, sr, subtype="PCM_16")
        emit({"type": "progress", "percent": 100})
        emit({"type": "done", "no_vocals": nv, "vocals": vo})
        return

    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model
    from pathlib import Path

    torch.set_num_threads(max(1, (os.cpu_count() or 4) - 1))
    model = get_model(SIG, repo=Path(args["model_dir"]))
    model.eval()
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    if sr != model.samplerate:
        import soxr
        audio = soxr.resample(audio, sr, model.samplerate)
        sr = model.samplerate
    wav = torch.from_numpy(audio.T.copy())  # (2, T)
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / (ref.std() + 1e-8)

    total = max(1, wav.shape[-1])

    def cb(d: dict) -> None:
        if d.get("state") == "end" and "segment_offset" in d:
            emit({"type": "progress", "percent": min(99.0, 100.0 * d["segment_offset"] / total)})

    with torch.no_grad():
        sources = apply_model(model, wav[None], device="cpu", split=True, overlap=0.25, progress=False, callback=cb)[0]
    sources = sources * (ref.std() + 1e-8) + ref.mean()
    names = list(model.sources)
    vocals = sources[names.index("vocals")]
    others = sum(sources[i] for i, n in enumerate(names) if n != "vocals")
    sf.write(vo, vocals.numpy().T, sr, subtype="PCM_16")
    sf.write(nv, others.numpy().T, sr, subtype="PCM_16")
    emit({"type": "done", "no_vocals": nv, "vocals": vo})


if __name__ == "__main__":
    main()
