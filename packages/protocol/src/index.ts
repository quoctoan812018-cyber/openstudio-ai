/* AUTO-GENERATED từ Pydantic (pnpm protocol:gen). KHÔNG sửa tay. */

export interface OpenStudioProtocol {
  ApiErrorResponse?: ApiErrorResponse;
  Progress?: Progress;
  Job?: Job;
  Event?: Event;
  Hardware?: Hardware;
  Tool?: Tool;
  ModelInfo?: ModelInfo;
  Project?: Project;
  ProjectCreate?: ProjectCreate;
  ToolCommand?: ToolCommand;
  JobCreate?: JobCreate;
  ModelDownloadRequest?: ModelDownloadRequest;
  UserSettings?: UserSettings;
  LibraryFile?: LibraryFile;
}
/**
 * This interface was referenced by `OpenStudioProtocol`'s JSON-Schema
 * via the `definition` "ApiErrorResponse".
 */
export interface ApiErrorResponse {
  error: ApiErrorBody;
}
/**
 * This interface was referenced by `OpenStudioProtocol`'s JSON-Schema
 * via the `definition` "ApiErrorBody".
 */
export interface ApiErrorBody {
  code: string;
  message: string;
  details?: {
    [k: string]: unknown;
  } | null;
}
/**
 * This interface was referenced by `OpenStudioProtocol`'s JSON-Schema
 * via the `definition` "Progress".
 */
export interface Progress {
  phase: string;
  percent: number;
  message?: string;
  completed?: number;
  failed?: number;
  total?: number;
}
/**
 * This interface was referenced by `OpenStudioProtocol`'s JSON-Schema
 * via the `definition` "Job".
 */
export interface Job {
  id: string;
  projectId?: string | null;
  tool?: string | null;
  type: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress?: Progress | null;
  error?: ApiErrorBody | null;
  result?: {
    [k: string]: unknown;
  } | null;
  createdAt: number;
  startedAt?: number | null;
  finishedAt?: number | null;
}
/**
 * This interface was referenced by `OpenStudioProtocol`'s JSON-Schema
 * via the `definition` "Event".
 */
export interface Event {
  id: number;
  type: string;
  projectId?: string | null;
  jobId?: string | null;
  ts: number;
  data?: {
    [k: string]: unknown;
  };
}
/**
 * This interface was referenced by `OpenStudioProtocol`'s JSON-Schema
 * via the `definition` "Hardware".
 */
export interface Hardware {
  os: string;
  cpu: {
    [k: string]: unknown;
  };
  ram_gb: number;
  gpus: Gpu[];
  cuda_available: boolean;
  tier: "cpu" | "gpu8" | "gpu12" | "gpu16plus";
  tier_label: string;
  note?: string | null;
}
/**
 * This interface was referenced by `OpenStudioProtocol`'s JSON-Schema
 * via the `definition` "Gpu".
 */
export interface Gpu {
  name: string;
  vram_gb: number;
  driver?: string | null;
  vendor: string;
}
/**
 * This interface was referenced by `OpenStudioProtocol`'s JSON-Schema
 * via the `definition` "Tool".
 */
export interface Tool {
  id: string;
  name: string;
  description: string;
  min_tier: "cpu" | "gpu8" | "gpu12" | "gpu16plus";
  phase: number;
  implemented: boolean;
  available: boolean;
  locked_reason?: string | null;
}
/**
 * This interface was referenced by `OpenStudioProtocol`'s JSON-Schema
 * via the `definition` "ModelInfo".
 */
export interface ModelInfo {
  id: string;
  name: string;
  capability: string;
  role: string;
  tier?: string | null;
  code_license?: string | null;
  weights_license?: string | null;
  commercial_ok?: boolean | string | null;
  non_commercial: boolean;
  verified: boolean;
  notes?: string | null;
  warning?: string | null;
  downloadable: boolean;
  size_bytes?: number | null;
  status: "not_installed" | "downloading" | "installed";
  downloadJobId?: string | null;
}
/**
 * This interface was referenced by `OpenStudioProtocol`'s JSON-Schema
 * via the `definition` "Project".
 */
export interface Project {
  id: string;
  name: string;
  createdAt: number;
  settings?: {
    [k: string]: unknown;
  };
}
/**
 * This interface was referenced by `OpenStudioProtocol`'s JSON-Schema
 * via the `definition` "ProjectCreate".
 */
export interface ProjectCreate {
  name: string;
}
/**
 * This interface was referenced by `OpenStudioProtocol`'s JSON-Schema
 * via the `definition` "ToolCommand".
 */
export interface ToolCommand {
  type: string;
  payload?: {
    [k: string]: unknown;
  };
  expectedRevision?: number | null;
}
/**
 * This interface was referenced by `OpenStudioProtocol`'s JSON-Schema
 * via the `definition` "JobCreate".
 */
export interface JobCreate {
  type: "demo.sleep";
  params?: {
    [k: string]: unknown;
  };
  projectId?: string | null;
}
/**
 * This interface was referenced by `OpenStudioProtocol`'s JSON-Schema
 * via the `definition` "ModelDownloadRequest".
 */
export interface ModelDownloadRequest {
  acknowledge_non_commercial?: boolean;
}
/**
 * This interface was referenced by `OpenStudioProtocol`'s JSON-Schema
 * via the `definition` "UserSettings".
 */
export interface UserSettings {
  language?: "vi" | "en";
  ai_label_metadata?: boolean;
  ai_label_watermark?: boolean;
  cloud_providers_enabled?: boolean;
}
/**
 * This interface was referenced by `OpenStudioProtocol`'s JSON-Schema
 * via the `definition` "LibraryFile".
 */
export interface LibraryFile {
  projectId: string;
  path: string;
  bytes: number;
  modifiedAt: number;
  kind: string;
}
