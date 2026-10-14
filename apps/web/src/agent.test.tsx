import { fireEvent, render, screen } from "@testing-library/react";
import type { Approval, Msg, SkillInfo } from "./api/agent";
import { Api } from "./api/client";
import { ApiCtx } from "./api/connection";
import { I18nProvider } from "./i18n";
import { ApprovalCard, MessageView } from "./pages/Agent";
import { CRON_PRESETS, SkillRow, fmtWhen } from "./pages/Skills";

const api = new Api({ address: "http://127.0.0.1:1", token: "t" });
const wrap = (ui: React.ReactNode) => render(<I18nProvider initial="vi"><ApiCtx.Provider value={api}>{ui}</ApiCtx.Provider></I18nProvider>);
const msg = (kind: Msg["kind"], content: Msg["content"], role: Msg["role"] = "assistant"): Msg => ({ id: 1, threadId: "t", role, kind, content, createdAt: 0 });
const approval = (over: Partial<Approval> = {}): Approval => ({
  id: "apr_1", threadId: "t", jobId: "j", status: "pending", reason: "Bước này tạo/xuất file media nặng.", tool: "subtitles_burn",
  args: { lang: "vi" }, category: "render", createdAt: 0, decidedAt: null, ...over,
});

describe("ApprovalCard", () => {
  it("đang chờ: hiện tham số, lý do và hai nút", () => {
    const onDecide = vi.fn();
    wrap(<ApprovalCard a={approval()} onDecide={onDecide} />);
    expect(screen.getByText("Cần bạn duyệt: subtitles_burn")).toBeInTheDocument();
    expect(screen.getByText(/"lang": "vi"/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Duyệt" }));
    expect(onDecide).toHaveBeenLastCalledWith("approve");
    fireEvent.click(screen.getByRole("button", { name: "Từ chối" }));
    expect(onDecide).toHaveBeenLastCalledWith("reject");
  });

  it("đã quyết định thì không còn nút; tải mô hình ghi rõ không bao giờ tự duyệt", () => {
    const { rerender } = wrap(<ApprovalCard a={approval({ status: "approved" })} onDecide={() => {}} />);
    expect(screen.queryByRole("button", { name: "Duyệt" })).toBeNull();
    expect(screen.getByText("Đã duyệt")).toBeInTheDocument();
    rerender(<I18nProvider initial="vi"><ApiCtx.Provider value={api}><ApprovalCard a={approval({ category: "download", tool: "download_model" })} onDecide={() => {}} /></ApiCtx.Provider></I18nProvider>);
    expect(screen.getByText(/không bao giờ tự duyệt/)).toBeInTheDocument();
  });
});

describe("MessageView", () => {
  const noop = () => {};
  it("tin nhắn người dùng/trợ lý/câu hỏi hiển thị khác nhau", () => {
    wrap(<div>
      <MessageView m={msg("user", { text: "Dịch video" }, "user")} pid="p" onDecide={noop} />
      <MessageView m={msg("assistant", { text: "Đã xong." })} pid="p" onDecide={noop} />
      <MessageView m={msg("question", { text: "Bạn muốn ngôn ngữ nào?" })} pid="p" onDecide={noop} />
    </div>);
    expect(screen.getByText("Dịch video")).toBeInTheDocument();
    expect(screen.getByText("Đã xong.")).toBeInTheDocument();
    expect(screen.getByText(/Cần thêm thông tin:/)).toBeInTheDocument();
    expect(screen.getByText("Bạn muốn ngôn ngữ nào?", { exact: false })).toBeInTheDocument();
  });

  it("kết quả tool: ✓/✗, chi tiết thu gọn và nút mở file", () => {
    wrap(<div>
      <MessageView m={msg("tool_result", { tool: "subtitles_translate", ok: true, summary: { job: { status: "succeeded" } }, files: ["exports/a.en.srt"] }, "tool")} pid="p" onDecide={noop} />
      <MessageView m={msg("tool_result", { tool: "subtitles_burn", ok: false, summary: { error: { code: "NOT_APPROVED" } }, files: [] }, "tool")} pid="p" onDecide={noop} />
    </div>);
    expect(screen.getByText("✓")).toBeInTheDocument();
    expect(screen.getByText("✗")).toBeInTheDocument();
    expect(screen.getByTitle("exports/a.en.srt")).toHaveTextContent("a.en.srt");
  });

  it("thẻ phê duyệt dùng trạng thái mới nhất từ danh sách approvals", () => {
    const onDecide = vi.fn();
    wrap(<MessageView m={msg("approval", { approvalId: "apr_1" })} pid="p" approval={approval()} onDecide={onDecide} />);
    fireEvent.click(screen.getByRole("button", { name: "Duyệt" }));
    expect(onDecide).toHaveBeenCalledWith("apr_1", "approve");
  });

  it("lời gọi tool hiện tên + lý do ngắn", () => {
    wrap(<MessageView m={msg("tool_call", { tool: "get_state", args: { tool: "subtitles" }, thought: "kiểm tra nguồn" })} pid="p" onDecide={noop} />);
    expect(screen.getByText(/get_state/)).toBeInTheDocument();
    expect(screen.getByText(/kiểm tra nguồn/)).toBeInTheDocument();
  });
});

describe("Skills UI", () => {
  const skill: SkillInfo = { name: "youtube-to-shorts", description: "Cắt video dài thành clip ngắn", tools: ["get_state"], source: "builtin", enabled: true, steps: ["get_state"], warnings: [] };
  it("bật/tắt và chọn skill", () => {
    const onToggle = vi.fn();
    const onSelect = vi.fn();
    wrap(<ul><SkillRow s={skill} selected={false} onSelect={onSelect} onToggle={onToggle} /></ul>);
    expect(screen.getByText("có sẵn")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Bật youtube-to-shorts"));
    expect(onToggle).toHaveBeenCalledWith(false);
    fireEvent.click(screen.getByText("youtube-to-shorts"));
    expect(onSelect).toHaveBeenCalled();
  });

  it("cron mẫu hợp lệ 5 trường và định dạng thời gian", () => {
    for (const p of CRON_PRESETS.filter((x) => x.cron)) expect(p.cron.split(" ")).toHaveLength(5);
    expect(fmtWhen(null)).toBe("—");
    expect(fmtWhen(1_800_000_000)).toMatch(/\d/);
  });
});
