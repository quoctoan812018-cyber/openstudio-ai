import type { Hardware, ModelInfo } from "@openstudio/protocol";
import { useCallback, useEffect, useState } from "react";
import { ApiRequestError, type DoctorReport, type SettingsResponse } from "../api/client";
import { useApi } from "../api/connection";
import { subscribeEvents } from "../api/sse";
import { formatBytes } from "../format";
import { useI18n, type Lang } from "../i18n";

function HardwarePanel({ hw }: { hw: Hardware }) {
  const { t } = useI18n();
  return (
    <dl className="grid grid-cols-[8rem_1fr] gap-y-1 text-sm" data-testid="hardware">
      <dt className="text-zinc-500">{t("settings.hardware.tier")}</dt>
      <dd><strong>{hw.tier_label}</strong></dd>
      <dt className="text-zinc-500">{t("settings.hardware.cpu")}</dt>
      <dd>{String(hw.cpu.name)} · {String(hw.cpu.cores)} cores / {String(hw.cpu.threads)} threads</dd>
      <dt className="text-zinc-500">{t("settings.hardware.ram")}</dt>
      <dd>{hw.ram_gb} GB</dd>
      <dt className="text-zinc-500">{t("settings.hardware.gpu")}</dt>
      <dd>{hw.gpus.length ? hw.gpus.map((g) => `${g.name} (${g.vram_gb} GB)`).join(", ") : t("settings.hardware.noGpu")}</dd>
    </dl>
  );
}

