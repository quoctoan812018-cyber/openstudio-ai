import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AgentApi, type Approval, type Msg, type SkillInfo, type Thread, type ThreadView } from "../api/agent";
import { ApiRequestError } from "../api/client";
import { useApi } from "../api/connection";
import { subscribeEvents } from "../api/sse";
import { PodcastApi } from "../api/studio";
import { SubtitlesApi } from "../api/subtitles";
import { ProjectPicker } from "../components/ProjectPicker";
import { useI18n } from "../i18n";

const btn = "rounded bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-500 disabled:opacity-50";
const btn2 = "rounded border px-3 py-1.5 text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50";
const field = "rounded border px-2 py-1 text-sm dark:bg-zinc-800";

function FileLink({ pid, path }: { pid: string; path: string }) {
  const api = useApi();
  const agent = useMemo(() => new AgentApi(api), [api]);
  return (
    <button className="mr-2 rounded bg-zinc-100 px-2 py-0.5 text-xs text-indigo-700 underline dark:bg-zinc-800" title={path}
      onClick={async () => { window.open(await agent.fileUrl(pid, path), "_blank", "noopener"); }}>{path.split("/").pop()}</button>
  );
}

export function ApprovalCard({ a, onDecide, disabled }: { a: Approval; onDecide: (d: "approve" | "reject") => void; disabled?: boolean }) {
  const { t } = useI18n();
  const color = a.status === "approved" ? "border-emerald-400" : a.status === "pending" ? "border-amber-400" : "border-zinc-300";
  return (
    <div className={`rounded-lg border-2 ${color} bg-amber-50 p-3 text-sm dark:bg-zinc-900`} data-testid={`approval-${a.id}`}>
      <p className="font-medium">{t("ag.approval.title", { tool: a.tool })}</p>
      <p className="text-xs text-zinc-600 dark:text-zinc-400">{a.reason} {a.category === "download" && t("ag.approval.noAuto")}</p>
      <pre className="my-2 overflow-x-auto rounded bg-white p-2 text-xs dark:bg-zinc-800">{JSON.stringify(a.args, null, 1)}</pre>
      {a.status === "pending" ? (
        <div className="flex gap-2">
          <button className={btn} disabled={disabled} onClick={() => onDecide("approve")}>{t("ag.approve")}</button>
          <button className={btn2} disabled={disabled} onClick={() => onDecide("reject")}>{t("ag.reject")}</button>
        </div>
      ) : <p className="text-xs">{t(`ag.approval.${a.status}`)}</p>}
    </div>
  );
}

export function MessageView({ m, pid, approval, onDecide }: { m: Msg; pid: string; approval?: Approval; onDecide: (id: string, d: "approve" | "reject") => void }) {
  const { t } = useI18n();
  const c = m.content;
  switch (m.kind) {
    case "user":
      return <div className="ml-auto max-w-[80%] whitespace-pre-wrap rounded-xl bg-indigo-600 px-3 py-2 text-sm text-white">{c.text}</div>;
    case "assistant":
      return <div className="max-w-[85%] whitespace-pre-wrap rounded-xl bg-zinc-100 px-3 py-2 text-sm dark:bg-zinc-800">{c.text}</div>;
    case "question":
      return <div className="max-w-[85%] rounded-xl border-2 border-sky-400 bg-sky-50 px-3 py-2 text-sm dark:bg-zinc-900"><strong>{t("ag.question")}</strong> {c.text}</div>;
    case "skill":
      return <div className="text-xs text-zinc-500">{t("ag.usingSkill")}: <code>{c.name}</code></div>;
    case "tool_call":
      return (
        <details className="text-xs text-zinc-600 dark:text-zinc-400">
          <summary className="cursor-pointer">🛠 <code>{c.tool}</code>{c.thought ? ` — ${c.thought}` : ""}</summary>
          <pre className="mt-1 overflow-x-auto rounded bg-zinc-50 p-2 dark:bg-zinc-900">{JSON.stringify(c.args, null, 1)}</pre>
        </details>
      );
    case "tool_result":
      return (
        <div className={`text-xs ${c.ok ? "text-emerald-700 dark:text-emerald-400" : "text-red-700 dark:text-red-400"}`}>
          {c.ok ? "✓" : "✗"} <code>{c.tool}</code>
          <details className="inline-block align-top"><summary className="ml-2 inline cursor-pointer">{t("ag.details")}</summary>
            <pre className="mt-1 max-w-[40rem] overflow-x-auto rounded bg-zinc-50 p-2 text-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">{JSON.stringify(c.summary, null, 1)}</pre>
          </details>
          {(c.files as string[] | undefined)?.length ? <div className="mt-1">{(c.files as string[]).map((f) => <FileLink key={f} pid={pid} path={f} />)}</div> : null}
        </div>
      );
    case "approval":
      return approval ? <ApprovalCard a={approval} onDecide={(d) => onDecide(approval.id, d)} /> : null;
    case "error":
      return <div role="alert" className="rounded bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950">{c.message}</div>;
    default:
      return null;
  }
}

