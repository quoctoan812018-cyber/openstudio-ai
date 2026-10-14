import type { Job } from "@openstudio/protocol";
import { Api } from "./client";
import type { SubtitleState, ToolStateResponse } from "./subtitles";

// ---------- Highlights ----------
export interface Clip {
  id: string;
  start: number;
  end: number;
  title: string;
  hook: string;
  score: number | null;
  heuristic?: number | null;
  llm?: number | null;
  reason: string;
  selected: boolean;
  manual?: boolean;
  text?: string;
}

export interface HighlightsState {
  options: {
    count: number; minLen: number; maxLen: number; layout: "vertical" | "horizontal"; fit: "crop" | "pad"; subtitleLang: string | null;
    hookOverlay: boolean; useLlm: boolean; narrationLang: string | null; voice: string | null;
  };
  analysis: { windows: number; scored: number; llm: boolean; scenes: number; lang: string } | null;
  clips: Clip[];
  results: Record<string, string>;
  summary: {
    path: string; script: string; duration: number; lang: string;
    narrations: { clipId: string; text: string; start: number; dur: number; llm: boolean }[];
  } | null;
}

export class HighlightsApi {
  constructor(private api: Api, private pid: string) {}
  private base = () => `/projects/${this.pid}`;
  state = () => this.api.req<{ revision: number; state: HighlightsState | Record<string, never> }>(`${this.base()}/tools/highlights/state`);
  subtitles = () => this.api.req<{ revision: number; state: SubtitleState | Record<string, never> }>(`${this.base()}/tools/subtitles/state`);
  command = (type: string, payload: object) =>
    this.api.req<ToolStateResponse>(`${this.base()}/tools/highlights/commands`, { method: "POST", body: JSON.stringify({ type, payload }) });
  analyze = () => this.api.req<Job>(`${this.base()}/highlights/analyze`, { method: "POST" });
  exportClips = (ids?: string[]) => this.api.req<Job>(`${this.base()}/highlights/export`, { method: "POST", body: JSON.stringify({ ids: ids ?? null }) });
  summary = () => this.api.req<Job>(`${this.base()}/highlights/summary`, { method: "POST" });
  fileUrl = async (path: string) => `${this.api.conn.address}${(await this.api.req<{ url: string }>(`${this.base()}/file-url`, { method: "POST", body: JSON.stringify({ path }) })).url}`;
}

// ---------- Podcast ----------
export interface Host { name: string; voice: string | null }
export interface PodcastScript {
  title: string; summary: string; takeaways: string[];
  sections: { title: string; turns: { speaker: string; text: string }[] }[];
}
export interface MusicItem { id: string; name: string; kind: string; license: string; builtin?: boolean; duration?: number }
export interface PodcastState {
  brief: { topic: string; sourceText: string; sourceName: string | null; language: string; minutes: number; style: string; hosts: Host[] };
  script: PodcastScript | null;
  music: { intro: string | null; outro: string | null; bed: string | null; bedGain: number };
  options: { format: "mp3" | "wav"; video: boolean; layout: "horizontal" | "vertical"; gap: number; speed: number };
  result: {
    audio: string; video: string | null; notes: string; chapters: string; duration: number;
    chapterList: { title: string; start: number }[]; turns: number;
  } | null;
}

export class PodcastApi {
  constructor(private api: Api, private pid: string) {}
  private base = () => `/projects/${this.pid}`;
  state = () => this.api.req<{ revision: number; state: PodcastState | Record<string, never> }>(`${this.base()}/tools/podcast/state`);
  command = (type: string, payload: object) =>
    this.api.req<ToolStateResponse>(`${this.base()}/tools/podcast/commands`, { method: "POST", body: JSON.stringify({ type, payload }) });
  script = () => this.api.req<Job>(`${this.base()}/podcast/script`, { method: "POST" });
  produce = () => this.api.req<Job>(`${this.base()}/podcast/produce`, { method: "POST" });
  fileUrl = async (path: string) => `${this.api.conn.address}${(await this.api.req<{ url: string }>(`${this.base()}/file-url`, { method: "POST", body: JSON.stringify({ path }) })).url}`;
}

