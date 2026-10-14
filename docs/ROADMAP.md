# ROADMAP — OpenStudio AI (bản nháp GĐ0)

Độ khó: ★ dễ · ★★ vừa · ★★★ khó · ★★★★ rất khó. Ước lượng theo công sức một lập trình viên có AI hỗ trợ, chỉ để so sánh tương đối.

| GĐ | Nội dung | Độ khó | Rủi ro chính | Hạng máy |
|---|---|---|---|---|
| 1 | Monorepo, daemon, Model Manager, UI nền | ★★ | Tải mô hình lớn, checksum, phát hiện GPU trên Windows | CPU |
| 2 | Phụ đề & dịch (faster-whisper, LLM, trình sửa, burn-in) | ★★★ | Chất lượng tiếng Việt của LLM nhỏ; căn thời gian; trình sửa phụ đề có video | CPU |
| 3 | TTS, voice clone, lồng tiếng | ★★★★ | Khớp thời lượng sau dịch; chất lượng VieNeu; Demucs chậm trên CPU; consent | CPU |
| 4 | Avatar lip-sync | ★★★ | License MuseTalk chưa rõ; VRAM; cài phụ thuộc CUDA | GPU 8GB |
| 5 | Ảnh, video, chỉnh sửa, template | ★★★★ | FLUX.2 klein 4B ~13GB (vượt hạng 8GB); video cần 16GB+; timeline UI lớn | GPU 12–16GB+ |
| 6 | Tóm tắt/highlight & podcast | ★★★ | Chấm điểm đoạn hay bằng LLM nhỏ; ducking/loudnorm; nhạc CC0 | CPU |
| 7 | Agent + Skills + lịch + MCP | ★★★★ | LLM cục bộ gọi tool kém; đồng bộ với state machine | CPU |
| 8 | Chiến dịch, đóng gói, CI, tài liệu, kiểm thử E2E | ★★★★ | Đóng gói Python+CUDA đa nền tảng; kích thước bộ cài; ký ứng dụng | — |

## Thứ tự và phụ thuộc
1 → 2 → 3 là xương sống (dùng lại đầu ra phụ đề). 4, 5, 6 độc lập sau 3. 7 cần các công cụ đã có để lộ thành tool. 8 cuối.
Mỗi GĐ kết thúc bằng: test xanh, prompt kiểm tra Phần C, cập nhật `PROGRESS.md`.

## Cổng "chất lượng thật" (bổ sung đề xuất)
Vì chất lượng tiếng Việt chưa được đo, thêm ở đầu GĐ2 và GĐ3 một **bộ mẫu kiểm tra** (clip tiếng Việt 2 phút, đoạn văn có số/tên riêng) để chọn mô hình dựa trên kết quả nghe/đọc thực tế, rồi mới khoá mặc định trong `registry.yaml`.

## Câu hỏi mở (cần bạn quyết trước GĐ1)
1. **Hạng GPU 6–8GB và tạo ảnh.** FLUX.2 klein 4B cần ~13GB. Chọn: (a) thử bản lượng tử hoá/offload và chấp nhận chậm, hoặc (b) chuyển "Ảnh" sang hạng 12GB và để máy 8GB chỉ có lip-sync. Đề xuất: (a) thử ở GĐ5, nếu không đạt thì (b).
2. **Piper (GPL-3.0)**: chỉ cho phép dùng như plugin tiến trình ngoài, hay bỏ hẳn? Đề xuất: plugin tuỳ chọn.
3. **Mô hình NC** (F5-TTS, MusicGen…): cho người dùng tự bật có cảnh báo, hay không hỗ trợ hẳn? Đề xuất: tự bật có cảnh báo, đánh dấu rõ không dùng thương mại.
4. **Edge TTS** (dịch vụ trực tuyến không chính thức): cho vào như tuỳ chọn tắt mặc định hay bỏ? Đề xuất: tuỳ chọn tắt mặc định.
5. **Nhóm bạn dự định dùng thương mại hay chỉ cá nhân?** Ảnh hưởng đến việc có nên hỗ trợ mô hình NC và LTX-2.x.
