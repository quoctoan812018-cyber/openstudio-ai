import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiRequestError } from "../api/client";
import { useApi } from "../api/connection";
import { CampaignApi, type CampaignCatalog, type CampaignPost, type CampaignState } from "../api/studio";
import { ProjectPicker } from "../components/ProjectPicker";
import { useI18n } from "../i18n";
import { JobList, useProjectJobs } from "../lib/useJobs";

const btn = "rounded bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-500 disabled:opacity-50";
const btn2 = "rounded border px-3 py-1.5 text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50";
const field = "rounded border px-2 py-1 text-sm dark:bg-zinc-800";
const card = "rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900";
const EMPTY: CampaignState = {
  brief: { goal: "", product: "", facts: "", markets: ["us"], platforms: ["tiktok"], days: 7, startDate: null, language: "vi", tone: "thân thiện, dễ hiểu", priceVnd: null, fx: {} },
  plan: null, posts: [], export: null,
};
const STATUS_COLOR: Record<string, string> = {
  planned: "bg-zinc-200 text-zinc-700", ready: "bg-sky-100 text-sky-800", approved: "bg-emerald-100 text-emerald-800",
  posted: "bg-indigo-100 text-indigo-800", failed: "bg-red-100 text-red-800",
};

export function PostRow({ post, marketName, platformName, thumbUrl, onPatch }: {
  post: CampaignPost; marketName: string; platformName: string; thumbUrl?: string; onPatch: (patch: Record<string, unknown>) => void;
}) {
  const { t } = useI18n();
  const [caption, setCaption] = useState(post.caption);
  useEffect(() => setCaption(post.caption), [post.caption]);
  const hasAssets = post.status !== "planned" && post.status !== "failed";
  return (
    <li className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <code>{post.date} {post.time}</code>
        <span>{marketName}</span>
        <span className="text-zinc-500">· {platformName} · {post.format}</span>
        <span className={`ml-auto rounded px-2 py-0.5 text-xs ${STATUS_COLOR[post.status]}`}>{t(`camp.status.${post.status}`)}</span>
      </div>
      <p className="mt-1 font-medium">{post.title}</p>
      {post.note && <p className="text-xs text-red-700">{post.note}</p>}
      {hasAssets && (
        <div className="mt-2 flex gap-3">
          {thumbUrl && <img src={thumbUrl} alt={`${t("camp.thumb")} ${post.id}`} className="h-24 rounded object-cover" />}
          <div className="flex-1 space-y-1">
            <textarea aria-label={`${t("camp.caption")} ${post.id}`} rows={3} className={`${field} w-full`} value={caption}
              onChange={(e) => setCaption(e.target.value)} onBlur={() => caption !== post.caption && onPatch({ caption })} />
            <p className="text-xs text-zinc-500">{post.hashtags.map((h) => `#${h}`).join(" ")}</p>
          </div>
        </div>
      )}
      <div className="mt-2 flex gap-2 text-sm">
        {post.status === "ready" && <button className={btn2} onClick={() => onPatch({ status: "approved" })}>{t("camp.approve")}</button>}
        {post.status === "approved" && <button className={btn2} onClick={() => onPatch({ status: "posted" })}>{t("camp.markPosted")}</button>}
      </div>
    </li>
  );
}

