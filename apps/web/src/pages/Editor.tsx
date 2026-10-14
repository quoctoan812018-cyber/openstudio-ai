import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiRequestError } from "../api/client";
import { useApi } from "../api/connection";
import { EditorApi, TemplatesApi, AssetsApi, type EditorState, type Segment, type TemplateInfo } from "../api/studio";
import { AssetPanel } from "../components/AssetPanel";
import { ProjectPicker } from "../components/ProjectPicker";
import { useI18n } from "../i18n";
import { JobList, useProjectJobs } from "../lib/useJobs";

const btn = "rounded bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-500 disabled:opacity-50";
const btn2 = "rounded border px-2 py-1 text-xs hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50";
const field = "rounded border px-2 py-1 text-sm dark:bg-zinc-800";
const card = "rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900";
const TRANSITIONS = ["none", "fade", "dissolve", "wipeleft", "wiperight", "slideleft", "slideright"];
const EMPTY: EditorState = {
  settings: { aspect: "16:9", quality: 720, fps: 25, fit: "pad" }, segments: [], texts: [], overlays: [],
  music: { asset: null, volumeDb: -18, duck: true, fadeOut: 2 }, result: null, preview: null,
};

export const segLength = (s: Segment) => (s.kind === "video" ? (s.out - s.in) / s.speed : s.duration);
export const totalLength = (segs: Segment[]) =>
  Math.max(0, segs.reduce((sum, s, i) => sum + segLength(s) - (i > 0 && s.transition.type !== "none" ? s.transition.duration : 0), 0));

/** Số có thể gõ dở: chỉ gửi khi blur và giá trị đổi. */
function NumField({ label, value, step = 0.1, min, max, onCommit }: { label: string; value: number; step?: number; min?: number; max?: number; onCommit: (v: number) => void }) {
  const [v, setV] = useState(String(value));
  useEffect(() => setV(String(value)), [value]);
  return (
    <input aria-label={label} title={label} type="number" step={step} min={min} max={max} className={`${field} w-20`} value={v} onChange={(e) => setV(e.target.value)}
      onBlur={() => { const n = Number(v); if (v.trim() !== "" && Number.isFinite(n) && n !== value) onCommit(n); else setV(String(value)); }} />
  );
}

export function SegmentRow({ seg, index, count, onUpdate, onMove, onSplit, onRemove }: {
  seg: Segment; index: number; count: number; onUpdate: (patch: Record<string, unknown>) => void; onMove: (to: number) => void; onSplit: (at: number) => void; onRemove: () => void;
}) {
  const { t } = useI18n();
  const n = `${t("ed.segment")} ${index + 1}`;
  return (
    <li className="rounded-lg border border-zinc-200 p-2 text-sm dark:border-zinc-800">
      <div className="flex flex-wrap items-center gap-2">
        <b>{index + 1}.</b><span className="min-w-0 flex-1 truncate">{seg.name}</span>
        <span className="text-xs text-zinc-500">{segLength(seg).toFixed(1)}s</span>
        <button className={btn2} disabled={index === 0} onClick={() => onMove(index - 1)} aria-label={`${n} ↑`}>↑</button>
        <button className={btn2} disabled={index === count - 1} onClick={() => onMove(index + 1)} aria-label={`${n} ↓`}>↓</button>
        <button className="text-red-700" onClick={onRemove} aria-label={`${n} ${t("sub.delete")}`}>✕</button>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        {seg.kind === "video" ? (
          <>
            <label className="text-xs">{t("ed.in")} <NumField label={`${n} in`} value={seg.in} min={0} onCommit={(v) => onUpdate({ in: v })} /></label>
            <label className="text-xs">{t("ed.out")} <NumField label={`${n} out`} value={seg.out} min={0} onCommit={(v) => onUpdate({ out: v })} /></label>
            <label className="text-xs">{t("ed.speed")} <NumField label={`${n} speed`} value={seg.speed} step={0.25} min={0.25} max={4} onCommit={(v) => onUpdate({ speed: v })} /></label>
            {seg.hasAudio && <label className="text-xs">{t("ed.volume")} <NumField label={`${n} volume`} value={seg.volume} step={10} min={0} max={200} onCommit={(v) => onUpdate({ volume: v })} /></label>}
            <button className={btn2} onClick={() => onSplit(seg.in + (seg.out - seg.in) / 2)}>{t("ed.split")}</button>
          </>
        ) : (
          <label className="text-xs">{t("ed.duration")} <NumField label={`${n} duration`} value={seg.duration} min={0.5} onCommit={(v) => onUpdate({ duration: v })} /></label>
        )}
        {index > 0 && (
          <label className="text-xs">{t("ed.transition")}{" "}
            <select aria-label={`${n} ${t("ed.transition")}`} className={field} value={seg.transition.type}
              onChange={(e) => onUpdate({ transition: e.target.value === "none" ? null : { type: e.target.value, duration: seg.transition.duration || 0.5 } })}>
              {TRANSITIONS.map((x) => <option key={x} value={x}>{x}</option>)}
            </select>
          </label>
        )}
      </div>
    </li>
  );
}

