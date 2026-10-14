---
name: video-localization
description: Khi người dùng muốn bản địa hoá một video sang ngôn ngữ khác — phụ đề dịch, và/hoặc lồng tiếng thay giọng gốc.
tools: [get_state, project_models, subtitles_fetch_url, subtitles_transcribe, subtitles_translate, subtitles_export, dubbing_setup, dubbing_synthesize, dubbing_mix, ask_user]
---
# Bản địa hoá video

## Khi nào dùng
- "Dịch video này sang tiếng Anh", "làm phụ đề tiếng Nhật", "lồng tiếng tiếng Anh cho video".

## Các bước
1. `get_state` — xem project đã có video nguồn (công cụ `subtitles`) và transcript chưa. Nếu chưa có nguồn: người dùng đưa link thì gọi `subtitles_fetch_url`, không thì `ask_user` xin họ tải file lên.
2. `subtitles_transcribe` — chỉ khi chưa có transcript (sourceLang trống). Nếu thiếu mô hình giọng nói thì dùng `project_models` rồi báo người dùng.
3. `subtitles_translate` — dịch sang MỌI ngôn ngữ người dùng nêu, đặt `tone` hợp ngữ cảnh.
4. `subtitles_export` — xuất SRT cho từng ngôn ngữ đã dịch.
5. `dubbing_setup` — CHỈ khi người dùng yêu cầu lồng tiếng: chọn `target_lang` (một ngôn ngữ mỗi lần). Kokoro không có tiếng Việt/Hàn/Thái/Đức/Nga/Indo.
6. `dubbing_synthesize` — đọc từng câu và khớp thời gian.
7. `dubbing_mix` — trộn nhạc nền và ghép vào video (cần người dùng duyệt).

## Tiêu chí đạt
- Mỗi ngôn ngữ yêu cầu có file phụ đề; nếu lồng tiếng, có video `.dub.mp4` và SRT khớp giọng.
- Báo lại cho người dùng: số câu bị tăng tốc/rút gọn, và lưu ý bản dịch do LLM nhỏ nên cần rà soát.
