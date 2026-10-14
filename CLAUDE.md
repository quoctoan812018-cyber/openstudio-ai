# OpenStudio AI — Bối cảnh dự án

## 1. Mục tiêu
Xây dựng ứng dụng desktop + web chạy CỤC BỘ, miễn phí 100%, mã nguồn mở (Apache-2.0),
gom vào một nơi các khả năng:
- Chuyển giọng nói thành văn bản (STT), tạo phụ đề
- Dịch thuật phụ đề/kịch bản đa ngôn ngữ (ưu tiên Việt ⇄ Anh/Trung/Nhật/Hàn)
- Tạo giọng nói (TTS), nhân bản giọng (voice clone) có đồng ý
- Lồng tiếng video (dubbing) khớp thời gian
- Tạo avatar AI nói (talking-head, lip-sync)
- Tạo & chỉnh sửa hình ảnh, video, thumbnail
- Video tóm tắt (long → short), cắt highlight tự động
- Sản xuất podcast (kịch bản 2 người, giọng, nhạc nền, xuất audio/video)
- Chiến dịch nội dung đa nền tảng (YouTube, TikTok, Facebook), bản địa hóa theo thị trường
- AI Agent + Skills tái sử dụng để tự động hóa toàn bộ quy trình

## 2. Kiến trúc tham chiếu
Học kiến trúc từ OpenCreator (github.com/krillinai/OpenCreator, Apache-2.0):
- Một frontend Web duy nhất (React + Vite + TypeScript), Desktop (Electron) chỉ bọc thêm
  tính năng hệ điều hành.
- Runtime cục bộ (daemon) quản lý project, run, phê duyệt, lịch, bộ nhớ; chỉ nghe 127.0.0.1,
  bắt buộc Bearer token.
- Mỗi công cụ là một STATE MACHINE: input → cấu hình → sinh → duyệt → sửa → xuất.
  Giao diện trực quan và hội thoại Agent cùng đẩy sự kiện vào MỘT state machine.
- Mọi lần sửa tạo PHIÊN BẢN MỚI, không ghi đè.
- Skills định nghĩa bằng thư mục `skills/<tên>/SKILL.md`.

KHÁC BIỆT BẮT BUỘC so với OpenCreator:
- OpenCreator phụ thuộc Codex CLI và API trả phí (GPT Image, Seedance, Kling…).
- OpenStudio AI phải chạy được HOÀN TOÀN bằng mô hình mở, cục bộ, không cần API key.
- Nhà cung cấp cloud chỉ là TÙY CHỌN, tắt mặc định, gắn nhãn "Có thể mất phí".
- Agent engine: tự viết vòng lặp agent gọn nhẹ, gọi LLM cục bộ qua Ollama
  (OpenAI-compatible API). Cho phép cắm thêm provider khác qua cấu hình.

## 3. Ngăn xếp công nghệ
- Frontend: React 18, Vite, TypeScript, Tailwind, Zustand/XState cho state machine
- Daemon: Python 3.11 + FastAPI (hệ sinh thái AI chủ yếu là Python), SSE cho tiến độ
- Desktop: Electron
- Hàng đợi tác vụ: tự quản trong daemon (asyncio + SQLite), không bắt buộc Redis
- Dữ liệu: SQLite + thư mục `.runtime/`
- Media: FFmpeg/ffprobe, yt-dlp
- Quản lý mô hình: tải theo nhu cầu vào `.runtime/models/`, có checksum, hiển thị dung lượng
- Monorepo: pnpm (JS) + uv (Python)

## 4. Mô hình mở ứng viên (PHẢI kiểm tra phiên bản & license thực tế trước khi dùng)
| Năng lực | Ứng viên |
|---|---|
| LLM, dịch, viết kịch bản | Ollama + Qwen / Gemma / Llama (bản nhỏ cho máy yếu) |
| Dịch chuyên dụng | NLLB-200, MADLAD-400, hoặc LLM cục bộ |
| STT | faster-whisper, whisper.cpp |
| Căn thời gian từ | WhisperX / stable-ts |
| TTS | Piper, Kokoro, Edge TTS (miễn phí nhưng cần mạng), F5-TTS, các mô hình TTS tiếng Việt mở |
| Voice clone | OpenVoice, F5-TTS, GPT-SoVITS |
| Tách giọng/nhạc nền | Demucs |
| Avatar / lip-sync | LivePortrait, MuseTalk, LatentSync, Wav2Lip, SadTalker |
| Ảnh | Stable Diffusion / FLUX (bản mở) qua diffusers hoặc ComfyUI |
| Video | Wan, LTX-Video, CogVideoX |
| Nhạc nền podcast | MusicGen hoặc thư viện nhạc CC0 |
| Highlight/tóm tắt | LLM + phân đoạn transcript + PySceneDetect |

Quy tắc license:
- Tạo `docs/MODEL_LICENSES.md` và `models/registry.yaml` ghi: tên, phiên bản, license code,
  license trọng số, có cho phép thương mại không, nguồn tải.
- Mô hình license phi thương mại (NC) phải gắn cờ `non_commercial: true` và hiển thị cảnh báo
  trên giao diện. Không đóng gói sẵn trọng số; người dùng tự tải.

## 5. Phân hạng phần cứng (bắt buộc hỗ trợ)
- Hạng CPU (8–16GB RAM): STT, dịch, TTS, lồng tiếng, podcast audio, phụ đề, cắt ghép.
- Hạng GPU 6–8GB VRAM: thêm ảnh, avatar lip-sync.
- Hạng GPU 12GB+: thêm sinh video.
Ứng dụng tự phát hiện phần cứng, ẩn/khóa công cụ vượt khả năng máy và giải thích lý do.

## 6. Đạo đức & an toàn (bắt buộc)
- Voice clone / avatar từ ảnh người thật: yêu cầu xác nhận "Tôi có quyền và sự đồng ý của
  người này" trước khi chạy; lưu bản ghi xác nhận cục bộ.
- Tùy chọn gắn nhãn "Nội dung tạo bởi AI" vào metadata và (tùy chọn) watermark hiển thị.
- Không có tính năng mạo danh người nổi tiếng/tổ chức; không có preset giọng người thật.
- Dữ liệu, file, log ở máy người dùng; log được che thông tin nhạy cảm.

## 7. Quy ước làm việc cho Claude
- Trước mỗi giai đoạn: đọc lại file này, lập kế hoạch ngắn, liệt kê file sẽ tạo/sửa.
- Làm từng lát dọc (vertical slice) chạy được, không dựng khung rỗng hàng loạt.
- Mỗi module có test (pytest / vitest); chạy test trước khi báo xong.
- Không hard-code đường dẫn; mọi cấu hình qua `config.toml` + biến môi trường.
- Commit nhỏ, thông điệp rõ: `feat(dubbing): ...`, `fix(stt): ...`.
- Gặp lựa chọn khó đảo ngược (đổi kiến trúc, đổi license) → dừng, trình bày phương án, chờ duyệt.
- Cập nhật `docs/PROGRESS.md` sau mỗi giai đoạn: đã xong, còn lại, rủi ro.
- Giao diện mặc định tiếng Việt, có tiếng Anh; i18n bằng file JSON.
