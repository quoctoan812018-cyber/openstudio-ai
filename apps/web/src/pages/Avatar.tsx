import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiRequestError } from "../api/client";
import { useApi } from "../api/connection";
import { AssetsApi, AvatarApi, AvatarLibraryApi, type Asset, type AvatarEngine, type AvatarInfo, type AvatarState } from "../api/studio";
import { AssetPanel } from "../components/AssetPanel";
import { ProjectPicker } from "../components/ProjectPicker";
import { useI18n } from "../i18n";
import { JobList, useProjectJobs } from "../lib/useJobs";

const btn = "rounded bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-500 disabled:opacity-50";
const btn2 = "rounded border px-2 py-1 text-xs hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50";
const field = "rounded border px-2 py-1 text-sm dark:bg-zinc-800";
const card = "rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900";
const EMPTY: AvatarState = {
  brief: { avatar: null, audio: null, aspect: "16:9", background: { kind: "blur", color: "#101828", asset: null }, frame: "rounded", border: true, subtitleLang: null, engine: "puppet" },
  result: null,
};

/** Điều kiện bật nút tạo avatar: người thật BẮT BUỘC tick xác nhận + ghi tên chủ nhân khuôn mặt. */
export function canCreateAvatar(f: { name: string; file: File | null; realPerson: boolean | null; subject: string; confirmed: boolean }): boolean {
  if (!f.name.trim() || !f.file || f.realPerson === null) return false;
  return f.realPerson ? f.subject.trim().length > 0 && f.confirmed : true;
}

