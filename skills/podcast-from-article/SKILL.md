---
name: podcast-from-article
description: Khi người dùng muốn biến một bài viết/tài liệu hoặc một chủ đề thành tập podcast hội thoại 2–3 người dẫn, có nhạc và chương.
tools: [get_state, project_models, podcast_brief, podcast_write_script, podcast_produce, ask_user]
---
# Podcast từ bài viết

## Khi nào dùng
- "Làm podcast từ bài này", "tập podcast 5 phút về cà phê Việt Nam".

## Các bước
1. `get_state` — xem tab podcast: có tài liệu nguồn đính kèm (`sourceName`) chưa. Chưa có chủ đề lẫn tài liệu: `ask_user`.
2. `podcast_brief` — đặt `topic`, `minutes`, `language`, `hosts` (2–3 tên) theo yêu cầu; không bịa tham số người dùng chưa nói.
3. `podcast_write_script` — LLM viết kịch bản (mất vài phút trên CPU).
4. `get_state` — đọc tiêu đề + số chương/lượt để báo người dùng; họ có thể sửa kịch bản trên trang Podcast.
5. `podcast_produce` — giọng, nhạc, chương, video, show notes (cần người dùng duyệt).

## Tiêu chí đạt
- Có file MP3 (kèm chương), show notes và chapters.txt.
- Nhắc người dùng kiểm tra sự thật trong kịch bản do LLM nhỏ viết trước khi đăng.