function Chat({ pid, thread, skills, onThreadChange }: { pid: string; thread: Thread; skills: SkillInfo[]; onThreadChange: () => void }) {
  const api = useApi();
  const { t } = useI18n();
  const agent = useMemo(() => new AgentApi(api), [api]);
  const [view, setView] = useState<ThreadView | null>(null);
  const [text, setText] = useState("");
  const [skill, setSkill] = useState(thread.skill ?? "");
  const [err, setErr] = useState<string | null>(null);
  const [approvals, setApprovals] = useState<Record<string, Approval>>({});
  const bottom = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    const v = await agent.thread(thread.id);
    setView(v);
    const all = await api.req<Approval[]>(`/approvals?threadId=${thread.id}`);
    setApprovals(Object.fromEntries(all.map((a) => [a.id, a])));
  }, [agent, api, thread.id]);

  useEffect(() => { void load().catch(() => setErr(t("common.error"))); }, [load, t]);
  useEffect(() => {
    const ctl = new AbortController();
    let timer: number | undefined;
    subscribeEvents(api.conn, { projectId: pid }, (e) => {
      if (e.type.startsWith("agent.") || e.type.startsWith("approval.") || e.type.startsWith("job.")) {
        window.clearTimeout(timer);
        timer = window.setTimeout(() => void load().catch(() => undefined), 250);   // gộp nhiều sự kiện liên tiếp
      }
    }, ctl.signal);
    return () => { ctl.abort(); window.clearTimeout(timer); };
  }, [api, pid, load]);
  useEffect(() => { bottom.current?.scrollIntoView?.({ block: "end" }); }, [view?.messages.length]);

  const running = view?.run?.status === "running" || view?.run?.status === "queued";
  const decide = async (id: string, d: "approve" | "reject") => {
    try { await agent.decide(id, d); await load(); } catch (e) { setErr(e instanceof ApiRequestError ? e.message : t("common.error")); }
  };
  const submit = async () => {
    setErr(null);
    try { await agent.send(thread.id, text, skill || null); setText(""); await load(); onThreadChange(); }
    catch (e) { setErr(e instanceof ApiRequestError ? e.message : t("common.error")); }
  };
  const attach = async (f: File) => {
    setErr(null);
    try {
      if (/\.(txt|md|markdown)$/i.test(f.name)) {
        await new PodcastApi(api, pid).command("set-brief", { brief: { sourceText: await f.text(), sourceName: f.name } });
        setText((x) => `${x}${x ? "\n" : ""}${t("ag.attachedDoc", { name: f.name })}`);
      } else {
        await new SubtitlesApi(api, pid).upload(f);
        setText((x) => `${x}${x ? "\n" : ""}${t("ag.attachedMedia", { name: f.name })}`);
      }
    } catch (e) { setErr(e instanceof ApiRequestError ? e.message : t("common.error")); }
  };

  return (
    <div className="flex h-[70vh] flex-col rounded-xl border border-zinc-200 dark:border-zinc-800">
      <div className="flex-1 space-y-2 overflow-y-auto p-3" aria-live="polite">
        {view?.messages.length === 0 && <p className="text-sm text-zinc-500">{t("ag.empty")}</p>}
        {view?.messages.map((m) => (
          <MessageView key={m.id} m={m} pid={pid} approval={m.kind === "approval" ? approvals[m.content.approvalId] : undefined} onDecide={decide} />
        ))}
        {running && <p className="text-xs text-zinc-500" role="status">{t("ag.running")} <button className="ml-2 underline" onClick={() => void agent.cancel(thread.id)}>{t("ag.cancel")}</button></p>}
        {view?.run?.status === "failed" && <p role="alert" className="text-sm text-red-700">{view.run.error?.message}</p>}
        <div ref={bottom} />
      </div>
      {err && <p role="alert" className="px-3 text-sm text-red-700">{err}</p>}
      <div className="space-y-2 border-t border-zinc-200 p-3 dark:border-zinc-800">
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <label>{t("ag.skill")}{" "}
            <select aria-label={t("ag.skill")} className={field} value={skill} onChange={(e) => setSkill(e.target.value)}>
              <option value="">{t("ag.skillAuto")}</option>
              {skills.filter((s) => s.enabled).map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-1" title={t("ag.autoHelp")}>
            <input type="checkbox" checked={view?.thread.autoApprove ?? false} onChange={(e) => void agent.patchThread(thread.id, { autoApprove: e.target.checked }).then(load)} />
            {t("ag.autoApprove")}
          </label>
          <label className="ml-auto cursor-pointer underline">{t("ag.attach")}
            <input type="file" className="sr-only" aria-label={t("ag.attach")} onChange={(e) => { const f = e.target.files?.[0]; if (f) void attach(f); e.target.value = ""; }} />
          </label>
        </div>
        <div className="flex gap-2">
          <textarea aria-label={t("ag.message")} rows={2} className={`${field} flex-1`} placeholder={t("ag.placeholder")} value={text} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && text.trim() && !running) void submit(); }} />
          <button className={btn} disabled={!text.trim() || running} onClick={() => void submit()}>{t("ag.send")}</button>
        </div>
      </div>
    </div>
  );
}

