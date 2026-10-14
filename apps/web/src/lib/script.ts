/** Phân tích nhanh kịch bản ở trình duyệt để hiện danh sách người nói (khớp quy tắc của daemon: openstudio/tts/script.py). */
const EMOTION = new Set(["cười", "thở dài", "hắng giọng", "ho", "khóc", "thì thầm"]);
const PAUSE = /^(nghỉ|pause|im lặng|silence)\b/i;

export function parseSpeakers(text: string): string[] {
  const seen: string[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    const m = /^\[([^\]\n]{1,40})\]\s*(.*)$/.exec(line);
    let speaker = "default";
    let body = line;
    if (m) {
      const tag = m[1].trim();
      if (!EMOTION.has(tag.toLowerCase()) && !PAUSE.test(tag)) {
        speaker = tag;
        body = m[2];
      }
    }
    body = body.replace(/\[\s*(?:nghỉ|pause|im lặng|silence)\s+[0-9.,]+\s*(?:ms|s|giây)?\s*\]/gi, "").trim();
    if (body && !seen.includes(speaker)) seen.push(speaker);
  }
  return seen;
}