export class MusicApi {
  constructor(private api: Api) {}
  list = () => this.api.req<MusicItem[]>("/music");
  add = (file: File, name: string, kind: string, license: string) =>
    this.api.req<MusicItem>(`/music?name=${encodeURIComponent(name)}&kind=${encodeURIComponent(kind)}&license=${encodeURIComponent(license)}`, {
      method: "PUT", body: file, headers: { "Content-Type": "application/octet-stream" },
    });
  remove = (id: string) => this.api.req<void>(`/music/${encodeURIComponent(id)}`, { method: "DELETE" });
}

// ---------- Chiến dịch ----------
export interface CampaignBrief {
  goal: string; product: string; facts: string; markets: string[]; platforms: string[]; days: 7 | 14 | 30; startDate: string | null;
  language: string; tone: string; priceVnd: number | null; fx: Record<string, number>;
}
export type PostStatus = "planned" | "ready" | "approved" | "posted" | "failed";
export interface CampaignPost {
  id: string; day: number; date: string; time: string; market: string; platform: string; format: string; title: string; hook: string;
  caption: string; hashtags: string[]; script: string; thumbnailText: string; thumbnail: string | null; subtitles: string | null;
  video: string | null; status: PostStatus; note: string;
}
export interface CampaignState {
  brief: CampaignBrief;
  plan: { summary: string; warnings: string[]; startDate: string } | null;
  posts: CampaignPost[];
  export: { folder: string; csv: string; zip: string; posts: number; files: number } | null;
}
export interface CampaignCatalog {
  markets: Record<string, { name: string; lang: string; currency: string; tz: string }>;
  platforms: Record<string, { name: string; formats: string[] }>;
}

export class CampaignApi {
  constructor(private api: Api, private pid: string) {}
  private base = () => `/projects/${this.pid}`;
  catalog = () => this.api.req<CampaignCatalog>("/campaign/catalog");
  state = () => this.api.req<{ revision: number; state: CampaignState | Record<string, never> }>(`${this.base()}/tools/campaign/state`);
  command = (type: string, payload: object) =>
    this.api.req<ToolStateResponse>(`${this.base()}/tools/campaign/commands`, { method: "POST", body: JSON.stringify({ type, payload }) });
  plan = () => this.api.req<Job>(`${this.base()}/campaign/plan`, { method: "POST" });
  assets = (force = false) => this.api.req<Job>(`${this.base()}/campaign/assets`, { method: "POST", body: JSON.stringify({ force }) });
  exportPack = () => this.api.req<NonNullable<CampaignState["export"]>>(`${this.base()}/campaign/export`, { method: "POST", body: "{}" });
  fileUrl = async (path: string) => `${this.api.conn.address}${(await this.api.req<{ url: string }>(`${this.base()}/file-url`, { method: "POST", body: JSON.stringify({ path }) })).url}`;
}

// ---------- Kho tài nguyên, Chỉnh sửa, Thumbnail, Avatar, Template ----------
export interface Asset { id: string; name: string; path: string; kind: "video" | "image" | "audio"; duration: number; hasAudio: boolean; width: number | null; height: number | null }
export interface TemplateInfo { id: string; name: string; kind: "thumbnail" | "editor"; description?: string; builtin: boolean; hasPreview: boolean; [k: string]: unknown }

export class AssetsApi {
  constructor(private api: Api, private pid: string) {}
  private base = () => `/projects/${this.pid}`;
  list = () => this.api.req<Asset[]>(`${this.base()}/assets`);
  upload = (file: File) =>
    this.api.req<Asset>(`${this.base()}/assets?filename=${encodeURIComponent(file.name)}`, { method: "PUT", body: file, headers: { "Content-Type": "application/octet-stream" } });
  register = (path: string, name?: string) => this.api.req<Asset>(`${this.base()}/assets/register`, { method: "POST", body: JSON.stringify({ path, name }) });
  remove = (id: string) => this.api.req<void>(`${this.base()}/assets/${id}`, { method: "DELETE" });
  fileUrl = async (path: string) => `${this.api.conn.address}${(await this.api.req<{ url: string }>(`${this.base()}/file-url`, { method: "POST", body: JSON.stringify({ path }) })).url}`;
}

