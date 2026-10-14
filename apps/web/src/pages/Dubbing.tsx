import { useCallback, useEffect, useMemo, useState } from "react";
import { AudioApi, DubbingApi, type DubItem, type DubState, type VoiceInfo } from "../api/audio";
import { ApiRequestError } from "../api/client";
import { useApi } from "../api/connection";
import { LANGS, type SubtitleState } from "../api/subtitles";
import { ProjectPicker } from "../components/ProjectPicker";
import { useI18n } from "../i18n";
import { JobList, useProjectJobs } from "../lib/useJobs";

const btn = "rounded bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-500 disabled:opacity-50";
const field = "rounded border px-2 py-1 text-sm dark:bg-zinc-800";

const STATUS_STYLE: Record<DubItem["status"], string> = {
  ok: "bg-emerald-100 text-emerald-800", sped: "bg-sky-100 text-sky-800", too_long: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-800", pending: "bg-zinc-200 text-zinc-700", retry: "bg-zinc-200 text-zinc-700",
};

export function ItemRow({ it, voices, onEdit }: { it: DubItem; voices: VoiceInfo[]; onEdit: (id: string, patch: { text?: string; voice?: string }) => void }) {
  const { t } = useI18n();
  const [text, setText] = useState(it.text);
  useEffect(() => setText(it.text), [it.text]);
  const over = it.finalDuration != null && it.finalDuration > it.slot + 0.06;
  return (
    <li className="rounded border border-zinc-200 p-2 text-sm dark:border-zinc-800" data-testid={`item-${it.id}`}>
      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-zinc-500">
        <span>{it.start.toFixed(1)}s</span>
        <span>{t("dub.slot")} {it.slot.toFixed(1)}s</span>
        {it.duration != null && <span>{t("dub.spoken")} {it.duration.toFixed(1)}s{it.speed > 1 ? ` · ×${it.speed.toFixed(2)}` : ""}</span>}
        <span className={`rounded-full px-2 py-0.5 ${STATUS_STYLE[it.status]}`}>{t(`dub.status.${it.status}`)}</span>
        {it.shortened && <span className="rounded-full bg-violet-100 px-2 py-0.5 text-violet-800">{t("dub.shortened")}</span>}
        {over && <span className="text-amber-700">{t("dub.over")}</span>}
        <select aria-label={`${t("tts.voice")} ${it.id}`} className="ml-auto rounded border px-1 dark:bg-zinc-800" value={it.voice ?? ""} onChange={(e) => onEdit(it.id, { voice: e.target.value })}>
          <option value="">{t("dub.defaultVoice")}</option>
          {voices.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
        </select>
      </div>
      {it.srcText && <p className="mb-1 text-xs text-zinc-500">{it.srcText}</p>}
      <textarea aria-label={`${t("sub.text")} ${it.id}`} rows={2} className="w-full rounded border px-2 py-1 dark:bg-zinc-800" value={text}
        onChange={(e) => setText(e.target.value)} onBlur={() => text.trim() && text !== it.text && onEdit(it.id, { text })} />
      {it.note && <p className="mt-1 text-xs text-amber-700">{it.note}</p>}
    </li>
  );
}

function Workspace({ pid }: { pid: string }) {
  const api = useApi();
  const { t } = useI18n();
  const dub = useMemo(() => new DubbingApi(api, pid), [api, pid]);
  const audio = useMemo(() => new AudioApi(api), [api]);
  const [st, setSt] = useState<DubState | null>(null);
  const [sub, setSub] = useState<Partial<SubtitleState>>({});
  const [voices, setVoices] = useState<VoiceInfo[]>([]);
  const [msg, setMsg] = useState<{ text: string; modelId?: string } | null>(null);
  const [urls, setUrls] = useState<{ video?: string; audio?: string; srt?: string }>({});

  const load = useCallback(async () => {
    const [d, s] = await Promise.all([dub.state(), dub.subtitles()]);
    setSt({ options: { targetLang: null, voice: null, maxSpeed: 1.3, keepBackground: true, backgroundGain: -4, format: "wav", minGap: 0.08 }, plan: null, result: null, ...(d.state as Partial<DubState>) } as DubState);
    setSub(s.state as Partial<SubtitleState>);
  }, [dub]);
  const { jobs, running, refresh } = useProjectJobs(pid, () => void load());
  useEffect(() => { void load().catch(() => setMsg({ text: t("common.error") })); }, [load, t]);

  const o = st?.options;
  const tracks = Object.entries(sub.tracks ?? {}).filter(([l, tr]) => tr.kind === "translation" && l !== sub.sourceLang);
  useEffect(() => {
    if (o?.targetLang) audio.voices(o.targetLang).then(setVoices).catch(() => undefined);
  }, [audio, o?.targetLang]);
  useEffect(() => {
    const r = st?.result;
    setUrls({});
    if (!r) return;
    void (async () => setUrls({ video: r.video ? await dub.fileUrl(r.video) : undefined, audio: await dub.fileUrl(r.audio), srt: await dub.fileUrl(r.subtitles) }))().catch(() => undefined);
  }, [st?.result, dub]);

  const run = async (fn: () => Promise<unknown>) => {
    setMsg(null);
    try { await fn(); await load(); await refresh(); } catch (e) {
      if (e instanceof ApiRequestError) setMsg({ text: e.message, modelId: e.code === "MODEL_MISSING" ? String(e.details?.modelId) : undefined });
      else setMsg({ text: t("common.error") });
    }
  };
  const setOpt = (options: object) => run(() => dub.command("set-options", { options }));
  const items = st?.plan?.items ?? [];
  const synthesized = items.length > 0 && items.every((i) => i.audio || i.status === "failed") && items.some((i) => i.audio);
  const stats = st?.result?.stats;

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
        <h2 className="mb-2 text-lg font-medium">{t("dub.setup")}</h2>
        {!sub.source ? <p className="text-sm text-amber-700">{t("dub.needSource")}</p> : (
          <p className="mb-2 text-sm"><strong>{sub.source.filename}</strong> · {Math.round(sub.source.duration)}s · {t("dub.tracks")}: {Object.keys(sub.tracks ?? {}).map((l) => LANGS[l] ?? l).join(", ") || "—"}</p>
        )}
        {sub.source && tracks.length === 0 && <p className="text-sm text-amber-700">{t("dub.needTrack")}</p>}
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label>{t("dub.target")}{" "}
            <select className={field} value={o?.targetLang ?? ""} onChange={(e) => void setOpt({ targetLang: e.target.value || null })}>
              <option value="">—</option>
              {tracks.map(([l, tr]) => <option key={l} value={l}>{LANGS[l] ?? l}{tr.stale ? " ⚠" : ""}</option>)}
            </select>
          </label>
          <label>{t("tts.voice")}{" "}
            <select aria-label={t("tts.voice")} className={field} value={o?.voice ?? ""} onChange={(e) => void setOpt({ voice: e.target.value || null })}>
              <option value="">{t("tts.autoVoice")}</option>
              {voices.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
          </label>
          <label>{t("dub.maxSpeed")}{" "}
            <select className={field} value={o?.maxSpeed ?? 1.3} onChange={(e) => void setOpt({ maxSpeed: Number(e.target.value) })}>
              {[1.0, 1.1, 1.2, 1.3, 1.4, 1.5].map((v) => <option key={v} value={v}>×{v.toFixed(1)}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={o?.keepBackground ?? true} onChange={(e) => void setOpt({ keepBackground: e.target.checked })} />{t("dub.keepBg")}
          </label>
          <label>{t("sub.format")}{" "}
            <select className={field} value={o?.format ?? "wav"} onChange={(e) => void setOpt({ format: e.target.value })}>
              <option value="wav">WAV</option><option value="mp3">MP3</option>
            </select>
          </label>
        </div>
      </section>

      <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="mb-2 text-lg font-medium">{t("dub.plan")}</h2>
        <div className="mb-3 flex flex-wrap gap-2">
          <button className={btn} disabled={!o?.targetLang || running} onClick={() => void run(() => dub.plan())}>{t("dub.makePlan")}</button>
          <button className={btn} disabled={!items.length || running} onClick={() => void run(() => dub.synthesize())}>{t("dub.synth")}</button>
          <button className={btn} disabled={!synthesized || running} onClick={() => void run(() => dub.mix())}>{t("dub.mix")}</button>
        </div>
        {items.length > 0 && (
          <ol className="max-h-[32rem] space-y-2 overflow-y-auto pr-1">
            {items.map((it) => (
              <ItemRow key={it.id} it={it} voices={voices} onEdit={(id, patch) => void run(() => dub.command("set-item", { id, ...patch }))} />
            ))}
          </ol>
        )}
      </section>

      {st?.result && (
        <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="mb-2 text-lg font-medium">{t("dub.result")}</h2>
          {stats && <p className="mb-2 text-sm">{t("dub.stats", { ok: stats.ok, sped: stats.sped, long: stats.too_long, short: stats.shortened })}{st.result.background ? ` · ${t("dub.withBg")}` : ""}</p>}
          {urls.video && <video controls src={urls.video} className="mb-2 max-h-96 w-full rounded bg-black" aria-label="dubbed video" />}
          <ul className="space-y-1 text-sm">
            {urls.video && <li><a className="text-indigo-600 underline" href={urls.video} download>{st.result.video?.split("/").pop()}</a></li>}
            {urls.audio && <li><a className="text-indigo-600 underline" href={urls.audio} download>{st.result.audio.split("/").pop()}</a></li>}
            {urls.srt && <li><a className="text-indigo-600 underline" href={urls.srt} download>{st.result.subtitles.split("/").pop()}</a></li>}
          </ul>
        </section>
      )}
    </div>
  );
}

export function Dubbing() {
  const { t } = useI18n();
  const [pid, setPid] = useState("");
  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold">{t("dub.title")}</h1>
      <p className="mb-4 text-zinc-600 dark:text-zinc-400">{t("dub.subtitle")}</p>
      <ProjectPicker storageKey="dub.pid" value={pid} onChange={setPid} />
      {pid && <Workspace key={pid} pid={pid} />}
    </div>
  );
}