function Workspace({ pid }: { pid: string }) {
  const api = useApi();
  const { t } = useI18n();
  const camp = useMemo(() => new CampaignApi(api, pid), [api, pid]);
  const [st, setSt] = useState<CampaignState>(EMPTY);
  const [cat, setCat] = useState<CampaignCatalog | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [goal, setGoal] = useState("");
  const [thumbs, setThumbs] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    const s = (await camp.state()).state as Partial<CampaignState>;
    setSt({ ...EMPTY, ...s } as CampaignState);
  }, [camp]);
  const { jobs, running, refresh } = useProjectJobs(pid, () => void load());
  useEffect(() => { void load().catch(() => setMsg(t("common.error"))); }, [load, t]);
  useEffect(() => { camp.catalog().then(setCat).catch(() => undefined); }, [camp]);
  useEffect(() => setGoal((cur) => cur || st.brief.goal), [st.brief.goal]);
  useEffect(() => {
    let off = false;
    void (async () => {
      const out: Record<string, string> = {};
      for (const p of st.posts) if (p.thumbnail) out[p.id] = await camp.fileUrl(p.thumbnail);
      if (!off) setThumbs(out);
    })().catch(() => undefined);
    return () => { off = true; };
  }, [st.posts, camp]);

  const run = async (fn: () => Promise<unknown>) => {
    setMsg(null);
    try { await fn(); await load(); await refresh(); } catch (e) { setMsg(e instanceof ApiRequestError ? e.message : t("common.error")); }
  };
  const b = st.brief;
  const setBrief = (patch: Partial<CampaignState["brief"]>) => run(() => camp.command("set-brief", { brief: patch }));
  const toggle = (key: "markets" | "platforms", id: string, max: number) => {
    const cur = b[key];
    const next = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id].slice(-max);
    if (next.length) void setBrief({ [key]: next });
  };
  const currencies = [...new Set(b.markets.map((m) => cat?.markets[m]?.currency).filter((c): c is string => !!c && c !== "VND"))];
  const counts = st.posts.reduce<Record<string, number>>((a, p) => ({ ...a, [p.status]: (a[p.status] ?? 0) + 1 }), {});
  const openFile = (path: string) => void camp.fileUrl(path).then((u) => window.open(u));

  return (
    <div className="space-y-4">
      {msg && <p role="alert" className="rounded bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950">{msg}</p>}
      <JobList jobs={jobs} />
      <section className={card}>
        <h2 className="mb-2 text-lg font-medium">{t("camp.brief")}</h2>
        <textarea aria-label={t("camp.goal")} placeholder={t("camp.goal")} rows={2} className={`${field} w-full`} value={goal}
          onChange={(e) => setGoal(e.target.value)} onBlur={() => goal !== b.goal && void setBrief({ goal })} />
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <input aria-label={t("camp.product")} placeholder={t("camp.product")} className={field} defaultValue={b.product} key={"p" + b.product}
            onBlur={(e) => e.target.value !== b.product && void setBrief({ product: e.target.value })} />
          <input aria-label={t("camp.facts")} placeholder={t("camp.facts")} className={field} defaultValue={b.facts} key={"f" + b.facts}
            onBlur={(e) => e.target.value !== b.facts && void setBrief({ facts: e.target.value })} />
        </div>
        <fieldset className="mt-3 text-sm">
          <legend className="font-medium">{t("camp.markets")}</legend>
          <div className="flex flex-wrap gap-3">
            {Object.entries(cat?.markets ?? {}).map(([id, m]) => (
              <label key={id} className="flex items-center gap-1">
                <input type="checkbox" checked={b.markets.includes(id)} onChange={() => toggle("markets", id, 8)} />{m.name} <span className="text-xs text-zinc-500">({m.lang})</span>
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset className="mt-2 text-sm">
          <legend className="font-medium">{t("camp.platforms")}</legend>
          <div className="flex flex-wrap gap-3">
            {Object.entries(cat?.platforms ?? {}).map(([id, p]) => (
              <label key={id} className="flex items-center gap-1"><input type="checkbox" checked={b.platforms.includes(id)} onChange={() => toggle("platforms", id, 3)} />{p.name}</label>
            ))}
          </div>
        </fieldset>
        <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
          <label>{t("camp.days")}{" "}
            <select className={field} value={b.days} onChange={(e) => void setBrief({ days: Number(e.target.value) as 7 | 14 | 30 })}>
              {[7, 14, 30].map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>
          <label>{t("camp.start")}{" "}
            <input type="date" className={field} aria-label={t("camp.start")} value={b.startDate ?? ""} onChange={(e) => void setBrief({ startDate: e.target.value || null })} />
          </label>
          <label>{t("camp.price")}{" "}
            <input type="number" min={0} className={`${field} w-32`} aria-label={t("camp.price")} defaultValue={b.priceVnd ?? ""} key={"v" + b.priceVnd}
              onBlur={(e) => { const v = e.target.value ? Number(e.target.value) : null; if (v !== b.priceVnd) void setBrief({ priceVnd: v }); }} />
          </label>
        </div>
        {b.priceVnd && currencies.length > 0 && (
          <div className="mt-2 text-sm">
            <p className="text-xs text-zinc-500">{t("camp.fxHelp")}</p>
            <div className="flex flex-wrap gap-3">
              {currencies.map((c) => (
                <label key={c}>1 {c} ={" "}
                  <input type="number" min={0} className={`${field} w-24`} aria-label={`${t("camp.fx")} ${c}`} defaultValue={b.fx[c] ?? ""} key={c + (b.fx[c] ?? "")}
                    onBlur={(e) => { const v = Number(e.target.value); const fx = { ...b.fx }; if (v > 0) fx[c] = v; else delete fx[c]; void setBrief({ fx }); }} /> VND
                </label>
              ))}
            </div>
          </div>
        )}
        <div className="mt-3">
          <button className={btn} disabled={running || !goal.trim()}
            onClick={() => void run(async () => { if (goal !== b.goal) await camp.command("set-brief", { brief: { goal } }); await camp.plan(); })}>{t("camp.plan")}</button>
        </div>
      </section>

      {st.plan && (
        <section className={card}>
          <h2 className="mb-1 text-lg font-medium">{t("camp.planTitle")}</h2>
          <p className="text-sm text-zinc-600">{st.plan.summary}</p>
          {st.plan.warnings.length > 0 && <ul className="mt-2 list-disc pl-5 text-sm text-amber-700">{st.plan.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
          <p className="mt-2 text-xs text-zinc-500">{Object.entries(counts).map(([k, n]) => `${t(`camp.status.${k}`)}: ${n}`).join(" · ")}</p>
          <div className="mt-2 flex gap-2">
            <button className={btn} disabled={running} onClick={() => void run(() => camp.assets(false))}>{t("camp.assets")}</button>
            <button className={btn2} disabled={running} onClick={() => void run(() => camp.assets(true))}>{t("camp.assetsAgain")}</button>
            <button className={btn2} disabled={running || !st.posts.some((p) => p.status !== "planned" && p.status !== "failed")} onClick={() => void run(() => camp.exportPack())}>{t("camp.export")}</button>
          </div>
          <p className="mt-2 text-xs text-zinc-500">{t("camp.reviewNote")}</p>
        </section>
      )}

      {st.posts.length > 0 && (
        <section className={card}>
          <h2 className="mb-2 text-lg font-medium">{t("camp.tracking")}</h2>
          <ul className="space-y-2">
            {st.posts.map((p) => (
              <PostRow key={p.id} post={p} marketName={cat?.markets[p.market]?.name ?? p.market} platformName={cat?.platforms[p.platform]?.name ?? p.platform}
                thumbUrl={thumbs[p.id]} onPatch={(patch) => void run(() => camp.command("set-post", { id: p.id, ...patch }))} />
            ))}
          </ul>
        </section>
      )}

      {st.export && (
        <section className={card}>
          <h2 className="mb-1 text-lg font-medium">{t("camp.exported")}</h2>
          <p className="text-sm">{st.export.posts} {t("camp.posts")} · {st.export.files} file</p>
          <p className="break-all text-xs text-zinc-500">{st.export.folder}</p>
          <p className="mt-1 flex gap-3 text-sm">
            <button className="text-indigo-600 underline" onClick={() => openFile(st.export!.zip)}>zip</button>
            <button className="text-indigo-600 underline" onClick={() => openFile(st.export!.csv)}>schedule.csv</button>
          </p>
        </section>
      )}
    </div>
  );
}

export function Campaign() {
  const { t } = useI18n();
  const [pid, setPid] = useState("");
  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold">{t("camp.title")}</h1>
      <p className="mb-4 text-zinc-600 dark:text-zinc-400">{t("camp.subtitle")}</p>
      <ProjectPicker storageKey="camp.pid" value={pid} onChange={setPid} />
      {pid && <Workspace key={pid} pid={pid} />}
    </div>
  );
}