export class TemplatesApi {
  constructor(private api: Api) {}
  list = (kind?: string) => this.api.req<TemplateInfo[]>(`/templates${kind ? `?kind=${kind}` : ""}`);
  save = (name: string, kind: string, config: object) => this.api.req<TemplateInfo>("/templates", { method: "POST", body: JSON.stringify({ name, kind, config }) });
  remove = (id: string) => this.api.req<void>(`/templates/${id}`, { method: "DELETE" });
}

export interface Segment {
  id: string; asset: string; kind: "video" | "image"; name: string; srcDuration: number; hasAudio: boolean; in: number; out: number; duration: number;
  speed: number; volume: number; transition: { type: string; duration: number };
}
export interface EditorText { id: string; text: string; start: number; end: number; position: "top" | "center" | "bottom"; size: number; color: string; bold: boolean }
export interface EditorOverlay { id: string; asset: string; kind: string; name: string; start: number; end: number; x: number; y: number; width: number }
export interface EditorState {
  settings: { aspect: "16:9" | "9:16" | "1:1"; quality: number; fps: number; fit: "pad" | "crop" };
  segments: Segment[]; texts: EditorText[]; overlays: EditorOverlay[];
  music: { asset: string | null; name?: string; volumeDb: number; duck: boolean; fadeOut: number };
  result: { path: string; duration: number; bytes: number } | null; preview: { path: string; duration: number; bytes: number } | null;
}

export class EditorApi {
  constructor(private api: Api, private pid: string) {}
  private base = () => `/projects/${this.pid}`;
  state = () => this.api.req<{ revision: number; state: EditorState | Record<string, never> }>(`${this.base()}/tools/editor/state`);
  command = (type: string, payload: object) =>
    this.api.req<ToolStateResponse>(`${this.base()}/tools/editor/commands`, { method: "POST", body: JSON.stringify({ type, payload }) });
  attach = (kind: "segment" | "overlay" | "music", assetId: string, params: object = {}) =>
    this.api.req<ToolStateResponse>(`${this.base()}/editor/attach`, { method: "POST", body: JSON.stringify({ kind, assetId, params }) });
  render = (preview: boolean) => this.api.req<Job>(`${this.base()}/editor/render`, { method: "POST", body: JSON.stringify({ preview }) });
}

export interface ThumbBrief {
  title: string; subtitle: string; aspect: "16:9" | "9:16" | "1:1"; layouts: string[]; palettes: string[]; count: number;
  background: { kind: "gradient" | "asset" | "frame"; asset: string | null; at: number; dim: number }; brand: { asset: string | null; position: string; width: number };
}
export interface ThumbState { brief: ThumbBrief; variants: { id: string; file: string; layout: string; palette: string; width: number; height: number }[]; selected: string | null }

export class ThumbApi {
  constructor(private api: Api, private pid: string) {}
  private base = () => `/projects/${this.pid}`;
  state = () => this.api.req<{ revision: number; state: ThumbState | Record<string, never> }>(`${this.base()}/tools/thumbnail/state`);
  command = (type: string, payload: object) =>
    this.api.req<ToolStateResponse>(`${this.base()}/tools/thumbnail/commands`, { method: "POST", body: JSON.stringify({ type, payload }) });
  render = () => this.api.req<Job>(`${this.base()}/thumbnail/render`, { method: "POST" });
}

export interface AvatarInfo { id: string; name: string; realPerson: boolean; subject: string | null; consentId: string | null; mouth: { x: number; y: number; w: number }; width: number; height: number }
export interface AvatarEngine { id: string; name: string; available: boolean; implemented: boolean; realLipSync: boolean; minTier: string; note: string }
export interface AvatarState {
  brief: { avatar: string | null; audio: string | null; aspect: "16:9" | "9:16" | "1:1"; background: { kind: "blur" | "color" | "image"; color: string; asset: string | null };
    frame: "none" | "rounded" | "circle"; border: boolean; subtitleLang: string | null; engine: "puppet" };
  result: { path: string; duration: number; aspect: string; warnings: string[] } | null;
}

