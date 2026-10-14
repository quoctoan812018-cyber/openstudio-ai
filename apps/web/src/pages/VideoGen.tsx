import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiRequestError } from "../api/client";
import { useApi } from "../api/connection";
import { AssetsApi, VideoApi, type Asset, type VideoEngine, type VideoState } from "../api/studio";
import { AssetPanel } from "../components/AssetPanel";
import { ProjectPicker } from "../components/ProjectPicker";
import { useI18n } from "../i18n";
import { JobList, useProjectJobs } from "../lib/useJobs";

const btn = "rounded bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-500 disabled:opacity-50";
const field = "rounded border px-2 py-1 text-sm dark:bg-zinc-800";
const card = "rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900";
const PRESETS = ["zoom-in", "zoom-out", "pan-left", "pan-right", "pan-up", "pan-down"];
const EMPTY: VideoState = { brief: { asset: null, duration: 6, preset: "zoom-in", aspect: "16:9", quality: 720, fps: 25, audio: null, strength: 0.25 }, result: null };

function Workspace({ pid }: { pid: string }) {
  const api = useApi();
  const { t } = useI18n();
  const vd = useMemo(() => new VideoApi(api, pid), [api, pid]);
  const assets = useMemo(() => new AssetsApi(api, pid), [api, pid]);
  const [st, setSt] = useState<VideoState>(EMPTY);
  const [engines, setEngines] = useState<VideoEngine[]>([]);
  const [list, setList] = useState<Asset[]>([]);
  const [url, setUrl] = useState<string>();
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => setSt({ ...EMPTY, ...((await vd.state()).state as Partial<VideoState>) } as VideoState), [vd]);
  const { jobs, running, refresh } = useProjectJobs(pid, () => void load());
  useEffect(() => { void load().catch(() => setMsg(t("common.error"))); vd.engines().then(setEngines).catch(() => undefined); }, [load, vd, t]);
  useEffect(() => {
    setUrl(undefined);
    if (st.result) void assets.fileUrl(st.result.path).then(setUrl).catch(() => undefined);
  }, [st.result, assets]);

  const run = async (fn: () => Promise<unknown>) => {
    setMsg(null);
    try { await fn(); await load(); await refresh(); } catch (e) { setMsg(e instanceof ApiRequestError ? e.message : t("common.error")); }
  };
  const b = st.brief;
  const setBrief = (patch: object) => run(() => vd.command("set-brief", { brief: patch }));
  const name = (id: string | null) => list.find((a) => a.id === id)?.name ?? id;

  return (
    <div className="space-y-4">
      {msg && <p role="alert" className="rounded bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950">{msg}</p>}
      <JobList jobs={jobs} />
      <section className={card}>
        <p className="text-sm">✔ <b>{engines.find((e) => e.id === "motion")?.name}</b> — {t("vid.notAi")}</p>
        <ul className="mt-1 space-y-0.5 text-xs text-zinc-500">
          {engines.filter((e) => !e.implemented).map((e) => <li key={e.id}>🔒 {e.name}: {e.note}</li>)}
        </ul>
      </section>
      <section className={card}>
        <h2 className="mb-2 text-lg font-medium">{t("vid.source")}</h2>
        <AssetPanel pid={pid} kinds={["image", "audio"]} onChange={setList}
          actions={[{ label: t("vid.useImage"), kinds: ["image"], run: (a) => setBrief({ asset: a.id }) }, { label: t("av.useAudio"), kinds: ["audio"], run: (a) => setBrief({ audio: a.id }) }]} />
        <p className="mt-1 text-sm">🖼 {b.asset ? name(b.asset) : t("vid.noImage")}{b.audio && <> · 🎵 {name(b.audio)} <button className="text-xs underline" onClick={() => void setBrief({ audio: null })}>{t("sub.delete")}</button></>}</p>
      </section>
      <section className={card}>
        <h2 className="mb-2 text-lg font-medium">{t("vid.motion")}</h2>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label>{t("vid.preset")}{" "}
            <select aria-label={t("vid.preset")} className={field} value={b.preset} onChange={(e) => void setBrief({ preset: e.target.value })}>{PRESETS.map((p) => <option key={p}>{p}</option>)}</select>
          </label>
          <label>{t("ed.duration")}{" "}
            <input aria-label={t("ed.duration")} type="number" min={1} max={60} step={1} className={`${field} w-20`} defaultValue={b.duration} key={b.duration}
              onBlur={(e) => { const v = Number(e.target.value); if (v !== b.duration) void setBrief({ duration: v }); }} /> s
          </label>
          <label>{t("ed.aspect")}{" "}
            <select aria-label={t("ed.aspect")} className={field} value={b.aspect} onChange={(e) => void setBrief({ aspect: e.target.value })}>{["16:9", "9:16", "1:1"].map((x) => <option key={x}>{x}</option>)}</select>
          </label>
          <label>{t("ed.quality")}{" "}
            <select aria-label={t("ed.quality")} className={field} value={b.quality} onChange={(e) => void setBrief({ quality: Number(e.target.value) })}>{[480, 720, 1080].map((x) => <option key={x} value={x}>{x}p</option>)}</select>
          </label>
        </div>
        <div className="mt-3"><button className={btn} disabled={running || !b.asset} onClick={() => void run(() => vd.render())}>{t("vid.render")}</button></div>
        {url && st.result && (
          <div className="mt-3">
            <video controls src={url} aria-label="video" className="max-h-96 rounded bg-black" />
            <a className="text-sm text-indigo-600 underline" href={url} download>{st.result.path.split("/").pop()}</a>
          </div>
        )}
      </section>
    </div>
  );
}

export function VideoGen() {
  const { t } = useI18n();
  const [pid, setPid] = useState("");
  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold">{t("vid.title")}</h1>
      <p className="mb-4 text-zinc-600 dark:text-zinc-400">{t("vid.subtitle")}</p>
      <ProjectPicker storageKey="vid.pid" value={pid} onChange={setPid} />
      {pid && <Workspace key={pid} pid={pid} />}
    </div>
  );
}
