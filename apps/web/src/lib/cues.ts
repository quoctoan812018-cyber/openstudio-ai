export interface Cue {
  start: number;
  end: number;
  text: string;
}

export function fmtTime(sec: number): string {
  const ms = Math.round(Math.max(0, sec) * 1000);
  const h = Math.floor(ms / 3600000);
  const m = Math.floor(ms / 60000) % 60;
  const s = Math.floor(ms / 1000) % 60;
  const f = ms % 1000;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  const fff = String(f).padStart(3, "0");
  return h ? `${h}:${mm}:${ss}.${fff}` : `${mm}:${ss}.${fff}`;
}

/** Nhận "1:02.5", "62.5", "01:02:03.456" → giây; null nếu sai định dạng. */
export function parseTime(s: string): number | null {
  const t = s.trim().replace(",", ".");
  if (!/^\d+(:\d{1,2}){0,2}(\.\d{1,3})?$/.test(t)) return null;
  const [main, frac = "0"] = t.split(".");
  const parts = main.split(":").map(Number);
  const secs = parts.reduce((a, p) => a * 60 + p, 0);
  return secs + Number(`0.${frac}`);
}

export function mergeWithNext(cues: Cue[], i: number): Cue[] {
  if (i < 0 || i >= cues.length - 1) return cues;
  const a = cues[i];
  const b = cues[i + 1];
  const merged = { start: a.start, end: Math.max(a.end, b.end), text: `${a.text.trim()} ${b.text.trim()}`.trim() };
  return [...cues.slice(0, i), merged, ...cues.slice(i + 2)];
}

/** Tách cue i tại vị trí ký tự `at`; thời gian chia theo tỉ lệ ký tự. */
export function splitCue(cues: Cue[], i: number, at: number): Cue[] {
  const c = cues[i];
  if (!c) return cues;
  const left = c.text.slice(0, at).trim();
  const right = c.text.slice(at).trim();
  if (!left || !right) return cues;
  const mid = Math.round((c.start + ((c.end - c.start) * left.length) / (left.length + right.length)) * 1000) / 1000;
  return [...cues.slice(0, i), { start: c.start, end: mid, text: left }, { start: mid, end: c.end, text: right }, ...cues.slice(i + 1)];
}

export function removeCue(cues: Cue[], i: number): Cue[] {
  return cues.filter((_, k) => k !== i);
}

export function shiftAll(cues: Cue[], delta: number): Cue[] {
  return cues.map((c) => ({ ...c, start: Math.max(0, round3(c.start + delta)), end: Math.max(0.1, round3(c.end + delta)) }));
}

const round3 = (n: number) => Math.round(n * 1000) / 1000;

export function activeIndex(cues: Cue[], t: number): number {
  return cues.findIndex((c) => t >= c.start && t < c.end);
}

export function validateCues(cues: Cue[]): number[] {
  const bad: number[] = [];
  cues.forEach((c, i) => {
    if (c.end <= c.start || (i > 0 && c.start < cues[i - 1].end - 1e-6)) bad.push(i);
  });
  return bad;
}