export class AvatarApi {
  constructor(private api: Api, private pid: string) {}
  private base = () => `/projects/${this.pid}`;
  state = () => this.api.req<{ revision: number; state: AvatarState | Record<string, never> }>(`${this.base()}/tools/avatar/state`);
  command = (type: string, payload: object) =>
    this.api.req<ToolStateResponse>(`${this.base()}/tools/avatar/commands`, { method: "POST", body: JSON.stringify({ type, payload }) });
  render = () => this.api.req<Job>(`${this.base()}/avatar/render`, { method: "POST" });
}

export class AvatarLibraryApi {
  constructor(private api: Api) {}
  list = () => this.api.req<AvatarInfo[]>("/avatars");
  engines = () => this.api.req<AvatarEngine[]>("/avatar/engines");
  createConsent = (subject: string) => this.api.req<{ id: string }>("/consents", { method: "POST", body: JSON.stringify({ kind: "face", subject, confirmed: true }) });
  create = (file: File, name: string, realPerson: boolean, consentId: string | null) =>
    this.api.req<AvatarInfo>(`/avatars?name=${encodeURIComponent(name)}&realPerson=${realPerson}${consentId ? `&consentId=${consentId}` : ""}`,
      { method: "PUT", body: file, headers: { "Content-Type": "application/octet-stream" } });
  setMouth = (id: string, mouth: { x: number; y: number; w: number }) => this.api.req<AvatarInfo>(`/avatars/${id}`, { method: "PATCH", body: JSON.stringify({ mouth }) });
  remove = (id: string) => this.api.req<void>(`/avatars/${id}`, { method: "DELETE" });
  /** Ảnh avatar cần Bearer → tải thành blob URL (không đưa token vào URL). */
  imageUrl = async (id: string) => {
    const r = await fetch(`${this.api.conn.address}/avatars/${id}/image`, { headers: { Authorization: `Bearer ${this.api.conn.token}` } });
    if (!r.ok) throw new Error("avatar image");
    return URL.createObjectURL(await r.blob());
  };
}

// ---------- Tạo ảnh AI & Tạo video (ảnh → chuyển động) ----------
export interface ImageStatus { engine: string | null; engineInstalled: boolean; model: string; modelInstalled: boolean; supported: boolean; device: string; note: string }
export interface ImageBrief { prompt: string; aspect: string; quality: "draft" | "standard" | "high"; count: number; seed: number | null; refAsset: string | null; translate: boolean; language: string }
export interface ImageResult { id: string; file: string; assetId: string; seed: number; width: number; height: number; prompt: string; seconds: number }
export interface ImageState { brief: ImageBrief; results: ImageResult[]; last: { warnings: string[]; englishPrompt: string } | null }

export class ImageApi {
  constructor(private api: Api, private pid: string) {}
  private base = () => `/projects/${this.pid}`;
  status = () => this.api.req<ImageStatus>("/image/status");
  state = () => this.api.req<{ revision: number; state: ImageState | Record<string, never> }>(`${this.base()}/tools/image/state`);
  command = (type: string, payload: object) =>
    this.api.req<ToolStateResponse>(`${this.base()}/tools/image/commands`, { method: "POST", body: JSON.stringify({ type, payload }) });
  generate = () => this.api.req<Job>(`${this.base()}/image/generate`, { method: "POST" });
}

export interface VideoBrief { asset: string | null; duration: number; preset: string; aspect: string; quality: number; fps: number; audio: string | null; strength: number }
export interface VideoState { brief: VideoBrief; result: { path: string; assetId: string; duration: number; preset: string; generative: boolean } | null }
export interface VideoEngine { id: string; name: string; available: boolean; implemented: boolean; generative: boolean; note: string }

export class VideoApi {
  constructor(private api: Api, private pid: string) {}
  private base = () => `/projects/${this.pid}`;
  engines = () => this.api.req<VideoEngine[]>("/video/engines");
  state = () => this.api.req<{ revision: number; state: VideoState | Record<string, never> }>(`${this.base()}/tools/video/state`);
  command = (type: string, payload: object) =>
    this.api.req<ToolStateResponse>(`${this.base()}/tools/video/commands`, { method: "POST", body: JSON.stringify({ type, payload }) });
  render = () => this.api.req<Job>(`${this.base()}/video/render`, { method: "POST" });
}
