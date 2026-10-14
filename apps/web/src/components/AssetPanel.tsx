import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiRequestError } from "../api/client";
import { useApi } from "../api/connection";
import { AssetsApi, type Asset } from "../api/studio";
import { useI18n } from "../i18n";
import { fmtTime } from "../lib/cues";

const btn2 = "rounded border px-2 py-1 text-xs hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50";
const ICON: Record<string, string> = { video: "🎞", image: "🖼", audio: "🎵" };

/** Kho tài nguyên của project: tải lên, đưa file có sẵn (exports/…) vào kho, chọn để dùng. `actions` là các nút theo từng công cụ. */
export function AssetPanel({ pid, kinds, actions, onChange }: {
  pid: string; kinds?: Asset["kind"][]; actions: { label: string; kinds?: Asset["kind"][]; run: (a: Asset) => void | Promise<void> }[]; onChange?: (list: Asset[]) => void;
}) {
  const api = useApi();
  const { t } = useI18n();
  const store = useMemo(() => new AssetsApi(api, pid), [api, pid]);
  const [list, setList] = useState<Asset[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [path, setPath] = useState("");
  const load = useCallback(async () => { const l = await store.list(); setList(l); onChange?.(l); }, [store, onChange]);
  useEffect(() => { void load().catch(() => undefined); }, [load]);
  const guard = async (fn: () => Promise<unknown>) => {
    setMsg(null);
    try { await fn(); await load(); } catch (e) { setMsg(e instanceof ApiRequestError ? e.message : t("common.error")); }
  };
  const shown = list.filter((a) => !kinds || kinds.includes(a.kind));
  return (
    <div className="space-y-2">
      {msg && <p role="alert" className="text-sm text-red-700">{msg}</p>}
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label className="cursor-pointer rounded bg-indigo-600 px-3 py-1.5 text-white">
          {t("asset.upload")}
          <input type="file" className="hidden" aria-label={t("asset.upload")} accept="video/*,audio/*,image/*"
            onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void guard(() => store.upload(f)); }} />
        </label>
        <input className="rounded border px-2 py-1 dark:bg-zinc-800" placeholder={t("asset.pathPlaceholder")} aria-label={t("asset.path")} value={path} onChange={(e) => setPath(e.target.value)} />
        <button className={btn2} disabled={!path.trim()} onClick={() => void guard(async () => { await store.register(path.trim()); setPath(""); })}>{t("asset.register")}</button>
      </div>
      {shown.length === 0 ? <p className="text-sm text-zinc-500">{t("asset.empty")}</p> : (
        <ul className="grid gap-1 text-sm sm:grid-cols-2">
          {shown.map((a) => (
            <li key={a.id} className="flex items-center gap-2 rounded border border-zinc-200 px-2 py-1 dark:border-zinc-800">
              <span>{ICON[a.kind]}</span>
              <span className="min-w-0 flex-1 truncate" title={a.path}>{a.name}</span>
              <span className="text-xs text-zinc-500">{a.kind === "image" ? `${a.width}×${a.height}` : fmtTime(a.duration).replace(/\.\d+$/, "")}</span>
              {actions.filter((x) => !x.kinds || x.kinds.includes(a.kind)).map((x) => (
                <button key={x.label} className={btn2} onClick={() => void guard(() => Promise.resolve(x.run(a)))}>{x.label}</button>
              ))}
              <button className="text-red-700" title={t("sub.delete")} onClick={() => void guard(() => store.remove(a.id))}>✕</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
