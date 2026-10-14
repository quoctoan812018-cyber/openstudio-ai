import { useCallback, useEffect, useMemo, useState } from "react";
import { AgentApi, type Schedule, type SkillInfo } from "../api/agent";
import { ApiRequestError } from "../api/client";
import { useApi } from "../api/connection";
import { ProjectPicker } from "../components/ProjectPicker";
import { useI18n } from "../i18n";

const btn = "rounded bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-500 disabled:opacity-50";
const btn2 = "rounded border px-3 py-1.5 text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50";
const field = "rounded border px-2 py-1 text-sm dark:bg-zinc-800";
const card = "rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900";
export const CRON_PRESETS: { id: string; cron: string }[] = [
  { id: "daily8", cron: "0 8 * * *" }, { id: "weekly", cron: "0 9 * * 1" }, { id: "hourly", cron: "0 * * * *" }, { id: "custom", cron: "" },
];

export function SkillRow({ s, selected, onSelect, onToggle }: { s: SkillInfo; selected: boolean; onSelect: () => void; onToggle: (v: boolean) => void }) {
  const { t } = useI18n();
  return (
    <li className={`flex items-center gap-2 rounded border p-2 text-sm ${selected ? "border-indigo-400" : "border-zinc-200 dark:border-zinc-800"}`}>
      <input type="checkbox" aria-label={`${t("sk.enabled")} ${s.name}`} checked={s.enabled} onChange={(e) => onToggle(e.target.checked)} />
      <button className="flex-1 text-left" onClick={onSelect}>
        <strong>{s.name}</strong>{" "}
        <span className={`rounded-full px-2 py-0.5 text-xs ${s.source === "builtin" ? "bg-zinc-200 text-zinc-700" : "bg-violet-100 text-violet-800"}`}>{t(`sk.source.${s.source}`)}</span>
        {s.warnings.length > 0 && <span className="ml-1 text-xs text-amber-700">⚠</span>}
        <span className="block text-xs text-zinc-500">{s.description}</span>
      </button>
    </li>
  );
}

export function fmtWhen(ts: number | null): string {
  return ts ? new Date(ts * 1000).toLocaleString() : "—";
}

function Schedules({ pid, skills }: { pid: string; skills: SkillInfo[] }) {
  const api = useApi();
  const { t } = useI18n();
  const agent = useMemo(() => new AgentApi(api), [api]);
  const [list, setList] = useState<Schedule[]>([]);
  const [form, setForm] = useState({ message: "", skill: "", preset: "daily8", cron: "0 8 * * *", autoApprove: false });
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => agent.schedules(pid).then(setList), [agent, pid]);
  useEffect(() => { void load().catch(() => undefined); }, [load]);
  const run = async (fn: () => Promise<unknown>) => {
    setErr(null);
    try { await fn(); await load(); } catch (e) { setErr(e instanceof ApiRequestError ? e.message : t("common.error")); }
  };
  return (
    <section className={card}>
      <h2 className="mb-2 text-lg font-medium">{t("sk.schedules")}</h2>
      <p className="mb-2 text-xs text-zinc-500">{t("sk.scheduleHelp")}</p>
      {err && <p role="alert" className="mb-2 text-sm text-red-700">{err}</p>}
      <ul className="mb-3 space-y-1 text-sm">
        {list.map((s) => (
          <li key={s.id} className="flex flex-wrap items-center gap-2 rounded border border-zinc-200 p-2 dark:border-zinc-800">
            <input type="checkbox" aria-label={`${t("sk.enabled")} ${s.id}`} checked={s.enabled} onChange={(e) => void run(() => agent.patchSchedule(s.id, { enabled: e.target.checked }))} />
            <code className="text-xs">{s.cron}</code>
            <span className="flex-1">{s.message}{s.skill ? ` · ${s.skill}` : ""}</span>
            <span className="text-xs text-zinc-500">{t("sk.next")}: {fmtWhen(s.nextRunAt)}</span>
            <button className={btn2} onClick={() => void run(() => agent.runNow(s.id))}>{t("sk.runNow")}</button>
            <button className="text-red-700 underline" onClick={() => void run(() => agent.deleteSchedule(s.id))}>{t("settings.models.delete")}</button>
          </li>
        ))}
        {list.length === 0 && <li className="text-zinc-500">{t("sk.noSchedules")}</li>}
      </ul>
      <div className="space-y-2 text-sm">
        <textarea aria-label={t("sk.scheduleMessage")} rows={2} className={`${field} w-full`} placeholder={t("sk.scheduleMessage")} value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} />
        <div className="flex flex-wrap items-center gap-3">
          <select aria-label={t("ag.skill")} className={field} value={form.skill} onChange={(e) => setForm({ ...form, skill: e.target.value })}>
            <option value="">{t("ag.skillAuto")}</option>
            {skills.filter((s) => s.enabled).map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
          </select>
          <select aria-label={t("sk.when")} className={field} value={form.preset}
            onChange={(e) => { const p = CRON_PRESETS.find((x) => x.id === e.target.value)!; setForm({ ...form, preset: p.id, cron: p.cron || form.cron }); }}>
            {CRON_PRESETS.map((p) => <option key={p.id} value={p.id}>{t(`sk.cron.${p.id}`)}</option>)}
          </select>
          <input aria-label="cron" className={`${field} w-36 font-mono`} value={form.cron} disabled={form.preset !== "custom"} onChange={(e) => setForm({ ...form, cron: e.target.value })} />
          <label className="flex items-center gap-1"><input type="checkbox" checked={form.autoApprove} onChange={(e) => setForm({ ...form, autoApprove: e.target.checked })} />{t("ag.autoApprove")}</label>
          <button className={btn} disabled={form.message.trim().length < 3 || !form.cron.trim()}
            onClick={() => void run(async () => { await agent.createSchedule({ projectId: pid, message: form.message.trim(), cron: form.cron.trim(), skill: form.skill || null, autoApprove: form.autoApprove }); setForm({ ...form, message: "" }); })}>{t("sk.addSchedule")}</button>
        </div>
      </div>
    </section>
  );
}

