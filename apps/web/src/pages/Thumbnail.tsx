import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiRequestError } from "../api/client";
import { useApi } from "../api/connection";
import { AssetsApi, TemplatesApi, ThumbApi, type Asset, type TemplateInfo, type ThumbState } from "../api/studio";
import { AssetPanel } from "../components/AssetPanel";
import { ProjectPicker } from "../components/ProjectPicker";
import { useI18n } from "../i18n";
import { JobList, useProjectJobs } from "../lib/useJobs";

const btn = "rounded bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-500 disabled:opacity-50";
const btn2 = "rounded border px-2 py-1 text-xs hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50";
const field = "rounded border px-2 py-1 text-sm dark:bg-zinc-800";
const card = "rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900";
const EMPTY: ThumbState = {
  brief: { title: "", subtitle: "", aspect: "16:9", layouts: ["banner", "center", "left", "top"], palettes: ["navy", "sun", "fire", "ink"], count: 4,
    background: { kind: "gradient", asset: null, at: 1, dim: 0.35 }, brand: { asset: null, position: "br", width: 0.14 } },
  variants: [], selected: null,
};

function Workspace({ pid }: { pid: string }) {
  const api = useApi();
  const { t } = useI18n();
  const th = useMemo(() => new ThumbApi(api, pid), [api, pid]);
  const assets = useMemo(() => new AssetsApi(api, pid), [api, pid]);
  const tpl = useMemo(() => new TemplatesApi(api), [api]);
  const [st, setSt] = useState<ThumbState>(EMPTY);
  const [list, setList] = useState<Asset[]>([]);
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [subtitle, setSubtitle] = useState("");
  const [urls, setUrls] = useState<Record<string, string>>({});

  const load = useCallback(async () => setSt({ ...EMPTY, ...((await th.state()).state as Partial<ThumbState>) } as ThumbState), [th]);
  const { jobs, running, refresh } = useProjectJobs(pid, () => void load());
  useEffect(() => { void load().catch(() => setMsg(t("common.error"))); }, [load, t]);
  useEffect(() => { tpl.list("thumbnail").then(setTemplates).catch(() => undefined); }, [tpl]);
  useEffect(() => setTitle((c) => c || st.brief.title), [st.brief.title]);
  useEffect(() => setSubtitle((c) => c || st.brief.subtitle), [st.brief.subtitle]);
  useEffect(() => {
    let off = false;
    void (async () => {
      const out: Record<string, string> = {};
      for (const v of st.variants) out[v.id] = await assets.fileUrl(v.file);
      if (!off) setUrls(out);
    })().catch(() => undefined);
    return () => { off = true; };
  }, [st.variants, assets]);

  const run = async (fn: () => Promise<unknown>) => {
    setMsg(null);
    try { await fn(); await load(); await refresh(); } catch (e) { setMsg(e instanceof ApiRequestError ? e.message : t("common.error")); }
  };
  const b = st.brief;
  const setBrief = (patch: object) => run(() => th.command("set-brief", { brief: patch }));
  const images = list.filter((a) => a.kind !== "audio");

  return (
    <div className="space-y-4">
      {msg && <p role="alert" className="rounded bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950">{msg}</p>}
      <JobList jobs={jobs} />
      <section className={card}>
        <h2 className="mb-2 text-lg font-medium">{t("th.brief")}</h2>
        <div className="grid gap-2 sm:grid-cols-2">
          <input aria-label={t("th.titleField")} placeholder={t("th.titleField")} className={field} value={title} maxLength={90} onChange={(e) => setTitle(e.target.value)}
            onBlur={() => title !== b.title && void setBrief({ title })} />
          <input aria-label={t("th.subtitleField")} placeholder={t("th.subtitleField")} className={field} value={subtitle} maxLength={140} onChange={(e) => setSubtitle(e.target.value)}
            onBlur={() => subtitle !== b.subtitle && void setBrief({ subtitle })} />
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
          <label>{t("ed.aspect")}{" "}
            <select aria-label={t("ed.aspect")} className={field} value={b.aspect} onChange={(e) => void setBrief({ aspect: e.target.value })}>{["16:9", "9:16", "1:1"].map((x) => <option key={x}>{x}</option>)}</select>
          </label>
          <label>{t("th.count")}{" "}
            <input aria-label={t("th.count")} type="number" min={1} max={8} className={`${field} w-16`} value={b.count} onChange={(e) => void setBrief({ count: Number(e.target.value) })} />
          </label>
          <label>{t("th.background")}{" "}
            <select aria-label={t("th.background")} className={field} value={b.background.kind === "gradient" ? "" : b.background.asset ?? ""}
              onChange={(e) => {
                const a = images.find((x) => x.id === e.target.value);
                void setBrief({ background: a ? { kind: a.kind === "video" ? "frame" : "asset", asset: a.id } : { kind: "gradient", asset: null } });
              }}>
              <option value="">{t("th.gradient")}</option>
              {images.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </label>
          <label>{t("th.logo")}{" "}
            <select aria-label={t("th.logo")} className={field} value={b.brand.asset ?? ""} onChange={(e) => void setBrief({ brand: { asset: e.target.value || null } })}>
              <option value="">—</option>
              {images.filter((a) => a.kind === "image").map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </label>
          <label>{t("tpl.apply")}{" "}
            <select aria-label={t("tpl.apply")} className={field} value="" onChange={(e) => { const x = templates.find((y) => y.id === e.target.value); if (x) void run(() => th.command("apply-template", { template: x })); }}>
              <option value="">—</option>
              {templates.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          </label>
        </div>
        <div className="mt-3">
          <button className={btn} disabled={running || !title.trim()}
            onClick={() => void run(async () => { await th.command("set-brief", { brief: { title, subtitle } }); await th.render(); })}>{t("th.render")}</button>
        </div>
      </section>

      <section className={card}>
        <h2 className="mb-2 text-lg font-medium">{t("asset.title")}</h2>
        <AssetPanel pid={pid} kinds={["image", "video"]} actions={[]} onChange={setList} />
      </section>

      <section className={card}>
        <h2 className="mb-2 text-lg font-medium">{t("th.variants")}</h2>
        {st.variants.length === 0 ? <p className="text-sm text-zinc-500">{t("th.none")}</p> : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {st.variants.map((v) => (
              <li key={v.id} className={`rounded-lg border p-2 ${st.selected === v.id ? "border-indigo-600" : "border-zinc-200 dark:border-zinc-800"}`}>
                {urls[v.id] && <img src={urls[v.id]} alt={`${t("th.variant")} ${v.layout}/${v.palette}`} className="w-full rounded" />}
                <div className="mt-1 flex items-center gap-2 text-xs text-zinc-500">
                  <span>{v.layout} · {v.palette} · {v.width}×{v.height}</span>
                  <button className={btn2} onClick={() => void run(() => th.command("select", { id: v.id }))}>{st.selected === v.id ? t("th.selected") : t("th.select")}</button>
                  {urls[v.id] && <a className="text-indigo-600 underline" href={urls[v.id]} download>PNG</a>}
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-zinc-500">{t("th.aiNote")}</p>
      </section>
    </div>
  );
}

export function Thumbnail() {
  const { t } = useI18n();
  const [pid, setPid] = useState("");
  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold">{t("th.title")}</h1>
      <p className="mb-4 text-zinc-600 dark:text-zinc-400">{t("th.subtitle")}</p>
      <ProjectPicker storageKey="th.pid" value={pid} onChange={setPid} />
      {pid && <Workspace key={pid} pid={pid} />}
    </div>
  );
}
