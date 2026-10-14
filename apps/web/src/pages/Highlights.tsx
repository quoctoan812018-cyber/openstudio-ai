import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AudioApi, type VoiceInfo } from "../api/audio";
import { ApiRequestError } from "../api/client";
import { useApi } from "../api/connection";
import { HighlightsApi, type Clip, type HighlightsState } from "../api/studio";
import { LANGS, type SubtitleState } from "../api/subtitles";
import { TimeInput } from "../components/CueEditor";
import { ProjectPicker } from "../components/ProjectPicker";
import { useI18n } from "../i18n";
import { JobList, useProjectJobs } from "../lib/useJobs";

const btn = "rounded bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-500 disabled:opacity-50";
const btn2 = "rounded border px-3 py-1.5 text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50";
const field = "rounded border px-2 py-1 text-sm dark:bg-zinc-800";
const DEFAULTS: HighlightsState["options"] = { count: 3, minLen: 20, maxLen: 60, layout: "vertical", fit: "crop", subtitleLang: null, hookOverlay: true, useLlm: true, narrationLang: null, voice: null };

export function ClipCard({ clip, resultUrl, onEdit, onPreview }: {
  clip: Clip; resultUrl?: string; onEdit: (patch: Partial<Pick<Clip, "title" | "hook" | "selected" | "start" | "end">>) => void; onPreview: () => void;
}) {
  const { t } = useI18n();
  const [title, setTitle] = useState(clip.title);
  const [hook, setHook] = useState(clip.hook);
  useEffect(() => { setTitle(clip.title); setHook(clip.hook); }, [clip.title, clip.hook]);
  return (
    <li className={`rounded-xl border p-3 text-sm ${clip.selected ? "border-indigo-300 dark:border-indigo-800" : "border-zinc-200 opacity-70 dark:border-zinc-800"}`} data-testid={`clip-${clip.id}`}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={clip.selected} aria-label={`${t("hl.select")} ${clip.id}`} onChange={(e) => onEdit({ selected: e.target.checked })} />
          <strong>{clip.id}</strong>
        </label>
        <TimeInput label={`${t("sub.start")} ${clip.id}`} value={clip.start} onCommit={(v) => onEdit({ start: v })} />
        <span>→</span>
        <TimeInput label={`${t("sub.end")} ${clip.id}`} value={clip.end} onCommit={(v) => onEdit({ end: v })} />
        <span className="text-xs text-zinc-500">{(clip.end - clip.start).toFixed(0)}s</span>
        {clip.score != null && (
          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800" title={clip.reason}>
            {t("hl.score")} {clip.score.toFixed(1)}{clip.llm != null ? ` (LLM ${clip.llm})` : ` (${t("hl.heuristic")})`}
          </span>
        )}
        {clip.manual && <span className="rounded-full bg-zinc-200 px-2 py-0.5 text-xs">{t("hl.manual")}</span>}
        <button className={`${btn2} ml-auto`} onClick={onPreview}>{t("hl.preview")}</button>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <input aria-label={`${t("hl.clipTitle")} ${clip.id}`} className={field} value={title} onChange={(e) => setTitle(e.target.value)}
          onBlur={() => title !== clip.title && onEdit({ title })} />
        <input aria-label={`${t("hl.hook")} ${clip.id}`} className={field} value={hook} onChange={(e) => setHook(e.target.value)}
          onBlur={() => hook !== clip.hook && onEdit({ hook })} />
      </div>
      {clip.text && <p className="mt-2 text-xs text-zinc-500">{clip.text}</p>}
      {clip.reason && <p className="mt-1 text-xs italic text-zinc-500">{clip.reason}</p>}
      {resultUrl && <p className="mt-2"><a className="text-indigo-600 underline" href={resultUrl} download>{t("hl.download")}</a></p>}
    </li>
  );
}

