# OpenStudio AI

🇻🇳 Tiếng Việt · [🇬🇧 English](README.en.md)

Bộ công cụ sáng tạo nội dung AI chạy **cục bộ trên máy bạn**, miễn phí, mã nguồn mở ([Apache-2.0](LICENSE)). Không cần API key; dữ liệu, file và log ở lại máy bạn. Nhà cung cấp cloud (nếu sau này thêm) luôn tắt mặc định.

## Có gì trong bản này

| Công cụ | Làm gì | Hạng máy |
|---|---|---|
| **Phụ đề & Dịch** | Giọng nói → văn bản (faster-whisper), sửa trực quan, dịch đa ngôn ngữ bằng LLM cục bộ có bảng thuật ngữ, xuất SRT/VTT/ASS, ghi phụ đề vào video 16:9 / 9:16 | CPU |
| **Giọng đọc** | TTS (VieNeu cho tiếng Việt, Kokoro cho tiếng Anh/Nhật/Trung…), nhân bản giọng **có ghi nhận đồng ý** | CPU |
| **Lồng tiếng** | Dịch → đọc → khớp thời lượng từng câu → tách nhạc nền bằng Demucs → trộn → ghép video | CPU |
| **Tóm tắt & Highlight** | Chọn đoạn hay bằng LLM + phân cảnh, xuất clip 9:16 có phụ đề/tiêu đề, video tóm tắt có lời dẫn | CPU |
| **Podcast** | Chủ đề/tài liệu → kịch bản 2–3 người → giọng + nhạc mở/kết, nhạc nền tự hạ khi nói → MP3 có chương, video sóng âm, show notes | CPU |
| **Chiến dịch nội dung** | Mục tiêu + thị trường + nền tảng → kế hoạch 7/14/30 ngày, lịch đăng theo múi giờ từng nơi, caption/hashtag/kịch bản/thumbnail bản địa hoá, phụ đề từng ngôn ngữ → bảng theo dõi → xuất gói + `schedule.csv` | CPU |
| **Trợ lý AI + Skills** | Ra lệnh bằng tiếng thường; trợ lý gọi đúng các công cụ trên; skill là file `SKILL.md`; lịch chạy cron | CPU |
| **Chỉnh sửa video** | Cắt/ghép, tốc độ, chuyển cảnh, chữ, ảnh chèn, nhạc nền tự hạ khi có lời, xem trước nhanh, 16:9 · 9:16 · 1:1 (FFmpeg) | CPU |
| **Thumbnail & Template** | Ảnh/khung hình + tiêu đề tiếng Việt, nhiều biến thể; template dùng lại | CPU |
| **Avatar AI (hoạt hình theo giọng)** | Ảnh chân dung nói theo giọng, ghép nền/khung/phụ đề; ảnh người thật cần xác nhận đồng ý. *Không phải lip-sync AI* | CPU |
| **Tạo ảnh AI** | FLUX.2 klein 4B lượng tử (Apache-2.0) chạy trên CPU qua stable-diffusion.cpp — **chậm** (~3–4 phút cho ảnh 512 px); tải ~5 GB một lần | CPU (chậm) |
| **Tạo video từ ảnh** | Zoom/lia máy trên ảnh tĩnh (FFmpeg). *Không phải AI sinh video* | CPU |
| Lip-sync AI, sinh video AI | **Chưa làm** (cần GPU lớn) | GPU |

Chi tiết tiến độ, rủi ro và giới hạn trung thực: [docs/PROGRESS.md](docs/PROGRESS.md) · kiểm tra phát hành: [docs/RELEASE_CHECK.md](docs/RELEASE_CHECK.md) · kiến trúc: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Cài đặt nhanh

Hướng dẫn đầy đủ theo hạng phần cứng: **[docs/INSTALL.md](docs/INSTALL.md)**.

