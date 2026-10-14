import type { Job } from "@openstudio/protocol";
import type { Cue } from "../lib/cues";
import { Api, ApiRequestError } from "./client";

export interface Track {
  kind: "transcript" | "translation";
  cues: Cue[];
  stale: boolean;
  meta: Record<string, unknown>;
}

export interface SubtitleSource {
  path: string;
  filename: string;
  audio: string;
  duration: number;
  hasVideo: boolean;
  width: number | null;
  height: number | null;
}

export interface SubtitleState {
  source: SubtitleSource | null;
  sourceLang: string | null;
  tracks: Record<string, Track>;
  glossary: { src: string; dst: string }[];
  options: { tone: string; polish: boolean; market: string | null; maxChars: number };
  revisionId?: string;
}

export interface ToolStateResponse {
  projectId: string;
  tool: string;
  revision: number;
  state: SubtitleState | Record<string, never>;
}

export interface RevisionInfo {
  id: string;
  n: number;
  author: string;
  createdAt: number;
}

export interface LlmStatus {
  available: boolean;
  model: string;
  model_installed: boolean;
}

export const LANGS: Record<string, string> = {
  vi: "Tiếng Việt", en: "English", zh: "中文", ja: "日本語", ko: "한국어", fr: "Français", de: "Deutsch",
  es: "Español", pt: "Português", ru: "Русский", th: "ไทย", id: "Indonesia", ms: "Melayu", it: "Italiano",
  tr: "Türkçe", ar: "العربية", hi: "हिन्दी",
};

const T = "subtitles";

export class SubtitlesApi {
  constructor(private api: Api, private pid: string) {}

  private req<T>(path: string, init?: RequestInit): Promise<T> {
    return this.api.req<T>(path, init);
  }

  state = () => this.req<ToolStateResponse>(`/projects/${this.pid}/tools/${T}/state`);
  revisions = () => this.req<(RevisionInfo & { state: unknown })[]>(`/projects/${this.pid}/tools/${T}/revisions`);
  command = (type: string, payload: object, expectedRevision?: number) =>
    this.req<ToolStateResponse>(`/projects/${this.pid}/tools/${T}/commands`, {
      method: "POST", body: JSON.stringify({ type, payload, expectedRevision }),
    });
  saveTrack = (lang: string, kind: Track["kind"], cues: Cue[], expectedRevision: number) =>
    this.command("set-track", { lang, kind, cues, meta: {} }, expectedRevision);
  restore = (revisionId: string) => this.command("select-revision", { revisionId });
  setGlossary = (glossary: { src: string; dst: string }[]) => this.command("set-glossary", { glossary });
  setOptions = (options: Partial<SubtitleState["options"]>) => this.command("set-options", { options });

  upload(file: File): Promise<Job> {
    return this.req<Job>(`/projects/${this.pid}/subtitles/upload?filename=${encodeURIComponent(file.name)}`, {
      method: "PUT", body: file, headers: { "Content-Type": "application/octet-stream" },
    });
  }
  fetchUrl = (url: string) => this.req<Job>(`/projects/${this.pid}/subtitles/fetch`, { method: "POST", body: JSON.stringify({ url }) });
  transcribe = (language: string | null, polish: boolean) =>
    this.req<Job>(`/projects/${this.pid}/subtitles/transcribe`, { method: "POST", body: JSON.stringify({ language, polish }) });
  translate = (targets: string[], tone: string, market: string | null) =>
    this.req<Job>(`/projects/${this.pid}/subtitles/translate`, { method: "POST", body: JSON.stringify({ targets, tone, market }) });
  exportTrack = (body: { lang: string; format: string; second?: string | null; order: string; layout: string }) =>
    this.req<{ path: string; bytes: number }>(`/projects/${this.pid}/subtitles/export`, { method: "POST", body: JSON.stringify(body) });
  burn = (body: { lang: string; second?: string | null; order: string; layout: string; fit: string }) =>
    this.req<Job>(`/projects/${this.pid}/subtitles/burn`, { method: "POST", body: JSON.stringify(body) });
  fileUrl = async (path: string) => {
    const r = await this.req<{ url: string }>(`/projects/${this.pid}/file-url`, { method: "POST", body: JSON.stringify({ path }) });
    return `${this.api.conn.address}${r.url}`;
  };
}

export { ApiRequestError };