export function Skills() {
  const api = useApi();
  const { t } = useI18n();
  const agent = useMemo(() => new AgentApi(api), [api]);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [sel, setSel] = useState<SkillInfo | null>(null);
  const [md, setMd] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [pid, setPid] = useState("");
  const load = useCallback(async () => setSkills(await agent.skills()), [agent]);
  useEffect(() => { void load().catch(() => setErr(t("common.error"))); void agent.template().then((x) => setMd(x.markdown)).catch(() => undefined); }, [load, agent, t]);

  const run = async (fn: () => Promise<unknown>) => {
    setErr(null);
    try { await fn(); await load(); } catch (e) { setErr(e instanceof ApiRequestError ? e.message : t("common.error")); }
  };
  const open = async (s: SkillInfo) => { try { setSel(await agent.skill(s.name)); } catch { setErr(t("common.error")); } };
  const download = async (name: string) => {
    const text = await agent.exportSkill(name);
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `${name}.SKILL.md` });
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="mb-1 text-2xl font-semibold">{t("sk.title")}</h1>
        <p className="text-zinc-600 dark:text-zinc-400">{t("sk.subtitle")}</p>
      </div>
      {err && <p role="alert" className="rounded bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950">{err}</p>}
      <div className="grid gap-4 lg:grid-cols-2">
        <section className={card}>
          <h2 className="mb-2 text-lg font-medium">{t("sk.list")}</h2>
          <ul className="space-y-1">
            {skills.map((s) => <SkillRow key={s.name} s={s} selected={sel?.name === s.name} onSelect={() => void open(s)} onToggle={(v) => void run(() => agent.setSkillEnabled(s.name, v))} />)}
          </ul>
        </section>
        <section className={card}>
          {sel ? (
            <div className="space-y-2 text-sm">
              <h2 className="text-lg font-medium">{sel.name}</h2>
              <p>{sel.description}</p>
              <p className="text-xs text-zinc-500">{t("sk.tools")}: {sel.tools.join(", ")}</p>
              {sel.warnings.map((w) => <p key={w} className="text-xs text-amber-700">⚠ {w}</p>)}
              <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded bg-zinc-50 p-2 text-xs dark:bg-zinc-800">{sel.body}</pre>
              <div className="flex gap-2">
                <button className={btn2} onClick={() => void download(sel.name)}>{t("sk.export")}</button>
                {sel.source === "user" && <button className={btn2} onClick={() => void run(async () => { await agent.deleteSkill(sel.name); setSel(null); })}>{t("settings.models.delete")}</button>}
              </div>
            </div>
          ) : <p className="text-sm text-zinc-500">{t("sk.pick")}</p>}
        </section>
      </div>

      <section className={card}>
        <h2 className="mb-2 text-lg font-medium">{t("sk.create")}</h2>
        <p className="mb-2 text-xs text-amber-700">{t("sk.safety")}</p>
        <textarea aria-label={t("sk.markdown")} rows={14} className={`${field} w-full font-mono`} value={md} onChange={(e) => setMd(e.target.value)} />
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <button className={btn} disabled={md.trim().length < 20} onClick={() => void run(async () => { const s = await agent.createSkill(md); setSel(s); })}>{t("sk.save")}</button>
          <label className="cursor-pointer text-sm underline">{t("sk.import")}
            <input type="file" accept=".md,text/markdown,text/plain" className="sr-only" aria-label={t("sk.import")}
              onChange={async (e) => { const f = e.target.files?.[0]; if (f) setMd(await f.text()); e.target.value = ""; }} />
          </label>
        </div>
      </section>

      <div>
        <ProjectPicker storageKey="skills.pid" value={pid} onChange={setPid} />
        {pid && <Schedules pid={pid} skills={skills} />}
      </div>
    </div>
  );
}
