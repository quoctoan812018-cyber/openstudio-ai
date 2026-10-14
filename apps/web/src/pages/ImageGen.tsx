import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiRequestError } from "../api/client";
import { useApi } from "../api/connection";
import { AssetsApi, ImageApi, type Asset, type ImageState, type ImageStatus } from "../api/studio";
import { AssetPanel } from "../components/AssetPanel";
import { ProjectPicker } from "../components/ProjectPicker";
import { useI18n } from "../i18n";
import { JobList, useProjectJobs } from "../lib/useJobs";

const btn = "rounded bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-500 disabled:opacity-50";
const btn2 = "rounded border px-2 py-1 text-xs hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50";
const field = "rounded border px-2 py-1 text-sm dark:bg-zinc-800";
const card = "rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900";
const EMPTY: ImageState = { brief: { prompt: "", aspect: "1:1", quality: "draft", count: 1, seed: null, refAsset: null, translate: true, language: "vi" }, results: [], last: null };
/** Cạnh dài theo chất lượng; thời gian ước lượng ~ bình phương diện tích (đã đo: 512 px ≈ 4 phút/ảnh trên CPU của máy phát triển). */
const LONG = { draft: 512, standard: 768, high: 1024 } as const;
export const estimateMinutes = (q: keyof typeof LONG, count: number, minutesAt512 = 4) => Math.round(minutesAt512 * (LONG[q] / 512) ** 2 * count);

