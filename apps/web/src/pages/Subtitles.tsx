import type { Job } from "@openstudio/protocol";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiRequestError } from "../api/client";
import { useApi } from "../api/connection";
import { subscribeEvents } from "../api/sse";
import { LANGS, SubtitlesApi, type LlmStatus, type SubtitleState, type ToolStateResponse } from "../api/subtitles";
import { CueEditor } from "../components/CueEditor";
import { useI18n } from "../i18n";
import { shiftAll, type Cue } from "../lib/cues";

function Section({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="mb-3 text-lg font-medium"><span className="mr-2 text-zinc-400">{n}.</span>{title}</h2>
      {children}
    </section>
  );
}

const btn = "rounded bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-500 disabled:opacity-50";
const btn2 = "rounded border px-3 py-1.5 text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50";
const field = "rounded border px-2 py-1 text-sm dark:bg-zinc-800";

function JobBar({ job }: { job: Job }) {
  const { t } = useI18n();
  const p = job.progress;
  return (
    <li className="text-sm">
      <div className="flex justify-between">
        <span>{job.type.replace("subtitles.", "")} · {p?.message || p?.phase || job.status}</span>
        <span className={job.status === "failed" ? "text-red-600" : ""}>
          {job.status === "failed" ? job.error?.message : job.status === "succeeded" ? t("sub.done") : `${Math.round(p?.percent ?? 0)}%`}
        </span>
      </div>
      {(job.status === "running" || job.status === "queued") && <progress className="w-full" max={100} value={p?.percent ?? 0} />}
    </li>
  );
}

