import { useCallback, useEffect, useMemo, useState } from "react";
import { AudioApi, type VoiceInfo } from "../api/audio";
import { ApiRequestError } from "../api/client";
import { useApi } from "../api/connection";
import { MusicApi, PodcastApi, type MusicItem, type PodcastScript, type PodcastState } from "../api/studio";
import { LANGS } from "../api/subtitles";
import { ProjectPicker } from "../components/ProjectPicker";
import { useI18n } from "../i18n";
import { fmtTime } from "../lib/cues";
import { JobList, useProjectJobs } from "../lib/useJobs";

const btn = "rounded bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-500 disabled:opacity-50";
const btn2 = "rounded border px-3 py-1.5 text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50";
const field = "rounded border px-2 py-1 text-sm dark:bg-zinc-800";
const card = "rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900";
const EMPTY: PodcastState = {
  brief: { topic: "", sourceText: "", sourceName: null, language: "vi", minutes: 3, style: "thân thiện, dễ hiểu", hosts: [{ name: "Minh", voice: null }, { name: "Lan", voice: null }] },
  script: null, music: { intro: null, outro: null, bed: null, bedGain: -22 },
  options: { format: "mp3", video: true, layout: "horizontal", gap: 0.35, speed: 1 }, result: null,
};

export function ScriptEditor({ script, hosts, onSave }: { script: PodcastScript; hosts: string[]; onSave: (s: PodcastScript) => void }) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(script);
  useEffect(() => setDraft(script), [script]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(script);
  const setTurn = (si: number, ti: number, patch: Partial<{ speaker: string; text: string }>) =>
    setDraft({ ...draft, sections: draft.sections.map((s, i) => (i !== si ? s : { ...s, turns: s.turns.map((x, j) => (j === ti ? { ...x, ...patch } : x)) })) });
  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-2">
        <input aria-label={t("pod.epTitle")} className={field} value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
        <input aria-label={t("pod.epSummary")} className={field} value={draft.summary} onChange={(e) => setDraft({ ...draft, summary: e.target.value })} />
      </div>
      {draft.sections.map((sec, si) => (
        <div key={si} className="rounded-lg border border-zinc-200 p-2 dark:border-zinc-800">
          <input aria-label={`${t("pod.chapter")} ${si + 1}`} className={`${field} mb-2 w-full font-medium`} value={sec.title}
            onChange={(e) => setDraft({ ...draft, sections: draft.sections.map((s, i) => (i === si ? { ...s, title: e.target.value } : s)) })} />
          <ol className="space-y-1">
            {sec.turns.map((tr, ti) => (
              <li key={ti} className="flex gap-2">
                <select aria-label={`${t("pod.speaker")} ${si + 1}.${ti + 1}`} className={field} value={tr.speaker} onChange={(e) => setTurn(si, ti, { speaker: e.target.value })}>
                  {hosts.map((h) => <option key={h}>{h}</option>)}
                </select>
                <textarea aria-label={`${t("sub.text")} ${si + 1}.${ti + 1}`} rows={2} className={`${field} flex-1`} value={tr.text} onChange={(e) => setTurn(si, ti, { text: e.target.value })} />
                <button className="text-red-700" title={t("sub.delete")} onClick={() => setDraft({ ...draft, sections: draft.sections.map((s, i) => (i === si ? { ...s, turns: s.turns.filter((_, j) => j !== ti) } : s)).filter((s) => s.turns.length) })}>✕</button>
              </li>
            ))}
          </ol>
          <button className="mt-1 text-xs underline" onClick={() => setDraft({ ...draft, sections: draft.sections.map((s, i) => (i === si ? { ...s, turns: [...s.turns, { speaker: hosts[s.turns.length % hosts.length], text: "" }] } : s)) })}>{t("pod.addTurn")}</button>
        </div>
      ))}
      <button className={btn} disabled={!dirty || draft.sections.some((s) => s.turns.some((x) => !x.text.trim()))} onClick={() => onSave(draft)}>{t("pod.saveScript")}</button>
    </div>
  );
}

