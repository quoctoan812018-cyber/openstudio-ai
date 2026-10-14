import { fireEvent, render, screen } from "@testing-library/react";
import { CueEditor } from "./components/CueEditor";
import { I18nProvider } from "./i18n";
import { activeIndex, fmtTime, mergeWithNext, parseTime, removeCue, shiftAll, splitCue, validateCues, type Cue } from "./lib/cues";

const cues: Cue[] = [
  { start: 0, end: 2, text: "Xin chào các bạn" },
  { start: 2.5, end: 4, text: "hôm nay học cà phê" },
];

describe("cue helpers", () => {
  it("định dạng và đọc thời gian", () => {
    expect(fmtTime(62.5)).toBe("01:02.500");
    expect(fmtTime(3723.456)).toBe("1:02:03.456");
    expect(parseTime("01:02.500")).toBeCloseTo(62.5);
    expect(parseTime("62.5")).toBeCloseTo(62.5);
    expect(parseTime("1:02:03,456")).toBeCloseTo(3723.456);
    expect(parseTime("abc")).toBeNull();
    expect(parseTime("")).toBeNull();
  });
  it("gộp cue", () => {
    const m = mergeWithNext(cues, 0);
    expect(m).toEqual([{ start: 0, end: 4, text: "Xin chào các bạn hôm nay học cà phê" }]);
    expect(mergeWithNext(cues, 1)).toBe(cues); // cue cuối không gộp được
  });
  it("tách cue theo tỉ lệ ký tự và không tách khi một nửa rỗng", () => {
    const s = splitCue(cues, 0, 8); // "Xin chào" | "các bạn"
    expect(s).toHaveLength(3);
    expect(s[0].text).toBe("Xin chào");
    expect(s[1].text).toBe("các bạn");
    expect(s[0].end).toBe(s[1].start);
    expect(s[0].end).toBeGreaterThan(0);
    expect(s[0].end).toBeLessThan(2);
    expect(splitCue(cues, 0, 0)).toBe(cues);
  });
  it("xoá, dời, tìm cue đang phát, kiểm tra chồng lấn", () => {
    expect(removeCue(cues, 0)).toHaveLength(1);
    expect(shiftAll(cues, -1)[0].start).toBe(0); // không âm
    expect(shiftAll(cues, 0.5)[1].start).toBe(3);
    expect(activeIndex(cues, 3)).toBe(1);
    expect(activeIndex(cues, 2.2)).toBe(-1);
    expect(validateCues(cues)).toEqual([]);
    expect(validateCues([cues[0], { start: 1, end: 3, text: "x" }])).toEqual([1]);
  });
});

describe("CueEditor", () => {
  const setup = (onChange = vi.fn(), onSeek = vi.fn()) => {
    render(<I18nProvider initial="vi"><CueEditor cues={cues} reference={[{ start: 0, end: 2, text: "Hello" }]} currentTime={3} onSeek={onSeek} onChange={onChange} /></I18nProvider>);
    return { onChange, onSeek };
  };
  it("đánh dấu cue đang phát và hiện bản gốc để đối chiếu", () => {
    setup();
    expect(screen.getAllByRole("listitem")[1]).toHaveAttribute("aria-current", "true");
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });
  it("sửa nội dung gọi onChange với cue mới", () => {
    const { onChange } = setup();
    fireEvent.change(screen.getByLabelText("Nội dung 1"), { target: { value: "Chào mọi người" } });
    expect(onChange).toHaveBeenCalledWith([{ ...cues[0], text: "Chào mọi người" }, cues[1]]);
  });
  it("sửa thời gian hợp lệ cập nhật, sai định dạng thì báo lỗi", () => {
    const { onChange } = setup();
    const end = screen.getByLabelText("Kết thúc 1");
    fireEvent.change(end, { target: { value: "00:01.500" } });
    fireEvent.blur(end);
    expect(onChange).toHaveBeenCalledWith([{ ...cues[0], end: 1.5 }, cues[1]]);
    onChange.mockClear();
    fireEvent.change(end, { target: { value: "abc" } });
    fireEvent.blur(end);
    expect(onChange).not.toHaveBeenCalled();
    expect(end).toHaveAttribute("aria-invalid", "true");
  });
  it("gộp, xoá và nhảy tới cue", () => {
    const { onChange, onSeek } = setup();
    fireEvent.click(screen.getAllByTitle("Gộp với cue sau")[0]);
    expect(onChange).toHaveBeenCalledWith(mergeWithNext(cues, 0));
    fireEvent.click(screen.getAllByTitle("Xoá cue")[1]);
    expect(onChange).toHaveBeenLastCalledWith([cues[0]]);
    fireEvent.click(screen.getByText("#2"));
    expect(onSeek).toHaveBeenCalledWith(2.5);
  });
});