function Workspace({ pid }: { pid: string }) {
  const api = useApi();
  const { t } = useI18n();
  const sapi = useMemo(() => new SubtitlesApi(api, pid), [api, pid]);
  const [ts, setTs] = useState<ToolStateResponse | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [llm, setLlm] = useState<LlmStatus | null>(null);
  const [msg, setMsg] = useState<{ text: string; modelId?: string } | null>(null);
  const [lang, setLang] = useState<string | null>(null);
  const [draft, setDraft] = useState<Cue[] | null>(null);
  const [time, setTime] = useState(0);
  const [mediaUrl, setMediaUrl] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [srcLang, setSrcLang] = useState("");
  const [polish, setPolish] = useState(true);
  const [targets, setTargets] = useState<string[]>(["en"]);
  const [tone, setTone] = useState("neutral");
  const [glossary, setGlossary] = useState("");
  const [exp, setExp] = useState({ format: "srt", second: "", order: "primary-top", layout: "horizontal", fit: "pad" });
  const [downloads, setDownloads] = useState<{ name: string; url: string }[]>([]);
  const media = useRef<HTMLVideoElement | null>(null);

  const st = (ts?.state ?? {}) as Partial<SubtitleState>;
  const tracks = st.tracks ?? {};
  const langs = Object.keys(tracks);
  const track = lang ? tracks[lang] : undefined;
  const cues = draft ?? track?.cues ?? [];
  const reference = track?.kind === "translation" && st.sourceLang ? tracks[st.sourceLang]?.cues : undefined;
  const dirty = draft !== null;
  const running = jobs.some((j) => j.status === "running" || j.status === "queued");

  const refresh = useCallback(async () => {
    const [s, j] = await Promise.all([sapi.state(), api.jobs(pid)]);
    setTs(s);
    setJobs(j.slice(0, 8));
  }, [sapi, api, pid]);

  useEffect(() => {
    void refresh().catch(() => setMsg({ text: t("common.error") }));
    api.llmStatus().then(setLlm).catch(() => setLlm(null));
    const ctl = new AbortController();
    subscribeEvents(api.conn, { projectId: pid }, (e) => {
      if (e.type === "job.progress" && e.jobId) {
        setJobs((js) => js.map((j) => (j.id === e.jobId ? { ...j, status: "running", progress: e.data as Job["progress"] } : j)));
      } else if (e.type.startsWith("job.") || e.type === "state.changed") {
        void refresh().catch(() => undefined);
      }
    }, ctl.signal);
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid]);

  useEffect(() => {
    if (!lang || !tracks[lang]) setLang(st.sourceLang && tracks[st.sourceLang] ? st.sourceLang : langs[0] ?? null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ts]);
  useEffect(() => setGlossary((st.glossary ?? []).map((g) => `${g.src} = ${g.dst}`).join("\n")), [ts?.state && (ts.state as SubtitleState).revisionId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    setMediaUrl(null);
    if (st.source?.path) sapi.fileUrl(st.source.path).then(setMediaUrl).catch(() => undefined);
  }, [st.source?.path, sapi]);

  const run = async (fn: () => Promise<unknown>) => {
    setMsg(null);
    try {
      await fn();
      await refresh();
    } catch (e) {
      if (e instanceof ApiRequestError) setMsg({ text: e.message, modelId: e.code === "MODEL_MISSING" ? String(e.details?.modelId) : undefined });
      else setMsg({ text: t("common.error") });
    }
  };

  const save = () => run(async () => {
    if (!lang || !track || !draft) return;
    await sapi.saveTrack(lang, track.kind, draft, ts!.revision);
    setDraft(null);
  });

  const parseGlossary = () =>
    glossary.split("\n").map((l) => l.split("=")).filter((p) => p[0]?.trim()).map((p) => ({ src: p[0].trim(), dst: (p[1] ?? p[0]).trim() }));

  const doExport = () => run(async () => {
    if (!lang) return;
    const r = await sapi.exportTrack({ lang, format: exp.format, second: exp.second || null, order: exp.order, layout: exp.layout });
    const u = await sapi.fileUrl(r.path);
    setDownloads((d) => [{ name: r.path.split("/").pop() ?? r.path, url: u }, ...d]);
  });

  const ready = !!st.source;

  return (
    <div className="space-y-4">
      {msg && (
        <p role="alert" className="rounded bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950">
          {msg.text}{" "}
          {msg.modelId && <button className="underline" onClick={() => void run(() => api.downloadModel(msg.modelId!))}>{t("sub.downloadModel")} ({msg.modelId})</button>}
        </p>
      )}
      {jobs.length > 0 && <ul className="space-y-2 rounded-xl border border-zinc-200 p-3 dark:border-zinc-800" aria-label="jobs">{jobs.slice(0, 4).map((j) => <JobBar key={j.id} job={j} />)}</ul>}

      <Section n={1} title={t("sub.source")}>
        {st.source ? (
          <p className="mb-2 text-sm"><strong>{st.source.filename}</strong> · {Math.round(st.source.duration)}s{st.source.width ? ` · ${st.source.width}×${st.source.height}` : ` · ${t("sub.audioOnly")}`}</p>
        ) : <p className="mb-2 text-sm text-zinc-500">{t("sub.noSource")}</p>}
        <div className="flex flex-wrap items-center gap-2">
          <input type="file" aria-label={t("sub.upload")} accept="video/*,audio/*" disabled={running}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void run(() => sapi.upload(f)); }} />
          <input className={`${field} w-72`} placeholder="https://…" aria-label="URL" value={url} onChange={(e) => setUrl(e.target.value)} />
          <button className={btn2} disabled={!url || running} onClick={() => void run(() => sapi.fetchUrl(url))}>{t("sub.fetch")}</button>
        </div>
      </Section>

      <Section n={2} title={t("sub.transcribe")}>
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm">{t("sub.sourceLang")}{" "}
            <select className={field} value={srcLang} onChange={(e) => setSrcLang(e.target.value)}>
              <option value="">{t("sub.auto")}</option>
              {Object.entries(LANGS).map(([c, n]) => <option key={c} value={c}>{n}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-1 text-sm">
            <input type="checkbox" checked={polish} onChange={(e) => setPolish(e.target.checked)} />{t("sub.polish")}
          </label>
          <button className={btn} disabled={!ready || running} onClick={() => void run(() => sapi.transcribe(srcLang || null, polish))}>{t("sub.runTranscribe")}</button>
        </div>
        <label className="mt-3 block text-sm">{t("sub.glossary")}
          <textarea className={`${field} mt-1 w-full font-mono`} rows={3} placeholder={t("sub.glossaryHint")} value={glossary}
            onChange={(e) => setGlossary(e.target.value)} onBlur={() => void run(() => sapi.setGlossary(parseGlossary()))} />
        </label>
      </Section>

      <Section n={3} title={t("sub.translate")}>
        {llm && !llm.available && <p className="mb-2 text-sm text-amber-700">{t("sub.llmDown")}</p>}
        {llm?.available && !llm.model_installed && <p className="mb-2 text-sm text-amber-700">{t("sub.llmModel", { model: llm.model })}</p>}
        <div className="mb-2 flex flex-wrap gap-2" role="group" aria-label={t("sub.targets")}>
          {Object.entries(LANGS).filter(([c]) => c !== st.sourceLang).map(([c, n]) => (
            <label key={c} className={`cursor-pointer rounded-full border px-2 py-0.5 text-sm ${targets.includes(c) ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950" : ""}`}>
              <input type="checkbox" className="sr-only" checked={targets.includes(c)}
                onChange={() => setTargets((x) => (x.includes(c) ? x.filter((k) => k !== c) : [...x, c]))} />{n}
            </label>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm">{t("sub.tone")}{" "}
            <select className={field} value={tone} onChange={(e) => setTone(e.target.value)}>
              <option value="neutral">{t("sub.tone.neutral")}</option><option value="formal">{t("sub.tone.formal")}</option><option value="casual">{t("sub.tone.casual")}</option>
            </select>
          </label>
          <button className={btn} disabled={!st.sourceLang || !targets.length || running} onClick={() => void run(() => sapi.translate(targets, tone, null))}>{t("sub.runTranslate")}</button>
        </div>
      </Section>

      <Section n={4} title={t("sub.editor")}>
        {!langs.length ? <p className="text-sm text-zinc-500">{t("sub.noTracks")}</p> : (
          <div className="grid gap-4 lg:grid-cols-2">
            <div>
              {mediaUrl && <video ref={media} src={mediaUrl} controls className="w-full rounded bg-black" aria-label="preview"
                onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)} />}
              {mediaUrl && cues.length > 0 && <p className="mt-2 min-h-12 rounded bg-black/80 p-2 text-center text-white" aria-live="off">{cues.find((c) => time >= c.start && time < c.end)?.text ?? ""}</p>}
            </div>
            <div>
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <div role="tablist" className="flex gap-1">
                  {langs.map((l) => (
                    <button key={l} role="tab" aria-selected={l === lang} onClick={() => { setLang(l); setDraft(null); }}
                      className={`rounded px-2 py-1 text-sm ${l === lang ? "bg-indigo-600 text-white" : "border"}`}>
                      {LANGS[l] ?? l}{tracks[l].stale ? " ⚠" : ""}
                    </button>
                  ))}
                </div>
                <button className={btn} disabled={!dirty} onClick={() => void save()}>{t("sub.save")}</button>
                <button className={btn2} disabled={!dirty} onClick={() => setDraft(null)}>{t("sub.discard")}</button>
                <button className={btn2} onClick={() => setDraft(shiftAll(cues, 0.1))} title={t("sub.shift")}>+0.1s</button>
                <button className={btn2} onClick={() => setDraft(shiftAll(cues, -0.1))} title={t("sub.shift")}>−0.1s</button>
              </div>
              {track?.stale && <p className="mb-2 text-sm text-amber-700">{t("sub.stale")}</p>}
              {track && Number(track.meta.fallbacks) > 0 && <p className="mb-2 text-sm text-amber-700">{t("sub.fallbacks", { n: String(track.meta.fallbacks) })}</p>}
              <CueEditor cues={cues} reference={reference} currentTime={time} onChange={setDraft}
                onSeek={(s) => { if (media.current) { media.current.currentTime = s; void media.current.play?.(); } }} />
            </div>
          </div>
        )}
      </Section>

      <Section n={5} title={t("sub.export")}>
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm">{t("sub.format")}{" "}
            <select className={field} value={exp.format} onChange={(e) => setExp({ ...exp, format: e.target.value })}>
              <option value="srt">SRT</option><option value="vtt">VTT</option><option value="ass">ASS</option>
            </select>
          </label>
          <label className="text-sm">{t("sub.bilingual")}{" "}
            <select className={field} value={exp.second} onChange={(e) => setExp({ ...exp, second: e.target.value })}>
              <option value="">{t("sub.none")}</option>
              {langs.filter((l) => l !== lang).map((l) => <option key={l} value={l}>{LANGS[l] ?? l}</option>)}
            </select>
          </label>
          <label className="text-sm">{t("sub.order")}{" "}
            <select className={field} value={exp.order} onChange={(e) => setExp({ ...exp, order: e.target.value })}>
              <option value="primary-top">{t("sub.order.top")}</option><option value="primary-bottom">{t("sub.order.bottom")}</option>
            </select>
          </label>
          <label className="text-sm">{t("sub.layout")}{" "}
            <select className={field} value={exp.layout} onChange={(e) => setExp({ ...exp, layout: e.target.value })}>
              <option value="horizontal">16:9</option><option value="vertical">9:16</option>
            </select>
          </label>
          {exp.layout === "vertical" && (
            <label className="text-sm">{t("sub.fit")}{" "}
              <select className={field} value={exp.fit} onChange={(e) => setExp({ ...exp, fit: e.target.value })}>
                <option value="pad">{t("sub.fit.pad")}</option><option value="crop">{t("sub.fit.crop")}</option>
              </select>
            </label>
          )}
        </div>
        <div className="mt-3 flex gap-2">
          <button className={btn} disabled={!lang || dirty} onClick={() => void doExport()}>{t("sub.exportFile")}</button>
          <button className={btn2} disabled={!lang || dirty || running || !ready}
            onClick={() => void run(() => sapi.burn({ lang: lang!, second: exp.second || null, order: exp.order, layout: exp.layout, fit: exp.fit }))}>{t("sub.burn")}</button>
        </div>
        {dirty && <p className="mt-1 text-xs text-amber-700">{t("sub.saveFirst")}</p>}
        <ul className="mt-3 space-y-1 text-sm">
          {downloads.map((d) => <li key={d.url}><a className="text-indigo-600 underline" href={d.url} download={d.name}>{d.name}</a></li>)}
          {jobs.filter((j) => j.type === "subtitles.burn" && j.status === "succeeded").slice(0, 3).map((j) => (
            <ResultLink key={j.id} sapi={sapi} path={String((j.result as { path?: string } | null)?.path ?? "")} />
          ))}
        </ul>
      </Section>
    </div>
  );
}

function ResultLink({ sapi, path }: { sapi: SubtitlesApi; path: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => { sapi.fileUrl(path).then(setUrl).catch(() => undefined); }, [sapi, path]);
  const name = path.split("/").pop() ?? path;
  return url ? <li><a className="text-indigo-600 underline" href={url} download={name}>{name}</a></li> : null;
}

export function Subtitles() {
  const api = useApi();
  const { t } = useI18n();
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [pid, setPid] = useState<string>(() => {
    try { return sessionStorage.getItem("sub.pid") ?? ""; } catch { return ""; }
  });
  const [name, setName] = useState("");

  const load = useCallback(() => api.projects().then(setProjects), [api]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { try { sessionStorage.setItem("sub.pid", pid); } catch { /* bỏ qua */ } }, [pid]);

  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold">{t("sub.title")}</h1>
      <p className="mb-4 text-zinc-600 dark:text-zinc-400">{t("sub.subtitle")}</p>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <select aria-label={t("library.projects")} className={field} value={pid} onChange={(e) => setPid(e.target.value)}>
          <option value="">{t("sub.pickProject")}</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <input className={field} placeholder={t("library.projectName")} aria-label={t("library.projectName")} value={name} onChange={(e) => setName(e.target.value)} />
        <button className={btn2} disabled={!name.trim()} onClick={async () => { const p = await api.createProject(name.trim()); setName(""); await load(); setPid(p.id); }}>{t("library.newProject")}</button>
      </div>
      {pid && projects.some((p) => p.id === pid) ? <Workspace key={pid} pid={pid} /> : null}
    </div>
  );
}
