import type {
  Hardware, Job, LibraryFile, ModelInfo, Project, Tool, UserSettings,
} from "@openstudio/protocol";
import type { Connection } from "./sse";

export class ApiRequestError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: Record<string, unknown>) {
    super(message);
  }
}

export interface SettingsResponse extends UserSettings {
  data_dir: string;
  version: string;
}

export class Api {
  constructor(public conn: Connection) {}

  async req<T>(path: string, init: RequestInit = {}): Promise<T> {
    const res = await fetch(`${this.conn.address}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${this.conn.token}`,
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    });
    if (res.status === 204) return undefined as T;
    const body = await res.json().catch(() => null);
    if (!res.ok) {
      const e = body?.error;
      throw new ApiRequestError(res.status, e?.code ?? "HTTP_ERROR", e?.message ?? res.statusText, e?.details);
    }
    return body as T;
  }

  health = () => fetch(`${this.conn.address}/healthz`).then((r) => r.ok);
  hardware = () => this.req<Hardware>("/system/hardware");
  doctor = () => this.req<DoctorReport>("/system/doctor");
  tools = () => this.req<Tool[]>("/tools");
  settings = () => this.req<SettingsResponse>("/settings");
  saveSettings = (s: UserSettings) => this.req<UserSettings>("/settings", { method: "PUT", body: JSON.stringify(s) });
  models = () => this.req<ModelInfo[]>("/models");
  downloadModel = (id: string, acknowledgeNonCommercial = false) =>
    this.req<Job>(`/models/${encodeURIComponent(id)}/download`, {
      method: "POST",
      body: JSON.stringify({ acknowledge_non_commercial: acknowledgeNonCommercial }),
    });
  deleteModel = (id: string) => this.req<void>(`/models/${encodeURIComponent(id)}`, { method: "DELETE" });
  projects = () => this.req<Project[]>("/projects");
  createProject = (name: string) => this.req<Project>("/projects", { method: "POST", body: JSON.stringify({ name }) });
  llmStatus = () => this.req<{ available: boolean; model: string; model_installed: boolean }>("/llm/status");
  jobs = (projectId: string) => this.req<Job[]>(`/jobs?projectId=${encodeURIComponent(projectId)}`);
  library = (projectId?: string) =>
    this.req<LibraryFile[]>(`/library${projectId ? `?projectId=${encodeURIComponent(projectId)}` : ""}`);
}

export interface DoctorCheck { id: string; ok: boolean; required: boolean; detail: string; fix: string | null }
export interface DoctorReport { ok: boolean; checks: DoctorCheck[] }