function Workspace({ pid }: { pid: string }) {
  const api = useApi();
  const { t } = useI18n();
  const hl = useMemo(() => new HighlightsApi(api, pid), [api, pid]);
  const audio = useMemo(() => new AudioApi(api), [api]);
  const [st, setSt] = useState<HighlightsState | null>(null);
  const [sub, setSub] = useState<Partial<SubtitleState>>({});
  const [voices, setVoices] = useState<VoiceInfo[]>([]);
  const [msg, setMsg] = useState<{ text: string; modelId?: string } | null>(null);
  const [mediaUrl, setMediaUrl] = useState<string | null>(null);
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [summaryUrl, setSummaryUrl] = useState<string | null>(null);
  const player = useRef<HTMLVideoElement | null>(null);
  const stopAt = useRef<number | null>(null);

  const load = useCallback(async () => {
    const [h, s] = await Promise.all([hl.state(), hl.subtitles()]);
    setSt({ options: DEFAULTS, analysis: null, clips: [], results: {}, summary: null, ...(h.state as Partial<HighlightsState>) } as HighlightsState);
    setSub(s.state as Partial<SubtitleState>);
  }, [hl]);
  const { jobs, running, refresh } = useProjectJobs(pid, () => void load());
  useEffect(() => { void load().catch(() => setMsg({ text: t("common.error") })); }, [load, t]);

  const o = st?.options ?? DEFAULTS;
  const narrLang = o.narrationLang ?? sub.sourceLang ?? "vi";
  useEffect(() => { audio.voices(narrLang).then(setVoices).catch(() => undefined); }, [audio, narrLang]);
  useEffect(() => {
    setMediaUrl(null);
    if (sub.source?.path) hl.fileUrl(sub.source.path).then(setMediaUrl).catch(() => undefined);
  }, [sub.source?.path, hl]);
  useEffect(() => {
    const entries = Object.entries(st?.results ?? {});
    void Promise.all(entries.map(async ([id, p]) => [id, await hl.fileUrl(p)] as const)).then((e) => setUrls(Object.fromEntries(e))).catch(() => undefined);
  }, [st?.results, hl]);
  useEffect(() => {
    setSummaryUrl(null);
    if (st?.summary?.path) hl.fileUrl(st.summary.path).then(setSummaryUrl).catch(() => undefined);
  }, [st?.summary?.path, hl]);

  const run = async (fn: () => Promise<unknown>) => {
    setMsg(null);
    try { await fn(); await load(); await refresh(); } catch (e) {
      if (e instanceof ApiRequestError) setMsg({ text: e.message, modelId: e.code === "MODEL_MISSING" ? String(e.details?.modelId) : undefined });
      else setMsg({ text: t("common.error") });
    }
  };
  const setOpt = (options: Partial<HighlightsState["options"]>) => run(() => hl.command("set-options", { options }));
  const preview = (c: Clip) => {
    const p = player.current;
    if (!p) return;
    stopAt.current = c.end;
    p.currentTime = c.start;
    void p.play?.();
  };
  const clips = st?.clips ?? [];
  const chosen = clips.filter((c) => c.selected).length;
  const hasTranscript = !!sub.sourceLang && !!sub.tracks?.[sub.sourceLang];

  return (
    <div className="space-y-4">
      {msg && (
        <p role="alert" className="rounded bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950">
          {msg.text}{" "}
          {msg.modelId && <button className="underline" onClick={() => void run(() => api.downloadModel(msg.modelId!))}>{t("sub.downloadModel")} ({msg.modelId})</button>}
        </p>
      )}
      <JobList jobs={jobs} />

      <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="mb-2 text-lg font-medium">{t("hl.setup")}</h2>
        {!sub.source ? <p className="text-sm text-amber-700">{t("dub.needSource")}</p>
          : !hasTranscript ? <p className="text-sm text-amber-700">{t("hl.needTranscript")}</p>
          : <p className="mb-2 text-sm"><strong>{sub.source.filename}</strong> · {Math.round(sub.source.duration)}s · {LANGS[sub.sourceLang!] ?? sub.sourceLang}</p>}
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label>{t("hl.count")}{" "}
            <input type="number" min={1} max={10} className={`${field} w-16`} value={o.count} aria-label={t("hl.count")}
              onChange={(e) => void setOpt({ count: Number(e.target.value) })} />
          </label>
          <label>{t("hl.minLen")}{" "}
            <input type="number" min={5} max={170} className={`${field} w-16`} value={o.minLen} aria-label={t("hl.minLen")}
              onChange={(e) => void setOpt({ minLen: Number(e.target.value) })} />
          </label>
          <label>{t("hl.maxLen")}{" "}
            <input type="number" min={6} max={180} className={`${field} w-16`} value={o.maxLen} aria-label={t("hl.maxLen")}
              onChange={(e) => void setOpt({ maxLen: Number(e.target.value) })} />
          </label>
          <label>{t("sub.layout")}{" "}
            <select className={field} value={o.layout} onChange={(e) => void setOpt({ layout: e.target.value as "vertical" | "horizontal" })}>
              <option value="vertical">9:16</option><option value="horizontal">16:9</option>
            </select>
          </label>
          {o.layout === "vertical" && (
            <label>{t("sub.fit")}{" "}
              <select className={field} value={o.fit} onChange={(e) => void setOpt({ fit: e.target.value as "crop" | "pad" })}>
                <option value="crop">{t("sub.fit.crop")}</option><option value="pad">{t("sub.fit.pad")}</option>
              </select>
            </label>
          )}
          <label>{t("hl.subLang")}{" "}
            <select className={field} value={o.subtitleLang ?? ""} onChange={(e) => void setOpt({ subtitleLang: e.target.value || null })}>
              <option value="">{t("hl.sourceLang")}</option>
              {Object.keys(sub.tracks ?? {}).filter((l) => l !== sub.sourceLang).map((l) => <option key={l} value={l}>{LANGS[l] ?? l}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-1"><input type="checkbox" checked={o.hookOverlay} onChange={(e) => void setOpt({ hookOverlay: e.target.checked })} />{t("hl.hookOverlay")}</label>
          <label className="flex items-center gap-1"><input type="checkbox" checked={o.useLlm} onChange={(e) => void setOpt({ useLlm: e.target.checked })} />{t("hl.useLlm")}</label>
        </div>
        <div className="mt-3"><button className={btn} disabled={!hasTranscript || running} onClick={() => void run(() => hl.analyze())}>{t("hl.analyze")}</button></div>
        {st?.analysis && (
          <p className="mt-2 text-xs text-zinc-500">{t("hl.analysis", { w: st.analysis.windows, s: st.analysis.scored, sc: st.analysis.scenes })}{st.analysis.llm ? "" : ` · ${t("hl.noLlm")}`}</p>
        )}
      </section>

      <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="mb-2 text-lg font-medium">{t("hl.clips")}</h2>
        {mediaUrl && (
          <video ref={player} src={mediaUrl} controls className="mb-3 max-h-72 w-full rounded bg-black" aria-label="source preview"
            onTimeUpdate={(e) => { const v = e.currentTarget; if (stopAt.current != null && v.currentTime >= stopAt.current) { v.pause(); stopAt.current = null; } }} />
        )}
        {clips.length === 0 ? <p className="text-sm text-zinc-500">{t("hl.noClips")}</p> : (
          <ul className="space-y-2">
            {clips.map((c) => (
              <ClipCard key={c.id} clip={c} resultUrl={urls[c.id]} onPreview={() => preview(c)}
                onEdit={(patch) => void run(() => hl.command("set-clip", { id: c.id, ...patch }))} />
            ))}
          </ul>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          <button className={btn2} disabled={!hasTranscript} onClick={() => void run(() => {
            const s = Math.floor(player.current?.currentTime ?? 0);
            return hl.command("add-clip", { start: s, end: s + 30, title: "" });
          })}>{t("hl.addClip")}</button>
          <button className={btn} disabled={!chosen || running} onClick={() => void run(() => hl.exportClips())}>{t("hl.export", { n: chosen })}</button>
        </div>
      </section>

      <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="mb-2 text-lg font-medium">{t("hl.summary")}</h2>
        <p className="mb-2 text-sm text-zinc-600 dark:text-zinc-400">{t("hl.summaryHelp")}</p>
        <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
          <label>{t("hl.narrLang")}{" "}
            <select className={field} value={o.narrationLang ?? ""} onChange={(e) => void setOpt({ narrationLang: e.target.value || null })}>
              <option value="">{t("hl.sourceLang")}</option>
              {["vi", "en", "ja", "zh", "es", "fr"].map((l) => <option key={l} value={l}>{LANGS[l]}</option>)}
            </select>
          </label>
          <label>{t("tts.voice")}{" "}
            <select aria-label={t("tts.voice")} className={field} value={o.voice ?? ""} onChange={(e) => void setOpt({ voice: e.target.value || null })}>
              <option value="">{t("tts.autoVoice")}</option>
              {voices.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
          </label>
          <button className={btn} disabled={!chosen || running} onClick={() => void run(() => hl.summary())}>{t("hl.makeSummary")}</button>
        </div>
        {st?.summary && (
          <div className="space-y-2">
            {summaryUrl && <video controls src={summaryUrl} className="max-h-80 w-full rounded bg-black" aria-label="summary video" />}
            <ol className="space-y-1 text-sm">
              {st.summary.narrations.map((n) => <li key={n.clipId}><span className="text-xs text-zinc-500">{n.clipId} · {n.start.toFixed(0)}s</span> {n.text}</li>)}
            </ol>
          </div>
        )}
      </section>
    </div>
  );
}

export function Highlights() {
  const { t } = useI18n();
  const [pid, setPid] = useState("");
  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold">{t("hl.title")}</h1>
      <p className="mb-4 text-zinc-600 dark:text-zinc-400">{t("hl.subtitle")}</p>
      <ProjectPicker storageKey="hl.pid" value={pid} onChange={setPid} />
      {pid && <Workspace key={pid} pid={pid} />}
    </div>
  );
}