function Workspace({ pid }: { pid: string }) {
  const api = useApi();
  const { t } = useI18n();
  const pod = useMemo(() => new PodcastApi(api, pid), [api, pid]);
  const lib = useMemo(() => new MusicApi(api), [api]);
  const audio = useMemo(() => new AudioApi(api), [api]);
  const [st, setSt] = useState<PodcastState>(EMPTY);
  const [music, setMusic] = useState<MusicItem[]>([]);
  const [voices, setVoices] = useState<VoiceInfo[]>([]);
  const [msg, setMsg] = useState<{ text: string; modelId?: string } | null>(null);
  const [topic, setTopic] = useState("");
  const [urls, setUrls] = useState<{ audio?: string; video?: string; notes?: string; chapters?: string }>({});
  const [up, setUp] = useState({ name: "", kind: "bed", license: "", file: null as File | null });

  const load = useCallback(async () => {
    const s = (await pod.state()).state as Partial<PodcastState>;
    setSt({ ...EMPTY, ...s } as PodcastState);
  }, [pod]);
  const { jobs, running, refresh } = useProjectJobs(pid, () => void load());
  useEffect(() => { void load().catch(() => setMsg({ text: t("common.error") })); }, [load, t]);
  useEffect(() => setTopic((cur) => cur || st.brief.topic), [st.brief.topic]);
  const loadMusic = useCallback(() => lib.list().then(setMusic).catch(() => undefined), [lib]);
  useEffect(() => { void loadMusic(); }, [loadMusic]);
  useEffect(() => { audio.voices(st.brief.language).then(setVoices).catch(() => undefined); }, [audio, st.brief.language]);
  useEffect(() => {
    const r = st.result;
    setUrls({});
    if (!r) return;
    void (async () => setUrls({ audio: await pod.fileUrl(r.audio), video: r.video ? await pod.fileUrl(r.video) : undefined, notes: await pod.fileUrl(r.notes), chapters: await pod.fileUrl(r.chapters) }))().catch(() => undefined);
  }, [st.result, pod]);

  const run = async (fn: () => Promise<unknown>) => {
    setMsg(null);
    try { await fn(); await load(); await refresh(); } catch (e) {
      if (e instanceof ApiRequestError) setMsg({ text: e.message, modelId: e.code === "MODEL_MISSING" ? String(e.details?.modelId) : undefined });
      else setMsg({ text: t("common.error") });
    }
  };
  const brief = st.brief;
  const setBrief = (patch: Partial<PodcastState["brief"]>) => run(() => pod.command("set-brief", { brief: patch }));
  const setMus = (m: Partial<PodcastState["music"]>) => run(() => pod.command("set-music", { music: m }));
  const setOpt = (o: Partial<PodcastState["options"]>) => run(() => pod.command("set-options", { options: o }));
  const musicChoices = (kind: string) => music.filter((m) => m.builtin || m.kind === kind);
  const hosts = brief.hosts.map((h) => h.name);

  return (
    <div className="space-y-4">
      {msg && (
        <p role="alert" className="rounded bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950">
          {msg.text}{" "}
          {msg.modelId && <button className="underline" onClick={() => void run(() => api.downloadModel(msg.modelId!))}>{t("sub.downloadModel")} ({msg.modelId})</button>}
        </p>
      )}
      <JobList jobs={jobs} />

      <section className={card}>
        <h2 className="mb-2 text-lg font-medium">{t("pod.brief")}</h2>
        <textarea aria-label={t("pod.topic")} placeholder={t("pod.topic")} rows={2} className={`${field} w-full`} value={topic}
          onChange={(e) => setTopic(e.target.value)} onBlur={() => topic !== brief.topic && void setBrief({ topic })} />
        <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
          <label>{t("pod.source")}{" "}
            <input type="file" accept=".txt,.md,.markdown,text/plain" aria-label={t("pod.source")}
              onChange={async (e) => { const f = e.target.files?.[0]; if (f) await setBrief({ sourceText: await f.text(), sourceName: f.name }); }} />
          </label>
          {brief.sourceName && <span className="text-xs text-zinc-500">{brief.sourceName} · {brief.sourceText.length.toLocaleString()} {t("pod.chars")}
            <button className="ml-2 underline" onClick={() => void setBrief({ sourceText: "", sourceName: null })}>{t("settings.models.delete")}</button></span>}
          <label>{t("tts.language")}{" "}
            <select className={field} value={brief.language} onChange={(e) => void setBrief({ language: e.target.value })}>
              {["vi", "en", "ja", "zh", "es", "fr"].map((l) => <option key={l} value={l}>{LANGS[l]}</option>)}
            </select>
          </label>
          <label>{t("pod.minutes")}{" "}
            <input type="number" min={1} max={30} className={`${field} w-16`} aria-label={t("pod.minutes")} value={brief.minutes} onChange={(e) => void setBrief({ minutes: Number(e.target.value) })} />
          </label>
          <label>{t("pod.style")}{" "}
            <input className={`${field} w-56`} aria-label={t("pod.style")} defaultValue={brief.style} key={brief.style} onBlur={(e) => e.target.value !== brief.style && void setBrief({ style: e.target.value })} />
          </label>
        </div>
        <h3 className="mb-1 mt-3 text-sm font-medium">{t("pod.hosts")}</h3>
        <ul className="space-y-1">
          {brief.hosts.map((h, i) => (
            <li key={i} className="flex flex-wrap items-center gap-2 text-sm">
              <input aria-label={`${t("pod.hostName")} ${i + 1}`} className={`${field} w-32`} defaultValue={h.name} key={h.name + i}
                onBlur={(e) => e.target.value.trim() !== h.name && void setBrief({ hosts: brief.hosts.map((x, j) => (j === i ? { ...x, name: e.target.value.trim() } : x)) })} />
              <select aria-label={`${t("tts.voice")} ${i + 1}`} className={field} value={h.voice ?? ""}
                onChange={(e) => void setBrief({ hosts: brief.hosts.map((x, j) => (j === i ? { ...x, voice: e.target.value || null } : x)) })}>
                <option value="">{t("tts.autoVoice")}</option>
                {voices.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
              </select>
              {brief.hosts.length > 2 && <button className="text-red-700" onClick={() => void setBrief({ hosts: brief.hosts.filter((_, j) => j !== i) })}>✕</button>}
            </li>
          ))}
        </ul>
        {brief.hosts.length < 3 && <button className="mt-1 text-xs underline" onClick={() => void setBrief({ hosts: [...brief.hosts, { name: `Người dẫn ${brief.hosts.length + 1}`, voice: null }] })}>{t("pod.addHost")}</button>}
        <div className="mt-3"><button className={btn} disabled={running || (!topic.trim() && !brief.sourceText.trim())} onClick={() => void run(async () => { if (topic !== brief.topic) await pod.command("set-brief", { brief: { topic } }); await pod.script(); })}>{t("pod.writeScript")}</button></div>
      </section>

      <section className={card}>
        <h2 className="mb-2 text-lg font-medium">{t("pod.script")}</h2>
        {st.script ? (
          <>
            <ScriptEditor script={st.script} hosts={hosts} onSave={(s) => void run(() => pod.command("set-script", { script: s }))} />
            {st.script.takeaways.length > 0 && <ul className="mt-2 list-disc pl-5 text-sm">{st.script.takeaways.map((x, i) => <li key={i}>{x}</li>)}</ul>}
          </>
        ) : <p className="text-sm text-zinc-500">{t("pod.noScript")}</p>}
      </section>

      <section className={card}>
        <h2 className="mb-2 text-lg font-medium">{t("pod.music")}</h2>
        <p className="mb-2 text-xs text-zinc-500">{t("pod.musicHelp")}</p>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          {(["intro", "bed", "outro"] as const).map((k) => (
            <label key={k}>{t(`pod.music.${k}`)}{" "}
              <select aria-label={t(`pod.music.${k}`)} className={field} value={st.music[k] ?? ""} onChange={(e) => void setMus({ [k]: e.target.value || null })}>
                <option value="">{t("sub.none")}</option>
                {musicChoices(k).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
            </label>
          ))}
          <label>{t("pod.bedGain")}: {st.music.bedGain} dB{" "}
            <input type="range" min={-40} max={-6} step={1} aria-label={t("pod.bedGain")} value={st.music.bedGain} onChange={(e) => setSt({ ...st, music: { ...st.music, bedGain: Number(e.target.value) } })}
              onMouseUp={(e) => void setMus({ bedGain: Number((e.target as HTMLInputElement).value) })} onKeyUp={(e) => void setMus({ bedGain: Number((e.target as HTMLInputElement).value) })} />
          </label>
        </div>
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer">{t("pod.addMusic")}</summary>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <input className={field} placeholder={t("pod.musicName")} aria-label={t("pod.musicName")} value={up.name} onChange={(e) => setUp({ ...up, name: e.target.value })} />
            <select className={field} aria-label={t("pod.musicKind")} value={up.kind} onChange={(e) => setUp({ ...up, kind: e.target.value })}>
              <option value="intro">{t("pod.music.intro")}</option><option value="bed">{t("pod.music.bed")}</option><option value="outro">{t("pod.music.outro")}</option>
            </select>
            <input className={`${field} w-64`} placeholder={t("pod.license")} aria-label={t("pod.license")} value={up.license} onChange={(e) => setUp({ ...up, license: e.target.value })} />
            <input type="file" accept="audio/*" aria-label={t("pod.musicFile")} onChange={(e) => setUp({ ...up, file: e.target.files?.[0] ?? null })} />
            <button className={btn2} disabled={!up.file || !up.name.trim() || up.license.trim().length < 3}
              onClick={() => void run(async () => { await lib.add(up.file!, up.name.trim(), up.kind, up.license.trim()); setUp({ name: "", kind: "bed", license: "", file: null }); await loadMusic(); })}>{t("pod.upload")}</button>
          </div>
          <ul className="mt-2 space-y-1">
            {music.filter((m) => !m.builtin).map((m) => (
              <li key={m.id} className="flex items-center justify-between rounded border border-zinc-200 px-2 py-1 dark:border-zinc-800">
                <span>{m.name} <span className="text-xs text-zinc-500">· {m.kind} · {m.license}</span></span>
                <button className="text-red-700 underline" onClick={() => void run(async () => { await lib.remove(m.id); await loadMusic(); })}>{t("settings.models.delete")}</button>
              </li>
            ))}
          </ul>
        </details>
      </section>

      <section className={card}>
        <h2 className="mb-2 text-lg font-medium">{t("pod.produce")}</h2>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label>{t("sub.format")}{" "}
            <select className={field} value={st.options.format} onChange={(e) => void setOpt({ format: e.target.value as "mp3" | "wav" })}><option value="mp3">MP3</option><option value="wav">WAV</option></select>
          </label>
          <label className="flex items-center gap-1"><input type="checkbox" checked={st.options.video} onChange={(e) => void setOpt({ video: e.target.checked })} />{t("pod.video")}</label>
          {st.options.video && (
            <label>{t("sub.layout")}{" "}
              <select className={field} value={st.options.layout} onChange={(e) => void setOpt({ layout: e.target.value as "horizontal" | "vertical" })}><option value="horizontal">16:9</option><option value="vertical">9:16</option></select>
            </label>
          )}
          <button className={btn} disabled={!st.script || running} onClick={() => void run(() => pod.produce())}>{t("pod.run")}</button>
        </div>
      </section>

      {st.result && (
        <section className={card}>
          <h2 className="mb-2 text-lg font-medium">{t("tts.result")}</h2>
          <p className="mb-2 text-sm text-zinc-600">{fmtTime(st.result.duration)} · {st.result.turns} {t("pod.turns")}</p>
          {urls.audio && <audio controls src={urls.audio} className="mb-2 w-full" aria-label="podcast audio" />}
          {urls.video && <video controls src={urls.video} className="mb-2 max-h-80 w-full rounded bg-black" aria-label="podcast video" />}
          <ul className="mb-2 space-y-0.5 text-sm">
            {st.result.chapterList.map((c, i) => <li key={i}><code>{fmtTime(c.start).replace(/\.\d+$/, "")}</code> {c.title}</li>)}
          </ul>
          <p className="flex flex-wrap gap-3 text-sm">
            {urls.audio && <a className="text-indigo-600 underline" href={urls.audio} download>{st.result.audio.split("/").pop()}</a>}
            {urls.video && <a className="text-indigo-600 underline" href={urls.video} download>{st.result.video?.split("/").pop()}</a>}
            {urls.notes && <a className="text-indigo-600 underline" href={urls.notes} download>{t("pod.showNotes")}</a>}
            {urls.chapters && <a className="text-indigo-600 underline" href={urls.chapters} download>{t("pod.chaptersFile")}</a>}
          </p>
        </section>
      )}
    </div>
  );
}

export function Podcast() {
  const { t } = useI18n();
  const [pid, setPid] = useState("");
  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold">{t("pod.title")}</h1>
      <p className="mb-4 text-zinc-600 dark:text-zinc-400">{t("pod.subtitle")}</p>
      <ProjectPicker storageKey="pod.pid" value={pid} onChange={setPid} />
      {pid && <Workspace key={pid} pid={pid} />}
    </div>
  );
}
