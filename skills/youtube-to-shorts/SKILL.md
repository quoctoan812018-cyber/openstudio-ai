---
name: youtube-to-shorts
description: Khi người dùng muốn cắt một video dài (link YouTube hoặc file đã tải) thành vài clip ngắn dọc 9:16 cho TikTok/Shorts/Reels.
tools: [get_state, subtitles_fetch_url, subtitles_transcribe, highlights_setup, highlights_analyze, highlights_export, highlights_summary, ask_user]
---
# Từ video dài thành clip ngắn

## Khi nào dùng
- "Cắt 3 clip TikTok từ video này", "lấy highlight", "làm shorts".

## Các bước
1. `get_state` — kiểm tra nguồn và transcript. Chưa có nguồn: có link thì `subtitles_fetch_url`, không thì `ask_user`.
2. `subtitles_transcribe` — chỉ khi chưa có transcript.
3. `highlights_setup` — đặt `count` theo yêu cầu (mặc định 3), `layout` vertical cho TikTok/Shorts.
4. `highlights_analyze` — tìm các đoạn hay.
5. `get_state` — đọc danh sách clip đề xuất để tóm tắt cho người dùng (tiêu đề, thời điểm, điểm).
6. `highlights_export` — xuất clip dọc có phụ đề (cần người dùng duyệt).
7. `highlights_summary` — CHỈ khi người dùng muốn thêm video tóm tắt có giọng dẫn.

## Tiêu chí đạt
- Số clip xuất ra bằng số yêu cầu (hoặc giải thích vì sao ít hơn); mỗi clip dài 20–60 giây, không cắt ngang câu.
- Liệt kê tiêu đề + hook của từng clip để người dùng đăng.