export function AvatarCreator({ lib, onCreated, statement }: { lib: AvatarLibraryApi; onCreated: () => void; statement: string }) {
  const { t } = useI18n();
  const [f, setF] = useState<{ name: string; file: File | null; realPerson: boolean | null; subject: string; confirmed: boolean }>({ name: "", file: null, realPerson: null, subject: "", confirmed: false });
  const [msg, setMsg] = useState<string | null>(null);
  const create = async () => {
    setMsg(null);
    try {
      const consent = f.realPerson ? await lib.createConsent(f.subject.trim()) : null;
      await lib.create(f.file!, f.name.trim(), !!f.realPerson, consent?.id ?? null);
      setF({ name: "", file: null, realPerson: null, subject: "", confirmed: false });
      onCreated();
    } catch (e) { setMsg(e instanceof ApiRequestError ? e.message : t("common.error")); }
  };
  return (
    <div className="space-y-2 text-sm">
      {msg && <p role="alert" className="text-red-700">{msg}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <input aria-label={t("av.name")} placeholder={t("av.name")} className={field} value={f.name} maxLength={60} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <input type="file" accept="image/*" aria-label={t("av.image")} onChange={(e) => setF({ ...f, file: e.target.files?.[0] ?? null })} />
      </div>
      <fieldset>
        <legend className="font-medium">{t("av.isReal")}</legend>
        <label className="mr-4"><input type="radio" name="real" checked={f.realPerson === false} onChange={() => setF({ ...f, realPerson: false, confirmed: false })} /> {t("av.notReal")}</label>
        <label><input type="radio" name="real" checked={f.realPerson === true} onChange={() => setF({ ...f, realPerson: true })} /> {t("av.real")}</label>
      </fieldset>
      {f.realPerson && (
        <div className="space-y-1 rounded border border-amber-300 bg-amber-50 p-2 dark:bg-amber-950">
          <input aria-label={t("av.subject")} placeholder={t("av.subject")} className={`${field} w-64`} value={f.subject} maxLength={120} onChange={(e) => setF({ ...f, subject: e.target.value })} />
          <label className="flex items-start gap-2"><input type="checkbox" checked={f.confirmed} onChange={(e) => setF({ ...f, confirmed: e.target.checked })} /><span>{statement}</span></label>
          <p className="text-xs text-zinc-600">{t("av.noCeleb")}</p>
        </div>
      )}
      <button className={btn} disabled={!canCreateAvatar(f)} onClick={() => void create()}>{t("av.create")}</button>
    </div>
  );
}

function Workspace({ pid }: { pid: string }) {
  const api = useApi();
  const { t } = useI18n();
  const av = useMemo(() => new AvatarApi(api, pid), [api, pid]);
  const lib = useMemo(() => new AvatarLibraryApi(api), [api]);
  const assets = useMemo(() => new AssetsApi(api, pid), [api, pid]);
  const [st, setSt] = useState<AvatarState>(EMPTY);
  const [avatars, setAvatars] = useState<AvatarInfo[]>([]);
  const [engines, setEngines] = useState<AvatarEngine[]>([]);
  const [files, setFiles] = useState<Asset[]>([]);
  const [imgs, setImgs] = useState<Record<string, string>>({});
  const [url, setUrl] = useState<string>();
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => setSt({ ...EMPTY, ...((await av.state()).state as Partial<AvatarState>) } as AvatarState), [av]);
  const loadLib = useCallback(() => lib.list().then(setAvatars).catch(() => undefined), [lib]);
  const { jobs, running, refresh } = useProjectJobs(pid, () => void load());
  useEffect(() => { void load().catch(() => setMsg(t("common.error"))); void loadLib(); lib.engines().then(setEngines).catch(() => undefined); }, [load, loadLib, lib, t]);
  useEffect(() => {
    let off = false;
    void (async () => {
      const out: Record<string, string> = {};
      for (const a of avatars) out[a.id] = imgs[a.id] ?? (await lib.imageUrl(a.id));
      if (!off) setImgs(out);
    })().catch(() => undefined);
    return () => { off = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [avatars, lib]);
  useEffect(() => {
    setUrl(undefined);
    if (st.result) void assets.fileUrl(st.result.path).then(setUrl).catch(() => undefined);
  }, [st.result, assets]);

  const run = async (fn: () => Promise<unknown>) => {
    setMsg(null);
    try { await fn(); await load(); await refresh(); } catch (e) { setMsg(e instanceof ApiRequestError ? e.message : t("common.error")); }
  };
  const b = st.brief;
  const setBrief = (patch: object) => run(() => av.command("set-brief", { brief: patch }));
  const sel = avatars.find((a) => a.id === b.avatar);
  const locked = engines.filter((e) => !e.implemented);

  return (
    <div className="space-y-4">
      {msg && <p role="alert" className="rounded bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950">{msg}</p>}
      <JobList jobs={jobs} />
      <section className={card}>
        <h2 className="mb-1 text-lg font-medium">{t("av.engine")}</h2>
        <p className="text-sm">✔ <b>{engines.find((e) => e.id === "puppet")?.name}</b> — {engines.find((e) => e.id === "puppet")?.note}</p>
        <ul className="mt-1 space-y-0.5 text-xs text-zinc-500">
          {locked.map((e) => <li key={e.id}>🔒 {e.name}: {e.available ? t("av.notBuilt") : t("av.needGpu")} — {e.note}</li>)}
        </ul>
      </section>

      <section className={card}>
        <h2 className="mb-2 text-lg font-medium">{t("av.library")}</h2>
        <ul className="mb-3 grid gap-2 sm:grid-cols-3">
          {avatars.map((a) => (
            <li key={a.id} className={`rounded-lg border p-2 text-sm ${b.avatar === a.id ? "border-indigo-600" : "border-zinc-200 dark:border-zinc-800"}`}>
              {imgs[a.id] && <img src={imgs[a.id]} alt={a.name} className="h-32 w-full rounded object-contain" />}
              <div className="mt-1 flex items-center gap-1"><b className="flex-1 truncate">{a.name}</b>{a.realPerson && <span title={a.subject ?? ""} className="rounded bg-amber-100 px-1 text-xs text-amber-800">{t("av.realTag")}</span>}</div>
              <div className="mt-1 flex gap-2">
                <button className={btn2} onClick={() => void setBrief({ avatar: a.id })}>{b.avatar === a.id ? t("th.selected") : t("th.select")}</button>
                <button className="text-xs text-red-700" onClick={() => void run(async () => { await lib.remove(a.id); await loadLib(); })}>{t("sub.delete")}</button>
              </div>
            </li>
          ))}
        </ul>
        <details>
          <summary className="cursor-pointer text-sm">{t("av.new")}</summary>
          <div className="mt-2"><AvatarCreator lib={lib} onCreated={() => void loadLib()} statement={t("av.consentStatement")} /></div>
        </details>
        {sel && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
            <span>{t("av.mouth")}:</span>
            {(["x", "y", "w"] as const).map((k) => (
              <label key={k}>{k.toUpperCase()}{" "}
                <input aria-label={`${t("av.mouth")} ${k}`} type="number" step={0.01} min={0.04} max={0.95} className={`${field} w-20`} defaultValue={sel.mouth[k]} key={k + sel.mouth[k]}
                  onBlur={(e) => { const v = Number(e.target.value); if (v !== sel.mouth[k]) void run(async () => { await lib.setMouth(sel.id, { ...sel.mouth, [k]: v }); await loadLib(); }); }} />
              </label>
            ))}
            <span className="text-xs text-zinc-500">{t("av.mouthHelp")}</span>
          </div>
        )}
      </section>

      <section className={card}>
        <h2 className="mb-2 text-lg font-medium">{t("av.audio")}</h2>
        <AssetPanel pid={pid} kinds={["audio", "video", "image"]} onChange={setFiles}
          actions={[{ label: t("av.useAudio"), kinds: ["audio", "video"], run: (a) => setBrief({ audio: a.id }) },
                    { label: t("av.useBg"), kinds: ["image"], run: (a) => setBrief({ background: { kind: "image", asset: a.id } }) }]} />
        {b.audio && <p className="mt-1 text-sm">🎵 {files.find((a) => a.id === b.audio)?.name ?? b.audio}</p>}
      </section>

      <section className={card}>
        <h2 className="mb-2 text-lg font-medium">{t("av.compose")}</h2>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label>{t("ed.aspect")}{" "}
            <select aria-label={t("ed.aspect")} className={field} value={b.aspect} onChange={(e) => void setBrief({ aspect: e.target.value })}>{["16:9", "9:16", "1:1"].map((x) => <option key={x}>{x}</option>)}</select>
          </label>
          <label>{t("av.frame")}{" "}
            <select aria-label={t("av.frame")} className={field} value={b.frame} onChange={(e) => void setBrief({ frame: e.target.value })}>{["none", "rounded", "circle"].map((x) => <option key={x}>{x}</option>)}</select>
          </label>
          <label>{t("av.bg")}{" "}
            <select aria-label={t("av.bg")} className={field} value={b.background.kind === "image" ? "color" : b.background.kind} onChange={(e) => void setBrief({ background: { kind: e.target.value } })}>
              <option value="blur">{t("av.bg.blur")}</option><option value="color">{t("av.bg.color")}</option>
            </select>
          </label>
          {b.background.kind === "color" && <input type="color" aria-label={t("av.bg.color")} value={b.background.color} onChange={(e) => void setBrief({ background: { kind: "color", color: e.target.value } })} />}
          <label>{t("av.subs")}{" "}
            <input aria-label={t("av.subs")} placeholder="vi" className={`${field} w-16`} defaultValue={b.subtitleLang ?? ""} key={b.subtitleLang ?? ""}
              onBlur={(e) => { const v = e.target.value.trim() || null; if (v !== b.subtitleLang) void setBrief({ subtitleLang: v }); }} />
          </label>
        </div>
        <div className="mt-3"><button className={btn} disabled={running || !b.avatar || !b.audio} onClick={() => void run(() => av.render())}>{t("av.render")}</button></div>
        {url && st.result && (
          <div className="mt-3">
            <video controls src={url} aria-label="avatar video" className="max-h-96 rounded bg-black" />
            <a className="text-sm text-indigo-600 underline" href={url} download>{st.result.path.split("/").pop()}</a>
            {st.result.warnings.map((w, i) => <p key={i} className="text-xs text-amber-700">⚠ {w}</p>)}
          </div>
        )}
      </section>
    </div>
  );
}

export function Avatar() {
  const { t } = useI18n();
  const [pid, setPid] = useState("");
  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold">{t("av.title")}</h1>
      <p className="mb-4 text-zinc-600 dark:text-zinc-400">{t("av.subtitle")}</p>
      <ProjectPicker storageKey="av.pid" value={pid} onChange={setPid} />
      {pid && <Workspace key={pid} pid={pid} />}
    </div>
  );
}