export function ModelRow({ m, percent, onDownload, onDelete }: {
  m: ModelInfo; percent?: number; onDownload: () => void; onDelete: () => void;
}) {
  const { t } = useI18n();
  const status = m.status === "installed" ? t("settings.models.installed")
    : m.status === "downloading" ? t("settings.models.downloading") : t("settings.models.notInstalled");
  return (
    <li className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800" data-testid={`model-${m.id}`}>
      <div className="flex flex-wrap items-center gap-2">
        <strong>{m.name}</strong>
        <span className="text-xs text-zinc-500">{m.capability}</span>
        {m.non_commercial && <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs text-red-800">{t("settings.models.nc")}</span>}
        {!m.verified && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800">{t("settings.models.unverified")}</span>}
        <span className="ml-auto text-sm">{status}</span>
      </div>
      <p className="mt-1 text-xs text-zinc-500">
        {m.weights_license ?? "—"} · {m.size_bytes ? formatBytes(m.size_bytes) : ""}
      </p>
      {m.warning && <p className="mt-1 text-xs text-red-700 dark:text-red-400">{m.warning}</p>}
      {m.status === "downloading" && (
        <progress className="mt-2 w-full" max={100} value={percent ?? 0} aria-label={m.name} />
      )}
      <div className="mt-2 flex gap-2">
        {m.status === "not_installed" && (m.downloadable
          ? <button className="rounded bg-indigo-600 px-2 py-1 text-sm text-white" onClick={onDownload}>{t("settings.models.download")}</button>
          : <span className="text-xs text-zinc-400">{t("settings.models.noDownload")}</span>)}
        {m.status === "installed" && (
          <button className="rounded border px-2 py-1 text-sm" onClick={onDelete}>{t("settings.models.delete")}</button>
        )}
      </div>
    </li>
  );
}

export function Settings() {
  const api = useApi();
  const { t, lang, setLang } = useI18n();
  const [hw, setHw] = useState<Hardware | null>(null);
  const [doctor, setDoctor] = useState<DoctorReport | null>(null);
  const [prefs, setPrefs] = useState<SettingsResponse | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [progress, setProgress] = useState<Record<string, number>>({});
  const [msg, setMsg] = useState<string | null>(null);

  const loadModels = useCallback(() => api.models().then(setModels).catch(() => setMsg(t("common.error"))), [api, t]);

  useEffect(() => {
    api.hardware().then(setHw).catch(() => setMsg(t("common.error")));
    api.doctor().then(setDoctor).catch(() => undefined);
    api.settings().then(setPrefs).catch(() => setMsg(t("common.error")));
    void loadModels();
    const ctl = new AbortController();
    subscribeEvents(api.conn, {}, (e) => {
      if (e.type === "job.progress") setProgress((p) => ({ ...p, [e.jobId ?? ""]: (e.data as { percent: number }).percent }));
      if (e.type === "job.succeeded" || e.type === "job.failed" || e.type === "job.cancelled") void loadModels();
      if (e.type === "job.failed") setMsg(String((e.data as { message?: string }).message ?? t("common.error")));
    }, ctl.signal);
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  const savePrefs = async (next: SettingsResponse) => {
    setPrefs(next);
    await api.saveSettings({
      language: next.language, ai_label_metadata: next.ai_label_metadata,
      ai_label_watermark: next.ai_label_watermark, cloud_providers_enabled: next.cloud_providers_enabled,
    });
  };

  const download = async (m: ModelInfo) => {
    let ack = false;
    if (m.non_commercial) {
      if (!window.confirm(t("settings.models.ncConfirm"))) return;
      ack = true;
    }
    try {
      await api.downloadModel(m.id, ack);
      setMsg(null);
      void loadModels();
    } catch (e) {
      setMsg(e instanceof ApiRequestError ? e.message : t("common.error"));
    }
  };

  const remove = async (m: ModelInfo) => {
    if (!window.confirm(t("settings.models.deleteConfirm"))) return;
    await api.deleteModel(m.id);
    void loadModels();
  };

  return (
    <section className="space-y-8">
      <h1 className="text-2xl font-semibold">{t("settings.title")}</h1>
      {msg && <p role="alert" className="text-red-600">{msg}</p>}

      <div>
        <h2 className="mb-2 text-lg font-medium">{t("settings.hardware")}</h2>
        {hw ? <HardwarePanel hw={hw} /> : <p>{t("common.loading")}</p>}
        {hw?.note && <p className="mt-1 text-sm text-zinc-500">{hw.note}</p>}
      </div>

      <div>
        <h2 className="mb-2 text-lg font-medium">{t("settings.doctor")}</h2>
        {doctor ? (
          <ul className="space-y-1 text-sm" data-testid="doctor">
            {doctor.checks.map((c) => (
              <li key={c.id}>
                <span className={c.ok ? "text-emerald-700" : c.required ? "text-red-700" : "text-amber-700"}>{c.ok ? "✔" : c.required ? "✖" : "!"}</span>{" "}
                <b>{c.id}</b> — {c.detail}
                {c.fix && <code className="ml-2 rounded bg-zinc-100 px-1 dark:bg-zinc-800">{c.fix}</code>}
              </li>
            ))}
          </ul>
        ) : <p>{t("common.loading")}</p>}
      </div>

      {prefs && (
        <div className="space-y-2">
          <label className="block text-sm">
            {t("settings.language")}{" "}
            <select value={lang} className="rounded border px-2 py-1 dark:bg-zinc-800"
              onChange={(e) => { const l = e.target.value as Lang; setLang(l); void savePrefs({ ...prefs, language: l }); }}>
              <option value="vi">Tiếng Việt</option>
              <option value="en">English</option>
            </select>
          </label>
          <p className="text-sm"><span className="text-zinc-500">{t("settings.dataDir")}: </span><code>{prefs.data_dir}</code></p>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={prefs.ai_label_metadata}
              onChange={(e) => void savePrefs({ ...prefs, ai_label_metadata: e.target.checked })} />
            {t("settings.aiLabel")}
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={prefs.ai_label_watermark}
              onChange={(e) => void savePrefs({ ...prefs, ai_label_watermark: e.target.checked })} />
            {t("settings.aiWatermark")}
          </label>
        </div>
      )}

      <div>
        <h2 className="mb-2 text-lg font-medium">{t("settings.models")}</h2>
        <ul className="space-y-2">
          {models.map((m) => (
            <ModelRow key={m.id} m={m} percent={m.downloadJobId ? progress[m.downloadJobId] : undefined}
              onDownload={() => void download(m)} onDelete={() => void remove(m)} />
          ))}
        </ul>
      </div>
    </section>
  );
}
