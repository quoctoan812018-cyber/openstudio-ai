import type { Job } from "@openstudio/protocol";
import { Api } from "./client";
import type { SubtitleState, ToolStateResponse } from "./subtitles";

export interface VoiceInfo {
  id: string;
  name: string;
  engine: string;
  lang: string;
  description: string;
  gender: string;
  kind: "preset" | "clone";
  consentId?: string;
}

export interface EngineInfo {
  id: string;
  name: string;
  languages: string[];
  clone: boolean;
  model: string | null;
  available: boolean;
}

export interface ConsentRecord {
  id: string;
  kind: string;
  subject: string;
  statement: string;
  usedBy: string | null;
}

export interface TtsResult {
  path: string;
  duration: number;
  segments: { index: number; speaker: string; text: string; voice: string; start: number; end: number }[];
  failed: { id: string; message: string }[];
}

export interface TtsState {
  text: string;
  language: string;
  voices: Record<string, string>;
  options: { speed: number; format: "wav" | "mp3"; gap: number; loudnorm: boolean };
  result: TtsResult | null;
  revisionId?: string;
}

export interface DubItem {
  id: string;
  start: number;
  end: number;
  slot: number;
  srcText: string;
  text: string;
  voice: string | null;
  status: "pending" | "retry" | "ok" | "sped" | "too_long" | "failed";
  speed: number;
  duration: number | null;
  finalDuration: number | null;
  audio: string | null;
  shortened: boolean;
  note: string | null;
}

export interface DubResult {
  audio: string;
  video: string | null;
  subtitles: string;
  background: boolean;
  duration: number;
  stats: Record<string, number>;
}

export interface DubState {
  options: { targetLang: string | null; voice: string | null; maxSpeed: number; keepBackground: boolean; backgroundGain: number; format: "wav" | "mp3"; minGap: number };
  plan: { targetLang: string; sourceLang: string | null; items: DubItem[] } | null;
  result: DubResult | null;
}

export class AudioApi {
  constructor(private api: Api) {}

  engines = () => this.api.req<EngineInfo[]>("/tts/engines");
  voices = (lang?: string) => this.api.req<VoiceInfo[]>(`/voices${lang ? `?lang=${encodeURIComponent(lang)}` : ""}`);
  createConsent = (subject: string, confirmed: boolean) =>
    this.api.req<ConsentRecord>("/consents", { method: "POST", body: JSON.stringify({ kind: "voice", subject, confirmed }) });
  cloneVoice = (file: File, name: string, consentId: string) =>
    this.api.req<VoiceInfo>(`/voices/clone?name=${encodeURIComponent(name)}&consentId=${encodeURIComponent(consentId)}`, {
      method: "PUT", body: file, headers: { "Content-Type": "application/octet-stream" },
    });
  deleteVoice = (id: string) => this.api.req<void>(`/voices/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export class TtsApi {
  constructor(private api: Api, private pid: string) {}
  private base = () => `/projects/${this.pid}`;
  state = () => this.api.req<{ revision: number; state: TtsState | Record<string, never> }>(`${this.base()}/tools/tts/state`);
  command = (type: string, payload: object) =>
    this.api.req<ToolStateResponse>(`${this.base()}/tools/tts/commands`, { method: "POST", body: JSON.stringify({ type, payload }) });
  synthesize = () => this.api.req<Job>(`${this.base()}/tts/synthesize`, { method: "POST" });
  preview = (voice: string, text: string, lang: string) =>
    this.api.req<Job>(`${this.base()}/tts/preview`, { method: "POST", body: JSON.stringify({ voice, text, lang }) });
  fileUrl = async (path: string) => `${this.api.conn.address}${(await this.api.req<{ url: string }>(`${this.base()}/file-url`, { method: "POST", body: JSON.stringify({ path }) })).url}`;
  job = (id: string) => this.api.req<Job>(`/jobs/${id}`);
}

export class DubbingApi {
  constructor(private api: Api, private pid: string) {}
  private base = () => `/projects/${this.pid}`;
  state = () => this.api.req<{ revision: number; state: DubState | Record<string, never> }>(`${this.base()}/tools/dubbing/state`);
  subtitles = () => this.api.req<{ revision: number; state: SubtitleState | Record<string, never> }>(`${this.base()}/tools/subtitles/state`);
  command = (type: string, payload: object) =>
    this.api.req<ToolStateResponse>(`${this.base()}/tools/dubbing/commands`, { method: "POST", body: JSON.stringify({ type, payload }) });
  plan = () => this.api.req<ToolStateResponse>(`${this.base()}/dubbing/plan`, { method: "POST" });
  synthesize = () => this.api.req<Job>(`${this.base()}/dubbing/synthesize`, { method: "POST" });
  mix = () => this.api.req<Job>(`${this.base()}/dubbing/mix`, { method: "POST" });
  fileUrl = async (path: string) => `${this.api.conn.address}${(await this.api.req<{ url: string }>(`${this.base()}/file-url`, { method: "POST", body: JSON.stringify({ path }) })).url}`;
}
