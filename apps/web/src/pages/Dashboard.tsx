import type { Tool } from "@openstudio/protocol";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../api/connection";
import { useI18n } from "../i18n";

export function ToolCard({ tool }: { tool: Tool }) {
  const { t } = useI18n();
  const locked = !tool.available;
  const soon = tool.available && !tool.implemented;
  return (
    <li
      data-testid={`tool-${tool.id}`}
      className={`rounded-xl border p-4 shadow-sm dark:border-zinc-800 ${
        locked ? "border-zinc-200 bg-zinc-100 opacity-70 dark:bg-zinc-900" : "border-zinc-200 bg-white dark:bg-zinc-900"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-medium">
          {tool.implemented && !locked ? <Link className="hover:underline" to={`/tools/${tool.id}`}>{tool.name}</Link> : tool.name}
        </h2>
        <span className={`rounded-full px-2 py-0.5 text-xs ${
          locked ? "bg-amber-100 text-amber-800" : soon ? "bg-zinc-200 text-zinc-700" : "bg-emerald-100 text-emerald-800"
        }`}>
          {locked ? t("dashboard.locked") : soon ? t("dashboard.soon", { phase: tool.phase }) : t("dashboard.ready")}
        </span>
      </div>
      <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">{tool.description}</p>
      {tool.locked_reason && <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">{tool.locked_reason}</p>}
    </li>
  );
}

export function Dashboard() {
  const api = useApi();
  const { t } = useI18n();
  const [tools, setTools] = useState<Tool[] | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    api.tools().then(setTools, () => setErr(true));
  }, [api]);

  return (
    <section>
      <h1 className="text-2xl font-semibold">{t("dashboard.title")}</h1>
      <p className="mb-4 text-zinc-600 dark:text-zinc-400">{t("dashboard.subtitle")}</p>
      {err && <p role="alert" className="text-red-600">{t("common.error")}</p>}
      {!tools && !err && <p>{t("common.loading")}</p>}
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {tools?.map((tool) => <ToolCard key={tool.id} tool={tool} />)}
      </ul>
    </section>
  );
}
