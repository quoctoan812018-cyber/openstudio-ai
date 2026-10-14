import type { Job } from "@openstudio/protocol";
import { Api } from "./client";

export interface Thread {
  id: string; projectId: string; title: string; createdAt: number; autoApprove: boolean; skill: string | null; runJobId: string | null;
}
export interface Msg {
  id: number; threadId: string; role: "user" | "assistant" | "tool"; createdAt: number;
  kind: "user" | "assistant" | "question" | "skill" | "tool_call" | "tool_result" | "approval" | "error";
  content: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
}
export interface Approval {
  id: string; threadId: string; jobId: string; status: "pending" | "approved" | "rejected" | "expired"; reason: string; tool: string;
  args: Record<string, unknown>; category: "render" | "download" | "external"; createdAt: number; decidedAt: number | null;
}
export interface ThreadView { thread: Thread; messages: Msg[]; pendingApprovals: Approval[]; run: Job | null }
export interface SkillInfo {
  name: string; description: string; tools: string[]; source: "builtin" | "user"; enabled: boolean; steps: string[]; warnings: string[]; body?: string;
}
export interface Schedule {
  id: string; projectId: string; skill: string | null; message: string; cron: string; enabled: boolean; autoApprove: boolean;
  lastRunAt: number | null; nextRunAt: number | null; lastThreadId: string | null;
}
export interface AgentToolInfo { name: string; description: string; approval: string | null; schema: Record<string, unknown> }

export class AgentApi {
  constructor(private api: Api) {}
  tools = () => this.api.req<AgentToolInfo[]>("/agent/tools");
  threads = (pid: string) => this.api.req<Thread[]>(`/projects/${pid}/threads`);
  createThread = (pid: string, body: { title?: string; skill?: string | null; autoApprove?: boolean } = {}) =>
    this.api.req<Thread>(`/projects/${pid}/threads`, { method: "POST", body: JSON.stringify(body) });
  thread = (id: string) => this.api.req<ThreadView>(`/threads/${id}`);
  patchThread = (id: string, body: { title?: string; autoApprove?: boolean; skill?: string }) =>
    this.api.req<Thread>(`/threads/${id}`, { method: "PATCH", body: JSON.stringify(body) });
  send = (id: string, text: string, skill?: string | null, autoApprove?: boolean) =>
    this.api.req<Job>(`/threads/${id}/messages`, { method: "POST", body: JSON.stringify({ text, skill: skill || null, autoApprove }) });
  cancel = (id: string) => this.api.req<unknown>(`/threads/${id}/cancel`, { method: "POST" });
  decide = (aid: string, decision: "approve" | "reject") => this.api.req<Approval>(`/approvals/${aid}`, { method: "POST", body: JSON.stringify({ decision }) });

  skills = () => this.api.req<SkillInfo[]>("/skills");
  skill = (name: string) => this.api.req<SkillInfo>(`/skills/${encodeURIComponent(name)}`);
  template = () => this.api.req<{ markdown: string }>("/skills/template");
  setSkillEnabled = (name: string, enabled: boolean) =>
    this.api.req<SkillInfo>(`/skills/${encodeURIComponent(name)}/enabled`, { method: "PUT", body: JSON.stringify({ enabled }) });
  createSkill = (markdown: string) => this.api.req<SkillInfo>("/skills", { method: "POST", body: JSON.stringify({ markdown }) });
  deleteSkill = (name: string) => this.api.req<void>(`/skills/${encodeURIComponent(name)}`, { method: "DELETE" });
  async exportSkill(name: string): Promise<string> {
    const res = await fetch(`${this.api.conn.address}/skills/${encodeURIComponent(name)}/export`, { headers: { Authorization: `Bearer ${this.api.conn.token}` } });
    if (!res.ok) throw new Error(String(res.status));
    return res.text();
  }

  schedules = (pid?: string) => this.api.req<Schedule[]>(`/schedules${pid ? `?projectId=${encodeURIComponent(pid)}` : ""}`);
  createSchedule = (body: { projectId: string; message: string; cron: string; skill?: string | null; autoApprove?: boolean }) =>
    this.api.req<Schedule>("/schedules", { method: "POST", body: JSON.stringify(body) });
  patchSchedule = (id: string, body: Partial<{ enabled: boolean; cron: string; message: string; autoApprove: boolean }>) =>
    this.api.req<Schedule>(`/schedules/${id}`, { method: "PATCH", body: JSON.stringify(body) });
  deleteSchedule = (id: string) => this.api.req<void>(`/schedules/${id}`, { method: "DELETE" });
  runNow = (id: string) => this.api.req<{ threadId: string }>(`/schedules/${id}/run-now`, { method: "POST" });
  fileUrl = async (pid: string, path: string) =>
    `${this.api.conn.address}${(await this.api.req<{ url: string }>(`/projects/${pid}/file-url`, { method: "POST", body: JSON.stringify({ path }) })).url}`;
}
