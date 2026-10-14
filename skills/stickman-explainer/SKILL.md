---
name: stickman-explainer
description: Khi người dùng muốn video giải thích kiểu nhân vật que (stickman) về một chủ đề — kịch bản phân cảnh và giọng dẫn.
tools: [project_models, draft_text, speak_text, ask_user]
---
# Video giải thích nhân vật que

## Giới hạn hiện tại (phải nói thẳng với người dùng)
- Việc VẼ hình/cảnh cần công cụ tạo ảnh-video (Giai đoạn 5, cần GPU) — máy này chưa có. Skill này dừng ở **kịch bản phân cảnh + lời dẫn đọc thành tiếng**; hình ảnh sẽ làm sau.

## Các bước
1. `ask_user` — chỉ khi chưa rõ chủ đề hoặc đối tượng người xem.
2. `draft_text` — viết kịch bản phân cảnh: 6–10 cảnh, mỗi cảnh một dòng "CẢNH n | hình que: … | lời dẫn: …".
3. `draft_text` — viết riêng LỜI DẪN liền mạch (chỉ phần được đọc), 120–200 từ, giọng gần gũi.
4. `speak_text` — đọc lời dẫn thành file âm thanh.

## Tiêu chí đạt
- Có file kịch bản phân cảnh (.md) và file giọng dẫn; báo rõ phần hình ảnh chưa được tạo.
