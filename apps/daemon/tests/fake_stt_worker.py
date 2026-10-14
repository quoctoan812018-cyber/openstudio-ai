"""STT giả cho test: cùng giao thức với openstudio.workers.stt_worker, không cần mô hình."""
import json
import sys

args = json.loads(sys.argv[1])
SENTENCES = [
    "Xin chào các bạn.", "Hôm nay chúng ta tìm hiểu về cà phê Việt Nam, một chủ đề rất thú vị.",
    "Cà phê Robusta có vị đậm.", "Cảm ơn các bạn đã theo dõi.",
]
words, t = [], 0.5
for si, sent in enumerate(SENTENCES):
    for w in sent.split(" "):
        words.append({"start": round(t, 3), "end": round(t + 0.3, 3), "word": " " + w, "prob": 0.99})
        t += 0.32
    t += 0.9  # khoảng lặng giữa các câu
for pct in (10, 60, 99):
    print(json.dumps({"type": "progress", "percent": pct}), flush=True)
with open(args["out"], "w", encoding="utf-8") as f:
    json.dump({"language": args.get("language") or "vi", "language_probability": 0.99, "duration": t, "words": words}, f,
              ensure_ascii=False)
print(json.dumps({"type": "done", "result": args["out"]}), flush=True)
