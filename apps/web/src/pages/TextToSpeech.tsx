import { useCallback, useEffect, useMemo, useState } from "react";
import { AudioApi, TtsApi, type ConsentRecord, type EngineInfo, type TtsState, type VoiceInfo } from "../api/audio";
import { ApiRequestError } from "../api/client";
import { useApi } from "../api/connection";
import { LANGS } from "../api/subtitles";
import { ProjectPicker } from "../components/ProjectPicker";
import { useI18n } from "../i18n";
import { parseSpeakers } from "../lib/script";
import { JobList, useProjectJobs } from "../lib/useJobs";

const btn = "rounded bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-500 disabled:opacity-50";
const btn2 = "rounded border px-3 py-1.5 text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50";
const field = "rounded border px-2 py-1 text-sm dark:bg-zinc-800";
const TTS_LANGS = ["vi", "en", "ja", "zh", "es", "fr", "hi", "it", "pt"];
const SAMPLE: Record<string, string> = { vi: "Xin chào, đây là giọng đọc thử.", en: "Hello, this is a voice sample." };

export function CloneVoicePanel({ audio, onCreated, clones, onDelete }: {
  audio: AudioApi; onCreated: () => void; clones: VoiceInfo[]; onDelete: (id: string) => void;
}) {
  const { t } = useI18n();
  const [subject, setSubject] = useState("");
  const [name, setName] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [statement, setStatement] = useState<string | null>(null);
  const ready = confirmed && subject.trim() && name.trim() && file && !busy;

  const create = async () => {
    if (!file) return;
    setBusy(true);
    setErr(null);
    try {
      const consent: ConsentRecord = await audio.createConsent(subject.trim(), confirmed);
      await audio.cloneVoice(file, name.trim(), consent.id);
      setSubject(""); setName(""); setFile(null); setConfirmed(false);
      onCreated();
    } catch (e) {
      if (e instanceof ApiRequestError && e.details?.statement) setStatement(String(e.details.statement));
      setErr(e instanceof ApiRequestError ? e.message : t("common.error"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-sm text-zinc-600 dark:text-zinc-400">{t("tts.cloneHelp")}</p>
      {err && <p role="alert" className="text-sm text-red-600">{err}</p>}
      {statement && <p className="text-xs text-zinc-500">{statement}</p>}
      <div className="flex flex-wrap gap-2">
        <input className={field} aria-label={t("tts.voiceName")} placeholder={t("tts.voiceName")} value={name} onChange={(e) => setName(e.target.value)} />
        <input className={field} aria-label={t("tts.subject")} placeholder={t("tts.subject")} value={subject} onChange={(e) => setSubject(e.target.value)} />
        <input type="file" accept="audio/*,video/*" aria-label={t("tts.sample")} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </div>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
        <span>{t("tts.consent")}</span>
      </label>
      <button className={btn} disabled={!ready} onClick={() => void create()}>{t("tts.createClone")}</button>
      {clones.length > 0 && (
        <ul className="space-y-1 text-sm">
          {clones.map((v) => (
            <li key={v.id} className="flex items-center justify-between rounded border border-zinc-200 px-2 py-1 dark:border-zinc-800">
              <span>{v.name} <span className="text-xs text-zinc-500">· {v.description}</span></span>
              <button className="text-red-700 underline" onClick={() => onDelete(v.id)}>{t("settings.models.delete")}</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Workspace({ pid }: { pid: string }) {
  const api = useApi();
  const { t } = useI18n();
  const audio = useMemo(() => new AudioApi(api), [api]);
  const tts = useMemo(() => new TtsApi(api, pid), [api, pid]);
  const [st, setSt] = useState<TtsState | null>(null);
  const [text, setText] = useState("");
  const [voices, setVoices] = useState<VoiceInfo[]>([]);
  const [engines, setEngines] = useState<EngineInfo[]>([]);
  const [msg, setMsg] = useState<{ text: string; modelId?: string } | null>(null);
  const [resultUrl, setResultUrl] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  const loadState = useCallback(async () => {
    const s = (await tts.state()).state as Partial<TtsState>;
    setSt({ text: "", language: "vi", voices: {}, options: { speed: 1, format: "wav", gap: 0.3, loudnorm: true }, result: null, ...s } as TtsState);
  }, [tts]);
  const { jobs, running, refresh } = useProjectJobs(pid, () => void loadState());
  const language = st?.language ?? "vi";
  const speakers = useMemo(() => parseSpeakers(text), [text]);

  useEffect(() => { void loadState().then(() => undefined); }, [loadState]);
  useEffect(() => { if (st) setText((cur) => (cur === "" ? st.text : cur)); }, [st?.revisionId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { audio.engines().then(setEngines).catch(() => undefined); }, [audio]);
  const loadVoices = useCallback(() => audio.voices().then(setVoices).catch(() => undefined), [audio]);
  useEffect(() => { void loadVoices(); }, [loadVoices]);
  useEffect(() => {
    setResultUrl(null);
    if (st?.result?.path) tts.fileUrl(st.result.path).then(setResultUrl).catch(() => undefined);
  }, [st?.result?.path, tts]);

  const run = async (fn: () => Promise<unknown>) => {
    setMsg(null);
    try { await fn(); await refresh(); } catch (e) {
      if (e instanceof ApiRequestError) setMsg({ text: e.message, modelId: e.code === "MODEL_MISSING" ? String(e.details?.modelId) : undefined });
      else setMsg({ text: t("common.error") });
    }
  };

  const voiceOptions = (lang: string) => voices.filter((v) => v.kind === "clone" || v.lang === lang || (v.engine === "vieneu" && lang === "en"));
  const setVoice = (sp: string, v: string) => run(async () => { await tts.command("set-voices", { voices: { ...st?.voices, [sp]: v } }); await loadState(); });
  const saveScript = (lang = language) => run(async () => { await tts.command("set-script", { text, language: lang }); await loadState(); });
  const setOpt = (o: object) => run(async () => { await tts.command("set-options", { options: o }); await loadState(); });
  const engineMissing = engines.filter((e) => e.model && !e.available && e.languages.includes(language));

  return (
    <div className="space-y-4">
      {msg && (
        <p role="alert" className="rounded bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950">
          {msg.text}{" "}
          {msg.modelId && <button className="underline" onClick={() => void run(() => api.downloadModel(msg.modelId!))}>{t("sub.downloadModel")} ({msg.modelId})</button>}
        </p>
      )}
      {engineMissing.length > 0 && (
        <p className="rounded bg-amber-50 p-2 text-sm text-amber-800 dark:bg-amber-950">
          {t("tts.needModel")}{" "}
          {engineMissing.map((e) => <button key={e.id} className="mr-2 underline" onClick={() => void run(() => api.downloadModel(e.model!))}>{e.name}</button>)}
        </p>
      )}
      <JobList jobs={jobs} />

      <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="mb-2 text-lg font-medium">{t("tts.script")}</h2>
        <div className="mb-2 flex flex-wrap items-center gap-3">
          <label className="text-sm">{t("tts.language")}{" "}
            <select className={field} value={language} onChange={(e) => void saveScript(e.target.value)}>
              {TTS_LANGS.map((l) => <option key={l} value={l}>{LANGS[l] ?? l}</option>)}
            </select>
          </label>
        </div>
        <textarea aria-label={t("tts.script")} className={`${field} w-full font-mono`} rows={8} value={text} placeholder={t("tts.scriptHint")}
          onChange={(e) => setText(e.target.value)} onBlur={() => void saveScript()} />
        <p className="mt-1 text-xs text-zinc-500">{t("tts.syntax")}</p>
      </section>

      <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="mb-2 text-lg font-medium">{t("tts.voices")}</h2>
        {speakers.length === 0 ? <p className="text-sm text-zinc-500">{t("tts.noSpeakers")}</p> : (
          <ul className="space-y-2">
            {speakers.map((sp) => (
              <li key={sp} className="flex flex-wrap items-center gap-2 text-sm">
                <strong className="w-28">{sp === "default" ? t("tts.default") : sp}</strong>
                <select aria-label={`${t("tts.voice")} ${sp}`} className={field} value={st?.voices[sp] ?? ""} onChange={(e) => void setVoice(sp, e.target.value)}>
                  <option value="">{t("tts.autoVoice")}</option>
                  {voiceOptions(language).map((v) => <option key={v.id} value={v.id}>{v.name} {v.kind === "clone" ? "(nhân bản)" : v.gender ? `(${v.gender})` : ""}</option>)}
                </select>
                <button className={btn2} disabled={running} onClick={() => void run(async () => {
                  const v = st?.voices[sp] || voiceOptions(language)[0]?.id;
                  if (!v) return;
                  const job = await tts.preview(v, SAMPLE[language] ?? SAMPLE.en, language);
                  const poll = async (): Promise<void> => {
                    const j = await tts.job(job.id);
                    if (j.status === "succeeded") setPreviewUrl(await tts.fileUrl(String((j.result as { path: string }).path)));
                    else if (j.status === "running" || j.status === "queued") { await new Promise((r) => setTimeout(r, 1500)); await poll(); }
                  };
                  await poll();
                })}>{t("tts.preview")}</button>
              </li>
            ))}
          </ul>
        )}
        {previewUrl && <audio className="mt-2" controls src={previewUrl} aria-label="preview" />}
      </section>

      <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="mb-2 text-lg font-medium">{t("tts.options")}</h2>
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <label>{t("tts.speed")}: {st?.options.speed.toFixed(2)}{" "}
            <input type="range" min={0.5} max={2} step={0.05} value={st?.options.speed ?? 1} aria-label={t("tts.speed")}
              onChange={(e) => setSt((s) => s && { ...s, options: { ...s.options, speed: Number(e.target.value) } })}
              onMouseUp={(e) => void setOpt({ speed: Number((e.target as HTMLInputElement).value) })}
              onKeyUp={(e) => void setOpt({ speed: Number((e.target as HTMLInputElement).value) })} />
          </label>
          <label>{t("tts.gap")}{" "}
            <select className={field} value={st?.options.gap ?? 0.3} onChange={(e) => void setOpt({ gap: Number(e.target.value) })}>
              {[0, 0.15, 0.3, 0.5, 0.8, 1.2].map((g) => <option key={g} value={g}>{g}s</option>)}
            </select>
          </label>
          <label>{t("sub.format")}{" "}
            <select className={field} value={st?.options.format ?? "wav"} onChange={(e) => void setOpt({ format: e.target.value })}>
              <option value="wav">WAV</option><option value="mp3">MP3</option>
            </select>
          </label>
        </div>
        <div className="mt-3 flex items-center gap-3">
          <button className={btn} disabled={!text.trim() || running} onClick={() => void run(async () => { await tts.command("set-script", { text, language }); await tts.synthesize(); })}>{t("tts.run")}</button>
        </div>
      </section>

      {st?.result && (
        <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="mb-2 text-lg font-medium">{t("tts.result")}</h2>
          {resultUrl && (
            <div className="space-y-2">
              <audio controls src={resultUrl} className="w-full" aria-label="result" />
              <a className="text-sm text-indigo-600 underline" href={resultUrl} download={st.result.path.split("/").pop()}>{st.result.path.split("/").pop()}</a>
            </div>
          )}
          {st.result.failed.length > 0 && <p className="mt-2 text-sm text-amber-700">{t("tts.failed", { n: st.result.failed.length })}</p>}
          <ol className="mt-2 max-h-56 space-y-1 overflow-y-auto text-sm">
            {st.result.segments.map((s) => <li key={s.index}><span className="text-xs text-zinc-500">{s.start.toFixed(1)}–{s.end.toFixed(1)}s · {s.speaker}</span> {s.text}</li>)}
          </ol>
        </section>
      )}

      <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="mb-2 text-lg font-medium">{t("tts.clone")}</h2>
        <CloneVoicePanel audio={audio} onCreated={() => void loadVoices()} clones={voices.filter((v) => v.kind === "clone")}
          onDelete={(id) => void audio.deleteVoice(id).then(loadVoices)} />
      </section>
    </div>
  );
}

export function TextToSpeech() {
  const { t } = useI18n();
  const [pid, setPid] = useState("");
  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold">{t("tts.title")}</h1>
      <p className="mb-4 text-zinc-600 dark:text-zinc-400">{t("tts.subtitle")}</p>
      <ProjectPicker storageKey="tts.pid" value={pid} onChange={setPid} />
      {pid && <Workspace key={pid} pid={pid} />}
    </div>
  );
}
