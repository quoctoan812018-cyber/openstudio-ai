import type { ModelInfo, Tool } from "@openstudio/protocol";
import { render, screen } from "@testing-library/react";
import { parseSse } from "./api/sse";
import { formatBytes } from "./format";
import en from "./i18n/en.json";
import { I18nProvider, translate } from "./i18n";
import vi from "./i18n/vi.json";
import { ToolCard } from "./pages/Dashboard";
import { ModelRow } from "./pages/Settings";

const tool = (over: Partial<Tool>): Tool => ({
  id: "x", name: "Công cụ X", description: "mô tả", min_tier: "cpu", phase: 2,
  implemented: false, available: true, locked_reason: null, ...over,
});

describe("parseSse", () => {
  it("tách sự kiện đầy đủ, giữ phần dư và bỏ qua heartbeat", () => {
    const ev = { id: 1, type: "job.started", ts: 1, data: {} };
    const buf = `: ping\n\nid: 1\nevent: job.started\ndata: ${JSON.stringify(ev)}\n\nid: 2\nevent: x\ndata: {"id`;
    const { events, rest } = parseSse(buf);
    expect(events).toEqual([ev]);
    expect(rest.startsWith("id: 2")).toBe(true);
  });
  it("bỏ qua khối JSON hỏng", () => {
    expect(parseSse("data: {oops\n\n").events).toEqual([]);
  });
});

describe("i18n", () => {
  it("vi và en có cùng bộ khoá", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(vi).sort());
  });
  it("thay biến", () => {
    expect(translate("vi", "dashboard.soon", { phase: 3 })).toBe("Sắp có (giai đoạn 3)");
  });
  it("khoá thiếu trả về chính khoá", () => {
    expect(translate("en", "no.such.key")).toBe("no.such.key");
  });
});

describe("formatBytes", () => {
  it("định dạng", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(75538270)).toBe("72.0 MB");
    expect(formatBytes(null)).toBe("—");
  });
});

describe("ToolCard", () => {
  it("công cụ bị khoá hiện lý do", () => {
    render(<I18nProvider initial="vi"><ToolCard tool={tool({ available: false, locked_reason: "Cần GPU 16GB+" })} /></I18nProvider>);
    expect(screen.getByText("Bị khoá")).toBeInTheDocument();
    expect(screen.getByText("Cần GPU 16GB+")).toBeInTheDocument();
  });
  it("công cụ chưa làm hiện giai đoạn", () => {
    render(<I18nProvider initial="vi"><ToolCard tool={tool({ phase: 5 })} /></I18nProvider>);
    expect(screen.getByText("Sắp có (giai đoạn 5)")).toBeInTheDocument();
  });
});

describe("ModelRow", () => {
  const model: ModelInfo = {
    id: "f5-tts", name: "F5-TTS", capability: "tts", role: "excluded", non_commercial: true, verified: true,
    warning: "Mô hình này có license phi thương mại", downloadable: true, status: "not_installed",
    weights_license: "CC-BY-NC-4.0",
  };
  it("hiện cờ phi thương mại và cảnh báo", () => {
    render(<I18nProvider initial="vi"><ul><ModelRow m={model} onDownload={() => {}} onDelete={() => {}} /></ul></I18nProvider>);
    expect(screen.getByText("Phi thương mại")).toBeInTheDocument();
    expect(screen.getByText(/phi thương mại/i, { selector: "p" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tải" })).toBeInTheDocument();
  });
});
