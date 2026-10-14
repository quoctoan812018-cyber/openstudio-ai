"""Danh mục công cụ + yêu cầu phần cứng. Công cụ vượt khả năng máy bị khóa kèm lý do."""
from __future__ import annotations

from .hardware import TIER_LABELS, tier_allows

# id, tên (vi), mô tả, hạng tối thiểu, giai đoạn xây dựng
TOOLS = [
    ("subtitles", "Phụ đề & Dịch", "Chuyển giọng nói thành phụ đề, dịch đa ngôn ngữ", "cpu", 2),
    ("tts", "Giọng đọc", "Tạo giọng nói từ kịch bản, nhân bản giọng có đồng ý", "cpu", 3),
    ("dubbing", "Lồng tiếng video", "Lồng tiếng khớp thời gian, giữ nhạc nền", "cpu", 3),
    ("avatar", "Avatar AI", "Ảnh chân dung nói theo audio (CPU: hoạt hình theo giọng; GPU: lip-sync AI chưa có)", "cpu", 4),
    ("image", "Tạo ảnh AI", "Sinh ảnh từ mô tả (FLUX.2 klein 4B lượng tử, chạy được trên CPU nhưng chậm)", "cpu", 5),
    ("video", "Tạo video", "Ảnh → video chuyển động bằng FFmpeg (sinh video AI cần GPU 16GB+, chưa có)", "cpu", 5),
    ("editor", "Chỉnh sửa video", "Cắt, ghép, chèn chữ, nhạc nền", "cpu", 5),
    ("thumbnail", "Thumbnail & Ảnh bìa", "Ghép ảnh/khung hình + tiêu đề tiếng Việt, nhiều biến thể", "cpu", 5),
    ("highlights", "Tóm tắt & Highlight", "Cắt clip ngắn từ video dài", "cpu", 6),
    ("podcast", "Podcast", "Kịch bản hội thoại, giọng, nhạc nền", "cpu", 6),
    ("agent", "AI Agent", "Ra lệnh bằng ngôn ngữ tự nhiên, Skills", "cpu", 7),
    ("campaign", "Chiến dịch nội dung", "Kế hoạch đa nền tảng, đa thị trường", "cpu", 8),
]

TOOL_IDS = {t[0] for t in TOOLS}
IMPLEMENTED = {"subtitles", "tts", "dubbing", "highlights", "podcast", "campaign", "editor", "thumbnail", "avatar", "image", "video", "agent"}  # thêm id khi giai đoạn tương ứng hoàn thành


def list_tools(machine_tier: str) -> list[dict]:
    out = []
    for tid, name, desc, req, phase in TOOLS:
        ok = tier_allows(machine_tier, req)
        out.append({
            "id": tid, "name": name, "description": desc, "min_tier": req, "phase": phase,
            "implemented": tid in IMPLEMENTED,
            "available": ok,
            "locked_reason": None if ok else
            f"Cần {TIER_LABELS[req]}; máy của bạn ở hạng {TIER_LABELS[machine_tier]}.",
        })
    return out
