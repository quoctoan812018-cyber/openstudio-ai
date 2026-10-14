import { fireEvent, render, screen } from "@testing-library/react";
import type { CampaignPost, Clip, PodcastScript, Segment } from "./api/studio";
import { I18nProvider } from "./i18n";
import { canCreateAvatar } from "./pages/Avatar";
import { PostRow } from "./pages/Campaign";
import { SegmentRow, totalLength } from "./pages/Editor";
import { ClipCard } from "./pages/Highlights";
import { ScriptEditor } from "./pages/Podcast";

const wrap = (ui: React.ReactNode) => render(<I18nProvider initial="vi">{ui}</I18nProvider>);

describe("ClipCard", () => {
  const clip: Clip = { id: "c001", start: 30, end: 62, title: "Bí mật nước 92 độ", hook: "Đừng dùng nước sôi!", score: 8.1, llm: 9, heuristic: 5, reason: "Hook mạnh", selected: true, text: "Bí mật của…" };

  it("hiện điểm LLM, thời lượng, lý do và nhãn khi là clip thủ công", () => {
    wrap(<ul><ClipCard clip={{ ...clip, manual: true }} onEdit={() => {}} onPreview={() => {}} /></ul>);
    expect(screen.getByText(/Điểm 8\.1 \(LLM 9\)/)).toBeInTheDocument();
    expect(screen.getByText("32s")).toBeInTheDocument();
    expect(screen.getByText("Hook mạnh")).toBeInTheDocument();
    expect(screen.getByText("thủ công")).toBeInTheDocument();
  });

  it("clip chưa có LLM hiện nhãn heuristic", () => {
    wrap(<ul><ClipCard clip={{ ...clip, llm: null }} onEdit={() => {}} onPreview={() => {}} /></ul>);
    expect(screen.getByText(/\(heuristic\)/)).toBeInTheDocument();
  });

  it("chỉ gửi chỉnh sửa khi giá trị thật sự đổi", () => {
    const onEdit = vi.fn();
    wrap(<ul><ClipCard clip={clip} onEdit={onEdit} onPreview={() => {}} /></ul>);
    const title = screen.getByLabelText("Tiêu đề clip c001");
    fireEvent.blur(title);
    expect(onEdit).not.toHaveBeenCalled();
    fireEvent.change(title, { target: { value: "Tiêu đề mới" } });
    fireEvent.blur(title);
    expect(onEdit).toHaveBeenCalledWith({ title: "Tiêu đề mới" });
    fireEvent.click(screen.getByLabelText("Chọn c001"));
    expect(onEdit).toHaveBeenLastCalledWith({ selected: false });
    const end = screen.getByLabelText("Kết thúc c001");
    fireEvent.change(end, { target: { value: "01:10" } });
    fireEvent.blur(end);
    expect(onEdit).toHaveBeenLastCalledWith({ end: 70 });
  });

  it("xem thử, và link tải chỉ hiện khi đã xuất", () => {
    const onPreview = vi.fn();
    const { rerender } = wrap(<ul><ClipCard clip={clip} onEdit={() => {}} onPreview={onPreview} /></ul>);
    expect(screen.queryByText("Tải clip")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Xem thử" }));
    expect(onPreview).toHaveBeenCalled();
    rerender(<I18nProvider initial="vi"><ul><ClipCard clip={clip} resultUrl="http://x/y.mp4" onEdit={() => {}} onPreview={onPreview} /></ul></I18nProvider>);
    expect(screen.getByText("Tải clip")).toHaveAttribute("href", "http://x/y.mp4");
  });
});

describe("Podcast ScriptEditor", () => {
  const script: PodcastScript = {
    title: "Cà phê Việt", summary: "Tóm tắt", takeaways: [],
    sections: [{ title: "Mở đầu", turns: [{ speaker: "Minh", text: "Xin chào" }, { speaker: "Lan", text: "Chào Minh" }] }],
  };

  it("nút lưu chỉ bật khi có thay đổi hợp lệ", () => {
    const onSave = vi.fn();
    wrap(<ScriptEditor script={script} hosts={["Minh", "Lan"]} onSave={onSave} />);
    const save = screen.getByRole("button", { name: "Lưu kịch bản" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Nội dung 1.1"), { target: { value: "Xin chào các bạn" } });
    expect(save).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Nội dung 1.2"), { target: { value: "   " } });
    expect(save).toBeDisabled();                       // lượt nói rỗng → không cho lưu
    fireEvent.change(screen.getByLabelText("Nội dung 1.2"), { target: { value: "Chào" } });
    fireEvent.click(save);
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ sections: [{ title: "Mở đầu", turns: [{ speaker: "Minh", text: "Xin chào các bạn" }, { speaker: "Lan", text: "Chào" }] }] }));
  });

  it("đổi người nói, thêm và xoá lượt nói", () => {
    const onSave = vi.fn();
    wrap(<ScriptEditor script={script} hosts={["Minh", "Lan"]} onSave={onSave} />);
    fireEvent.change(screen.getByLabelText("Người nói 1.1"), { target: { value: "Lan" } });
    fireEvent.click(screen.getByText("+ Thêm lượt nói"));
    expect(screen.getByLabelText("Nội dung 1.3")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Nội dung 1.3"), { target: { value: "Hẹn gặp lại" } });
    fireEvent.click(screen.getAllByTitle("Xoá cue")[1]);        // xoá lượt thứ hai
    fireEvent.click(screen.getByRole("button", { name: "Lưu kịch bản" }));
    const saved = onSave.mock.calls[0][0] as PodcastScript;
    expect(saved.sections[0].turns.map((t) => `${t.speaker}:${t.text}`)).toEqual(["Lan:Xin chào", "Minh:Hẹn gặp lại"]);
  });
});

describe("Campaign PostRow", () => {
  const post: CampaignPost = {
    id: "p001", day: 1, date: "2030-03-04", time: "19:00", market: "us", platform: "tiktok", format: "short_video", title: "Coffee tip 1", hook: "",
    caption: "Brew it right", hashtags: ["coffee"], script: "", thumbnailText: "", thumbnail: "x.png", subtitles: null, video: null, status: "ready", note: "",
  };

  it("sửa caption chỉ gửi khi đổi; duyệt bài", () => {
    const onPatch = vi.fn();
    wrap(<ul><PostRow post={post} marketName="Hoa Kỳ" platformName="TikTok" onPatch={onPatch} /></ul>);
    const cap = screen.getByLabelText("Caption p001");
    fireEvent.blur(cap);
    expect(onPatch).not.toHaveBeenCalled();
    fireEvent.change(cap, { target: { value: "Brew it better" } });
    fireEvent.blur(cap);
    expect(onPatch).toHaveBeenCalledWith({ caption: "Brew it better" });
    fireEvent.click(screen.getByRole("button", { name: "Duyệt" }));
    expect(onPatch).toHaveBeenCalledWith({ status: "approved" });
  });

  it("bài mới lập kế hoạch chưa hiện caption và nút duyệt", () => {
    wrap(<ul><PostRow post={{ ...post, status: "planned", thumbnail: null }} marketName="Hoa Kỳ" platformName="TikTok" onPatch={() => {}} /></ul>);
    expect(screen.queryByLabelText("Caption p001")).toBeNull();
    expect(screen.queryByRole("button", { name: "Duyệt" })).toBeNull();
  });
});

describe("Editor SegmentRow", () => {
  const seg: Segment = { id: "s1", asset: "a1", kind: "video", name: "clip.mp4", srcDuration: 10, hasAudio: true, in: 0, out: 6, duration: 5, speed: 1, volume: 100, transition: { type: "none", duration: 0 } };

  it("tổng thời lượng trừ phần chồng của chuyển cảnh và chia theo tốc độ", () => {
    const b: Segment = { ...seg, id: "s2", speed: 2, transition: { type: "fade", duration: 0.5 } };
    expect(totalLength([seg, b])).toBeCloseTo(6 + 3 - 0.5);
  });

  it("chỉ gửi khi giá trị đổi; đổi tốc độ và chuyển cảnh; đoạn đầu không có chuyển cảnh", () => {
    const onUpdate = vi.fn();
    wrap(<ol><SegmentRow seg={seg} index={0} count={2} onUpdate={onUpdate} onMove={() => {}} onSplit={() => {}} onRemove={() => {}} /></ol>);
    const speed = screen.getByLabelText("Đoạn 1 speed");
    fireEvent.blur(speed);
    expect(onUpdate).not.toHaveBeenCalled();
    fireEvent.change(speed, { target: { value: "2" } });
    fireEvent.blur(speed);
    expect(onUpdate).toHaveBeenCalledWith({ speed: 2 });
    expect(screen.queryByLabelText("Đoạn 1 Chuyển cảnh")).toBeNull();
  });

  it("đoạn sau chọn chuyển cảnh; nút ↑ khoá ở đầu danh sách, cắt đôi ở giữa đoạn", () => {
    const onUpdate = vi.fn();
    const onSplit = vi.fn();
    wrap(<ol><SegmentRow seg={{ ...seg, id: "s2" }} index={1} count={2} onUpdate={onUpdate} onMove={() => {}} onSplit={onSplit} onRemove={() => {}} /></ol>);
    fireEvent.change(screen.getByLabelText("Đoạn 2 Chuyển cảnh"), { target: { value: "dissolve" } });
    expect(onUpdate).toHaveBeenCalledWith({ transition: { type: "dissolve", duration: 0.5 } });
    fireEvent.click(screen.getByRole("button", { name: "Cắt đôi" }));
    expect(onSplit).toHaveBeenCalledWith(3);
  });
});

describe("Avatar consent gating", () => {
  const file = new File(["x"], "a.png");
  it("ảnh người thật chỉ tạo được khi ghi tên và tick xác nhận", () => {
    expect(canCreateAvatar({ name: "A", file, realPerson: null, subject: "", confirmed: false })).toBe(false);   // chưa nói có phải người thật không
    expect(canCreateAvatar({ name: "A", file, realPerson: true, subject: "", confirmed: true })).toBe(false);
    expect(canCreateAvatar({ name: "A", file, realPerson: true, subject: "Lan", confirmed: false })).toBe(false);
    expect(canCreateAvatar({ name: "A", file, realPerson: true, subject: "Lan", confirmed: true })).toBe(true);
    expect(canCreateAvatar({ name: "A", file, realPerson: false, subject: "", confirmed: false })).toBe(true);
    expect(canCreateAvatar({ name: "A", file: null, realPerson: false, subject: "", confirmed: false })).toBe(false);
  });
});