- **Windows**: chạy bộ cài `OpenStudio-AI-<phiên bản>-win-x64.exe` (chưa ký số → Windows SmartScreen có thể cảnh báo). Lần mở đầu tiên app tự tạo môi trường Python bằng `uv` (cần mạng, vài phút).
- **macOS / Linux**: bộ cài `.dmg` / `.AppImage` do CI dựng (xem [giới hạn đã biết](docs/RELEASE_CHECK.md)); hoặc chạy từ mã nguồn.
- **Docker (web)**: `OPENSTUDIO_TOKEN=<chuỗi-bí-mật> docker compose up --build` rồi mở http://127.0.0.1:8787.
- **Từ mã nguồn**:
```bash
pnpm install
pnpm dev            # daemon :8787 + web :5173 (token ngẫu nhiên mỗi lần chạy)
pnpm doctor         # kiểm tra FFmpeg, Ollama, dung lượng
```

Cần thêm **FFmpeg** (bản có libass) và, cho dịch/kịch bản/Agent, **[Ollama](https://ollama.com)** với một mô hình (mặc định `qwen3:4b`). Bộ cài **không** đóng gói FFmpeg, Ollama hay trọng số mô hình; mô hình tải theo nhu cầu vào thư mục dữ liệu, có checksum và hiển thị dung lượng.

## Phát triển

```bash
pnpm test           # pytest + vitest + test desktop
pnpm lint           # ESLint + ruff
pnpm typecheck
pnpm check:licenses # kiểm models/registry.yaml theo quy tắc license
pnpm protocol:gen   # sinh lại type TS từ Pydantic
pnpm dist:win       # dựng bộ cài Windows (cần Windows)
```
Xem [CONTRIBUTING.md](CONTRIBUTING.md). Cấu hình: [config.toml](config.toml) + biến môi trường `OPENSTUDIO_*` (`DATA_DIR`, `PORT`, `REGISTRY`, `LLM_MODEL`, …).

## An toàn & đạo đức
- Daemon **chỉ nghe 127.0.0.1** và bắt buộc Bearer token (ngoại lệ duy nhất: container Docker, publish cổng vào loopback máy chủ).
- Nhân bản giọng / avatar từ người thật yêu cầu xác nhận *"Tôi có quyền và sự đồng ý của người này"*, bản ghi lưu cục bộ. Không có preset giọng người nổi tiếng.
- Có thể gắn nhãn "Nội dung tạo bởi AI" vào metadata. Log được che token/khoá.
- Nội dung AI viết (đặc biệt chiến dịch đa thị trường) **cần người bản ngữ rà soát** trước khi đăng.

## Mô hình & license
[docs/MODEL_LICENSES.md](docs/MODEL_LICENSES.md) và [models/registry.yaml](models/registry.yaml). Mô hình phi thương mại gắn `non_commercial: true`, cần bạn xác nhận trước khi tải. Ứng dụng không đóng gói sẵn trọng số.

## Trợ lý AI & Skills
- Trang **Trợ lý AI**: bước xuất media nặng, tải mô hình, công cụ ngoài (MCP) đều **hỏi bạn duyệt**.
- **Skills**: `skills/<tên>/SKILL.md` (có sẵn: `video-localization`, `youtube-to-shorts`, `podcast-from-article`, `multi-market-campaign`, `stickman-explainer`) và `.runtime/skills/` của bạn. Skill chỉ là văn bản hướng dẫn, không chạy mã.
- **Lịch chạy**: trang *Skills & Lịch* (cron 5 trường, ≥ 5 phút/lần).
- **MCP** (tuỳ chọn, mặc định tắt) khai báo trong `config.toml`:
```toml
[[mcp.servers]]
name = "docs"
command = ["python", "my_mcp_server.py"]
```

## Lời cảm ơn
Kiến trúc tham khảo [OpenCreator](https://github.com/krillinai/OpenCreator) (Apache-2.0). Các mô hình/thư viện mở được liệt kê trong [docs/MODEL_LICENSES.md](docs/MODEL_LICENSES.md).
