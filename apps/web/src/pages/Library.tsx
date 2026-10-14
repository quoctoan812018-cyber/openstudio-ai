import type { LibraryFile, Project } from "@openstudio/protocol";
import { useCallback, useEffect, useState } from "react";
import { useApi } from "../api/connection";
import { formatBytes } from "../format";
import { useI18n } from "../i18n";

export function Library() {
  const api = useApi();
  const { t } = useI18n();
  const [projects, setProjects] = useState<Project[]>([]);
  const [files, setFiles] = useState<LibraryFile[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [name, setName] = useState("");
  const [err, setErr] = useState(false);

  const load = useCallback(async () => {
    try {
      const [p, f] = await Promise.all([api.projects(), api.library(selected || undefined)]);
      setProjects(p);
      setFiles(f);
      setErr(false);
    } catch {
      setErr(true);
    }
  }, [api, selected]);

  useEffect(() => {
    void load();
  }, [load]);

  const projectName = (id: string) => projects.find((p) => p.id === id)?.name ?? id;

  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">{t("library.title")}</h1>
      {err && <p role="alert" className="text-red-600">{t("common.error")}</p>}
      <form
        className="mb-4 flex gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!name.trim()) return;
          await api.createProject(name.trim());
          setName("");
          void load();
        }}
      >
        <input aria-label={t("library.projectName")} placeholder={t("library.projectName")} value={name}
          onChange={(e) => setName(e.target.value)} className="rounded border px-2 py-1 dark:bg-zinc-800" />
        <button className="rounded bg-indigo-600 px-3 py-1 text-white hover:bg-indigo-500">{t("library.newProject")}</button>
      </form>

      <label className="mb-3 block text-sm">
        {t("library.projects")}{" "}
        <select value={selected} onChange={(e) => setSelected(e.target.value)} className="rounded border px-2 py-1 dark:bg-zinc-800">
          <option value="">{t("library.allProjects")}</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </label>
      {projects.length === 0 && <p className="text-zinc-500">{t("library.noProjects")}</p>}

      {files.length === 0 ? (
        <p className="text-zinc-500">{t("library.empty")}</p>
      ) : (
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b text-zinc-500">
              <th className="py-1">{t("library.col.name")}</th><th>{t("library.col.kind")}</th><th>{t("library.col.size")}</th>
            </tr>
          </thead>
          <tbody>
            {files.map((f) => (
              <tr key={`${f.projectId}/${f.path}`} className="border-b border-zinc-100 dark:border-zinc-800">
                <td className="py-1">{projectName(f.projectId)} / {f.path}</td>
                <td>{f.kind}</td>
                <td>{formatBytes(f.bytes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
