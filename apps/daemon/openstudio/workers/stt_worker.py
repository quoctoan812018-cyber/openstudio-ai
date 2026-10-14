"""Tiến trình con STT (faster-whisper). Chạy tách biệt để cô lập phụ thuộc, giải phóng RAM/VRAM khi xong và huỷ được.

Giao thức: đối số dòng lệnh là MỘT chuỗi JSON; stdout là các dòng JSON:
  {"type":"progress","percent":N}  ...  {"type":"done","result":"<đường dẫn file JSON kết quả>"}
"""
from __future__ import annotations

import json
import os
import sys


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def main() -> None:
    args = json.loads(sys.argv[1])
    os.environ.setdefault("HF_HUB_OFFLINE", "1")  # mô hình đã nằm ở máy; không gọi mạng
    from faster_whisper import WhisperModel

    model = WhisperModel(args["model_dir"], device=args.get("device", "cpu"),
                         compute_type=args.get("compute_type", "int8"), cpu_threads=int(args.get("cpu_threads", 0)))
    emit({"type": "progress", "percent": 1, "message": "model loaded"})
    segments, info = model.transcribe(
        args["audio"], language=args.get("language") or None, word_timestamps=True, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500}, condition_on_previous_text=False,
        beam_size=int(args.get("beam_size", 5)), initial_prompt=args.get("initial_prompt") or None)
    duration = max(info.duration, 0.001)
    words: list[dict] = []
    for seg in segments:
        for w in seg.words or []:
            words.append({"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word,
                          "prob": round(w.probability, 3)})
        emit({"type": "progress", "percent": min(99, seg.end / duration * 100)})
    with open(args["out"], "w", encoding="utf-8") as f:
        json.dump({"language": info.language, "language_probability": info.language_probability,
                   "duration": info.duration, "words": words}, f, ensure_ascii=False)
    emit({"type": "done", "result": args["out"]})


if __name__ == "__main__":
    main()
