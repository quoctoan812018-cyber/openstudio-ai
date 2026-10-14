import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useI18n } from "../i18n";
import { Api } from "./client";
import type { Connection } from "./sse";

declare global {
  interface Window {
    /** Do Electron preload cung cấp (apps/desktop). */
    openstudioDesktop?: { connection: Connection };
  }
}

const ApiCtx = createContext<Api | null>(null);
export const useApi = (): Api => {
  const api = useContext(ApiCtx);
  if (!api) throw new Error("useApi ngoài ConnectionGate");
  return api;
};
export { ApiCtx };

function initialConnection(): Connection | null {
  if (window.openstudioDesktop?.connection) return window.openstudioDesktop.connection;
  const address = import.meta.env.VITE_DAEMON_URL as string | undefined;
  const token = import.meta.env.VITE_DAEMON_TOKEN as string | undefined;
  if (address && token) return { address, token };
  try {
    const saved = sessionStorage.getItem("conn");
    if (saved) return JSON.parse(saved) as Connection;
  } catch {
    /* bỏ qua */
  }
  return null;
}

/** Chạy dưới cùng origin với daemon (Docker/web) → dùng origin hiện tại; dev server Vite (5173) → cổng daemon dev 8787. */
function defaultAddress(): string {
  const { protocol, origin, port } = window.location;
  return protocol.startsWith("http") && port !== "5173" && port !== "" ? origin : "http://127.0.0.1:8787";
}

export function ConnectionGate({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [conn, setConn] = useState<Connection | null>(initialConnection);
  const [state, setState] = useState<"idle" | "connecting" | "ok" | "error">(conn ? "connecting" : "idle");
  const [form, setForm] = useState({ address: defaultAddress(), token: "" });
  const api = useMemo(() => (conn ? new Api(conn) : null), [conn]);

  useEffect(() => {
    if (!api) return;
    let alive = true;
    setState("connecting");
    api.hardware().then(
      () => alive && setState("ok"),
      () => alive && setState("error"),
    );
    return () => {
      alive = false;
    };
  }, [api]);

  if (api && state === "ok") return <ApiCtx.Provider value={api}>{children}</ApiCtx.Provider>;

  return (
    <main className="mx-auto mt-24 max-w-md rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <h1 className="mb-4 text-xl font-semibold">{t("conn.title")}</h1>
      {state === "connecting" && <p>{t("conn.connecting")}</p>}
      {state === "error" && <p role="alert" className="mb-3 text-red-600">{t("conn.error")}</p>}
      {(state === "idle" || state === "error") && (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            const c = { address: form.address.replace(/\/$/, ""), token: form.token };
            try {
              sessionStorage.setItem("conn", JSON.stringify(c));
            } catch {
              /* bỏ qua */
            }
            setConn(c);
          }}
        >
          <label className="block text-sm">
            {t("conn.url")}
            <input className="mt-1 w-full rounded border px-2 py-1 dark:bg-zinc-800" value={form.address}
              onChange={(e) => setForm({ ...form, address: e.target.value })} />
          </label>
          <label className="block text-sm">
            {t("conn.token")}
            <input type="password" className="mt-1 w-full rounded border px-2 py-1 dark:bg-zinc-800" value={form.token}
              onChange={(e) => setForm({ ...form, token: e.target.value })} />
          </label>
          <button className="rounded bg-indigo-600 px-3 py-1.5 text-white hover:bg-indigo-500">{t("conn.connect")}</button>
        </form>
      )}
    </main>
  );
}
