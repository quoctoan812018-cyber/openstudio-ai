import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { AudioApi, DubItem, VoiceInfo } from "./api/audio";
import { ApiRequestError } from "./api/client";
import { I18nProvider } from "./i18n";
import { parseSpeakers } from "./lib/script";
import { ItemRow } from "./pages/Dubbing";
import { CloneVoicePanel } from "./pages/TextToSpeech";

const wrap = (ui: React.ReactNode) => render(<I18nProvider initial="vi">{ui}</I18nProvider>);

describe("parseSpeakers (khớp quy tắc của daemon)", () => {
  it("nhiều người nói, dòng không thẻ, thẻ cảm xúc, thẻ nghỉ", () => {
    expect(parseSpeakers("Mở đầu\n[Người A] Xin chào\n[nghỉ 1s]\n[Người B] Chào!\n[cười] haha")).toEqual(["default", "Người A", "Người B"]);
    expect(parseSpeakers("[A] một [nghỉ 500ms] hai")).toEqual(["A"]);
    expect(parseSpeakers("  \n[nghỉ 2s]\n")).toEqual([]);
    expect(parseSpeakers("[pause 1s]\n[B] hi")).toEqual(["B"]);
  });
});

describe("CloneVoicePanel: bắt buộc xác nhận đồng ý", () => {
  const make = (over: Partial<Record<keyof AudioApi, unknown>> = {}) => ({
    createConsent: vi.fn().mockResolvedValue({ id: "cns_1" }),
    cloneVoice: vi.fn().mockResolvedValue({ id: "clone:vc_1" }),
    ...over,
  }) as unknown as AudioApi & { createConsent: ReturnType<typeof vi.fn>; cloneVoice: ReturnType<typeof vi.fn> };

  const fill = (checkbox: boolean) => {
    fireEvent.change(screen.getByLabelText("Tên giọng"), { target: { value: "Giọng của tôi" } });
    fireEvent.change(screen.getByLabelText("Tên người sở hữu giọng nói"), { target: { value: "Nguyễn Văn A" } });
    const file = new File([new Uint8Array(10)], "mau.wav", { type: "audio/wav" });
    fireEvent.change(screen.getByLabelText("Mẫu giọng"), { target: { files: [file] } });
    if (checkbox) fireEvent.click(screen.getByRole("checkbox"));
    return file;
  };

  it("nút tạo bị khoá cho tới khi tick xác nhận và điền đủ", () => {
    wrap(<CloneVoicePanel audio={make()} onCreated={() => {}} clones={[]} onDelete={() => {}} />);
    const button = screen.getByRole("button", { name: "Tạo giọng nhân bản" });
    expect(button).toBeDisabled();
    fill(false);
    expect(button).toBeDisabled(); // thiếu xác nhận
    fireEvent.click(screen.getByRole("checkbox"));
    expect(button).toBeEnabled();
  });

  it("ghi consent (confirmed=true) trước rồi mới nhân bản bằng id consent đó", async () => {
    const audio = make();
    const created = vi.fn();
    wrap(<CloneVoicePanel audio={audio} onCreated={created} clones={[]} onDelete={() => {}} />);
    const file = fill(true);
    fireEvent.click(screen.getByRole("button", { name: "Tạo giọng nhân bản" }));
    await waitFor(() => expect(created).toHaveBeenCalled());
    expect(audio.createConsent).toHaveBeenCalledWith("Nguyễn Văn A", true);
    expect(audio.cloneVoice).toHaveBeenCalledWith(file, "Giọng của tôi", "cns_1");
    expect(audio.createConsent.mock.invocationCallOrder[0]).toBeLessThan(audio.cloneVoice.mock.invocationCallOrder[0]);
  });

  it("hiện lỗi từ daemon và không báo thành công", async () => {
    const audio = make({ cloneVoice: vi.fn().mockRejectedValue(new ApiRequestError(400, "VALIDATION_FAILED", "Mẫu giọng phải dài 3–60 giây")) });
    const created = vi.fn();
    wrap(<CloneVoicePanel audio={audio} onCreated={created} clones={[]} onDelete={() => {}} />);
    fill(true);
    fireEvent.click(screen.getByRole("button", { name: "Tạo giọng nhân bản" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Mẫu giọng phải dài");
    expect(created).not.toHaveBeenCalled();
  });

  it("liệt kê giọng đã nhân bản và cho xoá", () => {
    const onDelete = vi.fn();
    const clone: VoiceInfo = { id: "clone:vc_9", name: "Giọng A", engine: "vieneu", lang: "vi", description: "9s mẫu", gender: "", kind: "clone" };
    wrap(<CloneVoicePanel audio={make()} onCreated={() => {}} clones={[clone]} onDelete={onDelete} />);
    fireEvent.click(screen.getByRole("button", { name: "Xoá" }));
    expect(onDelete).toHaveBeenCalledWith("clone:vc_9");
  });
});

describe("Dubbing ItemRow", () => {
  const item: DubItem = {
    id: "d0002", start: 6, end: 8, slot: 2.5, srcText: "Câu gốc", text: "Hello there", voice: null, status: "too_long", speed: 1.6,
    duration: 4.2, finalDuration: 2.63, audio: "a.wav", shortened: true, note: "Vẫn dài hơn khung thời gian; đã tăng tốc tối đa",
  };

  it("hiện trạng thái, tốc độ, nhãn rút gọn, cảnh báo vượt khung và ghi chú", () => {
    wrap(<ul><ItemRow it={item} voices={[]} onEdit={() => {}} /></ul>);
    expect(screen.getByText("Quá dài")).toBeInTheDocument();
    expect(screen.getByText("đã rút gọn")).toBeInTheDocument();
    expect(screen.getByText("vượt khung")).toBeInTheDocument();
    expect(screen.getByText(/×1\.60/)).toBeInTheDocument();
    expect(screen.getByText("Câu gốc")).toBeInTheDocument();
    expect(screen.getByText(/đã tăng tốc tối đa/)).toBeInTheDocument();
  });

  it("chỉ gửi chỉnh sửa khi nội dung thật sự đổi", () => {
    const onEdit = vi.fn();
    wrap(<ul><ItemRow it={item} voices={[]} onEdit={onEdit} /></ul>);
    const box = screen.getByLabelText("Nội dung d0002");
    fireEvent.blur(box);
    expect(onEdit).not.toHaveBeenCalled();
    fireEvent.change(box, { target: { value: "Hi" } });
    fireEvent.blur(box);
    expect(onEdit).toHaveBeenCalledWith("d0002", { text: "Hi" });
    fireEvent.change(box, { target: { value: "   " } });
    fireEvent.blur(box);
    expect(onEdit).toHaveBeenCalledTimes(1); // khoảng trắng không gửi
  });

  it("đổi giọng riêng cho câu", () => {
    const onEdit = vi.fn();
    const v: VoiceInfo = { id: "kokoro:am_adam", name: "am_adam", engine: "kokoro", lang: "en", description: "", gender: "male", kind: "preset" };
    wrap(<ul><ItemRow it={item} voices={[v]} onEdit={onEdit} /></ul>);
    fireEvent.change(screen.getByLabelText("Giọng d0002"), { target: { value: "kokoro:am_adam" } });
    expect(onEdit).toHaveBeenCalledWith("d0002", { voice: "kokoro:am_adam" });
  });
});
