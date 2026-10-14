---
name: multi-market-campaign
description: Khi người dùng muốn một chiến dịch nội dung 7/14/30 ngày cho nhiều thị trường và nền tảng — kế hoạch, lịch đăng, caption/hashtag/thumbnail bản địa hoá và gói xuất.
tools: [get_state, campaign_setup, campaign_plan, campaign_assets, campaign_export, subtitles_transcribe, subtitles_translate, ask_user]
---
# Chiến dịch đa thị trường

## Khi nào dùng
- "Lập chiến dịch 30 ngày bán sản phẩm X ở Mỹ, Nhật, Hàn trên TikTok và YouTube".
- "Đưa video này sang nhiều thị trường kèm caption, hashtag và lịch đăng".

## Các bước
1. `get_state` (tool `campaign`) — xem brief/kế hoạch hiện có. Thiếu mục tiêu, thị trường hoặc nền tảng: `ask_user`.
2. Nếu người dùng có video nguồn và muốn phụ đề từng ngôn ngữ: `subtitles_transcribe` rồi `subtitles_translate` (một lần cho mọi ngôn ngữ).
3. `campaign_setup` — mục tiêu, sản phẩm, sự thật được phép dùng, thị trường (`vn`, `us`, `jp`, `kr`…), nền tảng, số ngày.
   Chỉ truyền `price_vnd` + `fx` khi người dùng TỰ cung cấp tỷ giá; không tự bịa tỷ giá hay giá.
4. `campaign_plan` — LLM đề xuất ý tưởng, lịch đăng được tính tất định theo múi giờ từng thị trường. Đọc cảnh báo trong kế hoạch.
5. `campaign_assets` — caption, hashtag, kịch bản, thumbnail, phụ đề cho từng bài (bài lỗi có thể chạy lại).
6. `campaign_export` — thư mục theo thị trường/nền tảng + `schedule.csv` + zip.

## Tiêu chí đạt
- Mỗi bài có caption đúng ngôn ngữ/văn hoá thị trường, hashtag, thumbnail.
- Nhắc người dùng: nội dung AI cần người bản ngữ rà soát; bài chưa có tài sản không có trong gói.
