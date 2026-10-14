import { useEffect, useRef, useState } from "react";
import { useI18n } from "../i18n";
import { activeIndex, fmtTime, mergeWithNext, parseTime, removeCue, splitCue, validateCues, type Cue } from "../lib/cues";

export function TimeInput({ value, onCommit, label }: { value: number; onCommit: (v: number) => void; label: string }) {
  const [text, setText] = useState(fmtTime(value));
  const [bad, setBad] = useState(false);
  useEffect(() => setText(fmtTime(value)), [value]);
  return (
    <input aria-label={label} value={text} aria-invalid={bad}
      className={`w-24 rounded border px-1 py-0.5 font-mono text-xs dark:bg-zinc-800 ${bad ? "border-red-500" : ""}`}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        const v = parseTime(text);
        if (v === null) { setBad(true); return; }
        setBad(false);
        onCommit(v);
      }} />
  );
}

export function CueEditor({ cues, reference, currentTime, onSeek, onChange }: {
  cues: Cue[];
  /** Bản gốc để đối chiếu khi sửa bản dịch (cùng chỉ số cue). */
  reference?: Cue[];
  currentTime: number;
  onSeek: (t: number) => void;
  onChange: (cues: Cue[]) => void;
}) {
  const { t } = useI18n();
  const active = activeIndex(cues, currentTime);
  const bad = new Set(validateCues(cues));
  const activeRef = useRef<HTMLLIElement | null>(null);
  const areas = useRef<Record<number, HTMLTextAreaElement | null>>({});

  useEffect(() => {
    activeRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [active]);

  const patch = (i: number, p: Partial<Cue>) => onChange(cues.map((c, k) => (k === i ? { ...c, ...p } : c)));

  return (
    <ol className="max-h-[28rem] space-y-1 overflow-y-auto pr-1" data-testid="cue-list">
      {cues.map((c, i) => (
        <li key={i} ref={i === active ? activeRef : null} aria-current={i === active}
          className={`rounded border p-2 text-sm ${i === active ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950" : "border-zinc-200 dark:border-zinc-800"} ${bad.has(i) ? "border-red-500" : ""}`}>
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <button className="w-8 text-left text-xs text-zinc-500" onClick={() => onSeek(c.start)} title={t("sub.seek")}>#{i + 1}</button>
            <TimeInput label={`${t("sub.start")} ${i + 1}`} value={c.start} onCommit={(v) => patch(i, { start: v })} />
            <span>→</span>
            <TimeInput label={`${t("sub.end")} ${i + 1}`} value={c.end} onCommit={(v) => patch(i, { end: v })} />
            <span className="ml-auto flex gap-1">
              <button className="rounded border px-1.5 text-xs" title={t("sub.split")}
                onClick={() => {
                  const ta = areas.current[i];
                  onChange(splitCue(cues, i, ta?.selectionStart ?? Math.floor(c.text.length / 2)));
                }}>✂</button>
              <button className="rounded border px-1.5 text-xs" title={t("sub.merge")} disabled={i === cues.length - 1}
                onClick={() => onChange(mergeWithNext(cues, i))}>⇣</button>
              <button className="rounded border px-1.5 text-xs text-red-700" title={t("sub.delete")}
                onClick={() => onChange(removeCue(cues, i))}>✕</button>
            </span>
          </div>
          {reference?.[i] && <p className="mb-1 text-xs text-zinc-500">{reference[i].text}</p>}
          <textarea ref={(el) => { areas.current[i] = el; }} aria-label={`${t("sub.text")} ${i + 1}`} rows={2} value={c.text}
            className="w-full rounded border px-2 py-1 dark:bg-zinc-800" onChange={(e) => patch(i, { text: e.target.value })} />
        </li>
      ))}
    </ol>
  );
}