function Workspace({ pid }: { pid: string }) {
  const api = useApi();
  const { t } = useI18n();
  const ed = useMemo(() => new EditorApi(api, pid), [api, pid]);
  const assets = useMemo(() => new AssetsApi(api, pid), [api, pid]);
  const tpl = useMemo(() => new TemplatesApi(api), [api]);
  const [st, setSt] = useState<EditorState>(EMPTY);
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [urls, setUrls] = useState<{ result?: string; preview?: string }>({});
  const [text, setText] = useState({ text: "", start: 0, end: 3, position: "bottom" });

  const load = useCallback(async () => setSt({ ...EMPTY, ...((await ed.state()).state as Partial<EditorState>) } as EditorState), [ed]);
  const { jobs, running, refresh } = useProjectJobs(pid, () => void load());
  useEffect(() => { void load().catch(() => setMsg(t("common.error"))); }, [load, t]);
  useEffect(() => { tpl.list("editor").then(setTemplates).catch(() => undefined); }, [tpl]);
  useEffect(() => {
    let off = false;
    void (async () => {
      const u = { result: st.result ? await assets.fileUrl(st.result.path) : undefined, preview: st.preview ? await assets.fileUrl(st.preview.path) : undefined };
      if (!off) setUrls(u);
    })().catch(() => undefined);
    return () => { off = true; };
  }, [st.result, st.preview, assets]);

  const run = async (fn: () => Promise<unknown>) => {
    setMsg(null);
    try { await fn(); await load(); await refresh(); } catch (e) { setMsg(e instanceof ApiRequestError ? e.message : t("common.error")); }
  };
  const cmd = (type: string, payload: object) => run(() => ed.command(type, payload));
  const total = totalLength(st.segments);

  return (
    <div className="space-y-4">
      {msg && <p role="alert" className="rounded bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950">{msg}</p>}
      <JobList jobs={jobs} />
      <section className={card}>
        <h2 className="mb-2 text-lg font-medium">{t("asset.title")}</h2>
        <AssetPanel pid={pid} actions={[
          { label: t("ed.addClip"), kinds: ["video", "image"], run: (a) => run(() => ed.attach("segment", a.id, a.kind === "image" ? { duration: 4 } : {})) },
          { label: t("ed.addOverlay"), kinds: ["video", "image"], run: (a) => run(() => ed.attach("overlay", a.id, { start: 0, end: Math.max(1, total || 3), x: 0.95, y: 0.05, width: 0.18 })) },
          { label: t("ed.setMusic"), kinds: ["audio", "video"], run: (a) => run(() => ed.attach("music", a.id)) },
        ]} />
      </section>

      <section className={card}>
        <div className="mb-2 flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-medium">{t("ed.timeline")}</h2>
          <span className="text-sm text-zinc-500">{total.toFixed(1)}s</span>
          <label className="text-sm">{t("tpl.apply")}{" "}
            <select aria-label={t("tpl.apply")} className={field} value="" onChange={(e) => { const x = templates.find((y) => y.id === e.target.value); if (x) void cmd("apply-template", { template: x }); }}>
              <option value="">—</option>
              {templates.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          </label>
        </div>
        <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
          <label>{t("ed.aspect")}{" "}
            <select aria-label={t("ed.aspect")} className={field} value={st.settings.aspect} onChange={(e) => void cmd("set-settings", { settings: { aspect: e.target.value } })}>
              {["16:9", "9:16", "1:1"].map((x) => <option key={x}>{x}</option>)}
            </select>
          </label>
          <label>{t("ed.quality")}{" "}
            <select aria-label={t("ed.quality")} className={field} value={st.settings.quality} onChange={(e) => void cmd("set-settings", { settings: { quality: Number(e.target.value) } })}>
              {[480, 720, 1080].map((x) => <option key={x} value={x}>{x}p</option>)}
            </select>
          </label>
          <label>{t("ed.fit")}{" "}
            <select aria-label={t("ed.fit")} className={field} value={st.settings.fit} onChange={(e) => void cmd("set-settings", { settings: { fit: e.target.value } })}>
              <option value="pad">{t("ed.fit.pad")}</option><option value="crop">{t("ed.fit.crop")}</option>
            </select>
          </label>
        </div>
        {st.segments.length === 0 ? <p className="text-sm text-zinc-500">{t("ed.empty")}</p> : (
          <ol className="space-y-2">
            {st.segments.map((s, i) => (
              <SegmentRow key={s.id} seg={s} index={i} count={st.segments.length}
                onUpdate={(patch) => void cmd("update-segment", { id: s.id, ...patch })} onMove={(to) => void cmd("move-segment", { id: s.id, index: to })}
                onSplit={(at) => void cmd("split-segment", { id: s.id, at })} onRemove={() => void cmd("remove-segment", { id: s.id })} />
            ))}
          </ol>
        )}
      </section>

      <section className={card}>
        <h2 className="mb-2 text-lg font-medium">{t("ed.texts")}</h2>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <input aria-label={t("ed.textContent")} placeholder={t("ed.textContent")} className={`${field} w-64`} value={text.text} onChange={(e) => setText({ ...text, text: e.target.value })} />
          <label>{t("ed.from")} <input aria-label={t("ed.from")} type="number" min={0} step={0.5} className={`${field} w-20`} value={text.start} onChange={(e) => setText({ ...text, start: Number(e.target.value) })} /></label>
          <label>{t("ed.to")} <input aria-label={t("ed.to")} type="number" min={0} step={0.5} className={`${field} w-20`} value={text.end} onChange={(e) => setText({ ...text, end: Number(e.target.value) })} /></label>
          <select aria-label={t("ed.position")} className={field} value={text.position} onChange={(e) => setText({ ...text, position: e.target.value })}>
            {["top", "center", "bottom"].map((x) => <option key={x}>{x}</option>)}
          </select>
          <button className={btn} disabled={!text.text.trim() || text.end <= text.start} onClick={() => void cmd("add-text", text).then(() => setText({ ...text, text: "" }))}>{t("ed.addText")}</button>
        </div>
        <ul className="mt-2 space-y-1 text-sm">
          {st.texts.map((x) => (
            <li key={x.id} className="flex items-center gap-2">
              <code>{x.start}–{x.end}s</code><span className="flex-1 truncate">{x.text}</span>
              <button className="text-red-700" onClick={() => void cmd("remove-text", { id: x.id })} aria-label={`${t("sub.delete")} ${x.text}`}>✕</button>
            </li>
          ))}
        </ul>
        {st.overlays.length > 0 && (
          <ul className="mt-2 space-y-1 text-sm">
            {st.overlays.map((o) => (
              <li key={o.id} className="flex items-center gap-2"><span>🖼</span><span className="flex-1 truncate">{o.name} · {o.start}–{o.end}s</span>
                <button className="text-red-700" onClick={() => void cmd("remove-overlay", { id: o.id })} aria-label={`${t("sub.delete")} ${o.name}`}>✕</button></li>
            ))}
          </ul>
        )}
      </section>

      <section className={card}>
        <h2 className="mb-2 text-lg font-medium">{t("ed.music")}</h2>
        {st.music.asset ? (
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span>🎵 {st.music.name}</span>
            <label>{t("ed.musicVol")} <NumField label={t("ed.musicVol")} value={st.music.volumeDb} step={1} min={-60} max={6} onCommit={(v) => void cmd("set-music", { volumeDb: v })} /> dB</label>
            <label className="flex items-center gap-1"><input type="checkbox" checked={st.music.duck} onChange={(e) => void cmd("set-music", { duck: e.target.checked })} />{t("ed.duck")}</label>
            <button className={btn2} onClick={() => void cmd("set-music", { remove: true })}>{t("sub.delete")}</button>
          </div>
        ) : <p className="text-sm text-zinc-500">{t("ed.noMusic")}</p>}
      </section>

      <section className={card}>
        <div className="flex flex-wrap gap-2">
          <button className={btn2} disabled={running || !st.segments.length} onClick={() => void run(() => ed.render(true))}>{t("ed.preview")}</button>
          <button className={btn} disabled={running || !st.segments.length} onClick={() => void run(() => ed.render(false))}>{t("ed.export")}</button>
        </div>
        {urls.preview && st.preview && <video controls src={urls.preview} aria-label="preview" className="mt-3 max-h-72 rounded bg-black" />}
        {urls.result && st.result && (
          <div className="mt-3">
            <video controls src={urls.result} aria-label="result" className="max-h-96 rounded bg-black" />
            <a className="text-sm text-indigo-600 underline" href={urls.result} download>{st.result.path.split("/").pop()} ({(st.result.bytes / 1e6).toFixed(1)} MB)</a>
          </div>
        )}
      </section>
    </div>
  );
}

export function Editor() {
  const { t } = useI18n();
  const [pid, setPid] = useState("");
  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold">{t("ed.title")}</h1>
      <p className="mb-4 text-zinc-600 dark:text-zinc-400">{t("ed.subtitle")}</p>
      <ProjectPicker storageKey="ed.pid" value={pid} onChange={setPid} />
      {pid && <Workspace key={pid} pid={pid} />}
    </div>
  );
}
