import { useCallback, useEffect, useState } from "react";
import { useApi } from "../api/connection";
import { useI18n } from "../i18n";

const field = "rounded border px-2 py-1 text-sm dark:bg-zinc-800";

/** Chọn/tạo project; nhớ lựa chọn theo từng công cụ trong sessionStorage. */
export function ProjectPicker({ storageKey, value, onChange }: { storageKey: string; value: string; onChange: (id: string) => void }) {
  const api = useApi();
  const { t } = useI18n();
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [name, setName] = useState("");
  const load = useCallback(() => api.projects().then(setProjects), [api]);

  useEffect(() => {
    let saved = "";
    try { saved = sessionStorage.getItem(storageKey) ?? ""; } catch { /* bỏ qua */ }
    void api.projects().then((list) => {
      setProjects(list);
      const want = value || saved;
      onChange(list.some((p) => p.id === want) ? want : ""); // project đã bị xoá thì bỏ chọn
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);
  useEffect(() => {
    try { sessionStorage.setItem(storageKey, value); } catch { /* bỏ qua */ }
  }, [storageKey, value]);

  return (
    <div className="mb-4 flex flex-wrap items-center gap-2">
      <select aria-label={t("library.projects")} className={field} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{t("sub.pickProject")}</option>
        {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
      <input className={field} placeholder={t("library.projectName")} aria-label={t("library.projectName")} value={name} onChange={(e) => setName(e.target.value)} />
      <button className="rounded border px-3 py-1.5 text-sm disabled:opacity-50" disabled={!name.trim()}
        onClick={async () => { const p = await api.createProject(name.trim()); setName(""); await load(); onChange(p.id); }}>{t("library.newProject")}</button>
    </div>
  );
}

export const projectExists = (list: { id: string }[], id: string) => list.some((p) => p.id === id);
