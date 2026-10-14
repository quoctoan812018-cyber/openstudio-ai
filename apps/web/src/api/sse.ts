import type { Event } from "@openstudio/protocol";

/** Tách các khối SSE hoàn chỉnh khỏi buffer; trả về sự kiện và phần dư chưa đủ khối. */
export function parseSse(buffer: string): { events: Event[]; rest: string } {
  const events: Event[] = [];
  const blocks = buffer.split(/\r?\n\r?\n/);
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    const dataLines = block
      .split(/\r?\n/)
      .filter((l) => l.startsWith("data:"))
      .map((l) => l.slice(5).trimStart());
    if (!dataLines.length) continue; // heartbeat ": ping"
    try {
      events.push(JSON.parse(dataLines.join("\n")) as Event);
    } catch {
      /* bỏ qua khối hỏng */
    }
  }
  return { events, rest };
}

export interface Connection {
  address: string;
  token: string;
}

/** Đăng ký SSE bằng fetch (EventSource không gửi được header Authorization). Tự nối lại với Last-Event-ID. */
export function subscribeEvents(
  conn: Connection,
  params: { projectId?: string; jobId?: string },
  onEvent: (e: Event) => void,
  signal: AbortSignal,
): void {
  let lastId = 0;
  const run = async () => {
    while (!signal.aborted) {
      try {
        const q = new URLSearchParams();
        if (params.projectId) q.set("projectId", params.projectId);
        if (params.jobId) q.set("jobId", params.jobId);
        if (lastId) q.set("lastEventId", String(lastId));
        const res = await fetch(`${conn.address}/events?${q}`, {
          headers: { Authorization: `Bearer ${conn.token}` },
          signal,
        });
        if (!res.ok || !res.body) throw new Error(`SSE ${res.status}`);
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          const { events, rest } = parseSse(buf);
          buf = rest;
          for (const ev of events) {
            lastId = Math.max(lastId, ev.id);
            onEvent(ev);
          }
        }
      } catch {
        if (signal.aborted) return;
      }
      await new Promise((r) => setTimeout(r, 1500));
    }
  };
  void run();
}