function Workspace({ pid }: { pid: string }) {
  const api = useApi();
  const { t } = useI18n();
  const im = useMemo(() => new ImageApi(api, pid), [api, pid]);
  const assets = useMemo(() => new AssetsApi(api, pid), [api, pid]);
  const [st, setSt] = useState<ImageState>(EMPTY);
  const [status, setStatus] = useState<ImageStatus | null>(null);
  const [list, setList] = useState<Asset[]>([]);
  const [prompt, setPrompt] = useState("");
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<{ text: string; modelId?: string } | null>(null);

  const load = useCallback(async () => setSt({ ...EMPTY, ...((await im.state()).state as Partial<ImageState>) } as ImageState), [im]);
  const { jobs, running, refresh } = useProjectJobs(pid, () => void load());
  useEffect(() => { void load().catch(() => setMsg({ text: t("common.error") })); im.status().then(setStatus).catch(() => undefined); }, [load, im, t]);
  useEffect(() => setPrompt((c) => c || st.brief.prompt), [st.brief.prompt]);
  useEffect(() => {
    let off = false;
    void (async () => {
      const out: Record<string, string> = {};
      for (const r of st.results) out[r.id] = await assets.fileUrl(r.file);
      if (!off) setUrls(out);
    })().catch(() => undefined);
    return () => { off = true; };
  }, [st.results, assets]);

  const run = async (fn: () => Promise<unknown>) => {
    setMsg(null);
    try { await fn(); await load(); await refresh(); } catch (e) {
      if (e instanceof ApiRequestError) setMsg({ text: e.message, modelId: e.code === "MODEL_MISSING" ? String(e.details?.modelId) : undefined });
      else setMsg({ text: t("common.error") });
    }
  };
  const b = st.brief;
  const setBrief = (patch: object) => run(() => im.command("set-brief", { brief: patch }));
  const missing = status && (!status.engineInstalled || !status.modelInstalled);

  return (
    <div className="space-y-4">
      {msg && (
        <p role="alert" className="rounded bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950">
          {msg.text}{" "}{msg.modelId && <button className="underline" onClick={() => void run(() => api.downloadModel(msg.modelId!))}>{t("sub.downloadModel")} ({msg.modelId})</button>}
        </p>
      )}
      <JobList jobs={jobs} />
      {missing && status && (
        <section className={`${card} border-amber-300`}>
          <p className="text-sm">{t("img.needModels")}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {!status.engineInstalled && status.engine && <button className={btn2} onClick={() => void run(() => api.downloadModel(status.engine!))}>{t("img.dlEngine")} ({status.engine})</button>}
            {!status.modelInstalled && <button className={btn2} onClick={() => void run(() => api.downloadModel(status.model))}>{t("img.dlModel")} (~5 GB)</button>}
          </div>
        </section>
      )}
      <section className={card}>
        <h2 className="mb-2 text-lg font-medium">{t("img.brief")}</h2>
        <textarea aria-label={t("img.prompt")} placeholder={t("img.prompt")} rows={3} className={`${field} w-full`} value={prompt} maxLength={1500}
          onChange={(e) => setPrompt(e.target.value)} onBlur={() => prompt !== b.prompt && void setBrief({ prompt })} />
        <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
          <label>{t("ed.aspect")}{" "}
            <select aria-label={t("ed.aspect")} className={field} value={b.aspect} onChange={(e) => void setBrief({ aspect: e.target.value })}>{["1:1", "16:9", "9:16", "4:3", "3:4"].map((x) => <option key={x}>{x}</option>)}</select>
          </label>
          <label>{t("img.quality")}{" "}
            <select aria-label={t("img.quality")} className={field} value={b.quality} onChange={(e) => void setBrief({ quality: e.target.value })}>
              <option value="draft">{t("img.q.draft")} (512)</option><option value="standard">{t("img.q.standard")} (768)</option><option value="high">{t("img.q.high")} (1024)</option>
            </select>
          </label>
          <label>{t("th.count")}{" "}
            <input aria-label={t("th.count")} type="number" min={1} max={4} className={`${field} w-16`} value={b.count} onChange={(e) => void setBrief({ count: Number(e.target.value) })} />
          </label>
          <label>Seed{" "}
            <input aria-label="seed" type="number" min={0} placeholder="auto" className={`${field} w-28`} defaultValue={b.seed ?? ""} key={String(b.seed)}
              onBlur={(e) => { const v = e.target.value === "" ? null : Number(e.target.value); if (v !== b.seed) void setBrief({ seed: v }); }} />
          </label>
          <label className="flex items-center gap-1"><input type="checkbox" checked={b.translate} onChange={(e) => void setBrief({ translate: e.target.checked })} />{t("img.translate")}</label>
        </div>
        <p className="mt-2 text-xs text-zinc-500">{t("img.estimate").replace("{min}", String(estimateMinutes(b.quality, b.count)))}</p>
        <div className="mt-3 flex items-center gap-3">
          <button className={btn} disabled={running || !prompt.trim() || !!missing}
            onClick={() => void run(async () => { if (prompt !== b.prompt) await im.command("set-brief", { brief: { prompt } }); await im.generate(); })}>{t("img.generate")}</button>
          {status && <span className="text-xs text-zinc-500">{status.note}</span>}
        </div>
      </section>

      <section className={card}>
        <h2 className="mb-1 text-lg font-medium">{t("img.ref")}</h2>
        <p className="mb-2 text-xs text-zinc-500">{t("img.refHelp")}</p>
        <AssetPanel pid={pid} kinds={["image"]} onChange={setList} actions={[{ label: t("img.useRef"), run: (a) => setBrief({ refAsset: a.id }) }]} />
        {b.refAsset && <p className="mt-1 text-sm">🖼 {list.find((a) => a.id === b.refAsset)?.name ?? b.refAsset} <button className="ml-2 text-xs underline" onClick={() => void setBrief({ refAsset: null })}>{t("sub.delete")}</button></p>}
      </section>

      <section className={card}>
        <h2 className="mb-2 text-lg font-medium">{t("img.results")}</h2>
        {st.last?.warnings.map((w, i) => <p key={i} className="text-xs text-amber-700">⚠ {w}</p>)}
        {st.last?.englishPrompt && <p className="mb-2 text-xs text-zinc-500">{t("img.finalPrompt")}: {st.last.englishPrompt}</p>}
        {st.results.length === 0 ? <p className="text-sm text-zinc-500">{t("img.none")}</p> : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {st.results.map((r) => (
              <li key={r.id} className="rounded-lg border border-zinc-200 p-2 dark:border-zinc-800">
                {urls[r.id] && <img src={urls[r.id]} alt={`${t("img.result")} ${r.seed}`} className="w-full rounded" />}
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-zinc-500">
                  <span>{r.width}×{r.height} · seed {r.seed} · {Math.round(r.seconds)}s</span>
                  {urls[r.id] && <a className="text-indigo-600 underline" href={urls[r.id]} download>PNG</a>}
                  <button className="text-red-700" onClick={() => void run(() => im.command("remove-result", { id: r.id }))}>{t("sub.delete")}</button>
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-zinc-500">{t("img.aiLabel")}</p>
      </section>
    </div>
  );
}

export function ImageGen() {
  const { t } = useI18n();
  const [pid, setPid] = useState("");
  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold">{t("img.title")}</h1>
      <p className="mb-4 text-zinc-600 dark:text-zinc-400">{t("img.subtitle")}</p>
      <ProjectPicker storageKey="img.pid" value={pid} onChange={setPid} />
      {pid && <Workspace key={pid} pid={pid} />}
    </div>
  );
}