function Workspace({ pid }: { pid: string }) {
  const api = useApi();
  const { t } = useI18n();
  const agent = useMemo(() => new AgentApi(api), [api]);
  const [threads, setThreads] = useState<Thread[]>([]);
  const [current, setCurrent] = useState<string>("");
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const load = useCallback(async () => setThreads(await agent.threads(pid)), [agent, pid]);
  useEffect(() => { void load(); void agent.skills().then(setSkills).catch(() => undefined); }, [load, agent]);
  useEffect(() => { if (!current && threads.length) setCurrent(threads[0].id); }, [threads, current]);
  const th = threads.find((x) => x.id === current);

  return (
    <div className="grid gap-4 lg:grid-cols-[14rem_1fr]">
      <aside className="space-y-2">
        <button className={`${btn} w-full`} onClick={async () => { const n = await agent.createThread(pid); await load(); setCurrent(n.id); }}>{t("ag.newThread")}</button>
        <ul className="space-y-1 text-sm">
          {threads.map((x) => (
            <li key={x.id}>
              <button className={`w-full truncate rounded px-2 py-1 text-left ${x.id === current ? "bg-indigo-100 dark:bg-indigo-950" : "hover:bg-zinc-100 dark:hover:bg-zinc-800"}`}
                onClick={() => setCurrent(x.id)}>{x.title}</button>
            </li>
          ))}
        </ul>
      </aside>
      {th ? <Chat key={th.id} pid={pid} thread={th} skills={skills} onThreadChange={() => void load()} /> : <p className="text-sm text-zinc-500">{t("ag.noThread")}</p>}
    </div>
  );
}

export function Agent() {
  const { t } = useI18n();
  const [pid, setPid] = useState("");
  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold">{t("ag.title")}</h1>
      <p className="mb-4 text-zinc-600 dark:text-zinc-400">{t("ag.subtitle")}</p>
      <ProjectPicker storageKey="agent.pid" value={pid} onChange={setPid} />
      {pid && <Workspace key={pid} pid={pid} />}
    </div>
  );
}
