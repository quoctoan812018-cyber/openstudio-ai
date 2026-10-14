# Hướng dẫn cài đặt OpenStudio AI

*English summary at the end.*

## 1. Chọn theo phần cứng

OpenStudio tự phát hiện máy (Cài đặt → *Phần cứng*) và **khoá công cụ vượt khả năng máy**, kèm lý do.

| Hạng | Máy | Dùng được | Dung lượng cần (ước lượng) |
|---|---|---|---|
| **CPU** | 8–16 GB RAM, không cần GPU | Phụ đề & dịch, giọng đọc, lồng tiếng, tóm tắt/highlight, podcast, chiến dịch nội dung, Trợ lý AI | Môi trường Python ~1,3 GB (Windows) + mô hình theo nhu cầu: Whisper tiny 78 MB / small 486 MB / **turbo 1,6 GB**, VieNeu 637 MB, Kokoro 354 MB, Demucs 84 MB; LLM `qwen3:4b` ~2,5 GB (Ollama) |
| **GPU 6–8 GB VRAM** | NVIDIA/AMD đủ VRAM | + avatar lip-sync, tạo ảnh (**chưa làm**; công cụ hiện khoá) | như trên |
| **GPU 12 GB+** | | + tạo video (**chưa làm**) | như trên |

Mốc đo thật trên máy CPU của nhóm phát triển (không GPU, RAM trống thường 2–5 GB, qwen3:4b + Whisper turbo + VieNeu/Kokoro, 2026-10-14): chiến dịch 3 ngôn ngữ từ video 70 s ≈ 12 phút (transcript ~70 s, kế hoạch ~45 s, 15 bài + dịch + 3 video ≈ 9–10 phút); lồng tiếng video 2 phút ≈ 6 phút (transcript ~2 phút); podcast ~90 s âm thanh ≈ 3 phút. Máy yếu hơn sẽ chậm hơn rõ rệt. **RAM ≥ 8 GB trống** khuyến nghị khi chạy cùng lúc Ollama và các mô hình giọng.

## 2. Phần mềm đi kèm bắt buộc / tuỳ chọn

| Thành phần | Bộ cài có đóng gói? | Cách cài |
|---|---|---|
| **FFmpeg + ffprobe** (có libass) — **bắt buộc** | Không | Windows: `winget install Gyan.FFmpeg` · macOS: `brew install ffmpeg` · Linux: `sudo apt install ffmpeg` |
| **Ollama** — cần cho dịch, kịch bản, caption, Trợ lý AI | Không | https://ollama.com, rồi `ollama pull qwen3:4b` và để `ollama serve` chạy |
| Python 3.11+ và thư viện AI | **Tự động** | `uv` đi kèm tạo môi trường ở lần mở đầu (cần mạng) |
| Mô hình giọng/STT/tách nhạc | Không (có checksum) | Tải trong app: Cài đặt → Mô hình |

Kiểm tra: **Cài đặt → Chẩn đoán môi trường** trong app, hoặc `pnpm doctor` khi chạy từ mã nguồn — báo thiếu gì và lệnh cài tương ứng.

## 3. Cách cài

### Windows (bộ cài `.exe`)
1. Tải `OpenStudio-AI-<phiên bản>-win-x64.exe` từ trang Releases, chạy.
2. Bộ cài **chưa ký số**: Windows SmartScreen có thể hiện "Windows protected your PC" → *More info → Run anyway*. (Nhóm dự án chưa có chứng chỉ ký mã.)
3. Mở app lần đầu: cửa sổ khởi động hiện tiến trình tạo môi trường Python (**cần Internet**, vài phút; lần sau mở ~vài giây).
4. Cài FFmpeg và Ollama theo mục 2 nếu chưa có.

Dữ liệu (project, mô hình, voice, log) nằm ở `%APPDATA%\OpenStudio AI\data` (môi trường Python ở `%APPDATA%\OpenStudio AI\env`; macOS: `~/Library/Application Support/OpenStudio AI`, Linux: `~/.config/OpenStudio AI`). Gỡ cài đặt không xoá thư mục này — xoá tay nếu muốn dọn.

### macOS (`.dmg`, arm64 và x64) và Linux (`.AppImage`)
Do GitHub Actions dựng (`.github/workflows/release.yml`). **Nhóm phát triển chưa chạy thử trên macOS/Linux thật** — xem giới hạn trong [RELEASE_CHECK.md](RELEASE_CHECK.md).
- macOS: bản chưa ký/chưa notarize → *chuột phải → Open* lần đầu, hoặc `xattr -dr com.apple.quarantine "/Applications/OpenStudio AI.app"`.
- Linux: `chmod +x OpenStudio-AI-*.AppImage && ./OpenStudio-AI-*.AppImage`. Bản torch trên Linux là bản CPU (gọn), không có CUDA.

### Docker (giao diện web)
```bash
OPENSTUDIO_TOKEN=$(openssl rand -hex 24) docker compose up --build
```
Mở http://127.0.0.1:8787, nhập địa chỉ + token. Ollama mặc định lấy từ máy chủ (`host.docker.internal:11434`), hoặc bật `--profile ollama` và đặt `OPENSTUDIO_LLM_BASE_URL=http://ollama:11434/v1`.
**Quan trọng:** trong container daemon nghe `0.0.0.0` (bắt buộc), nên `docker-compose.yml` chỉ publish `127.0.0.1:8787`. **Đừng** đổi thành `8787:8787` hay `0.0.0.0:8787` — daemon sẽ lộ ra mạng; token do bạn đặt là lớp bảo vệ duy nhất. Chế độ này **không** dùng GPU và chưa được chạy thử trong môi trường của nhóm phát triển (xem RELEASE_CHECK).

### Từ mã nguồn
Yêu cầu: Node ≥ 20, pnpm, [uv](https://docs.astral.sh/uv/), FFmpeg.
```bash
pnpm install
pnpm dev          # daemon :8787 + web :5173
pnpm doctor
```

## 4. Dùng LLM khác
`config.toml` → `[llm]` hoặc biến môi trường: `OPENSTUDIO_LLM_MODEL=qwen3:8b`, `OPENSTUDIO_LLM_BASE_URL=...`, `OPENSTUDIO_LLM_PROVIDER=openai` (máy chủ tương thích OpenAI). Mô hình lớn hơn cho kết quả dịch/viết tốt hơn nhưng chậm hơn trên CPU.

## 5. Sự cố thường gặp
| Triệu chứng | Nguyên nhân / cách xử lý |
|---|---|
| Cửa sổ khởi động kẹt ở "tạo môi trường Python" | Không có Internet hoặc bị chặn `pypi.org` / `download.pytorch.org`; kiểm tra mạng rồi mở lại (tiến trình đồng bộ lại từ chỗ dở) |
| `424 TOOL_MISSING` | Thiếu FFmpeg trong PATH — xem mục 2 |
| `424 LLM_UNAVAILABLE` | Ollama chưa chạy: `ollama serve` |
| Công cụ bị khoá | Máy không đủ VRAM (avatar/ảnh/video) — đúng thiết kế |
| Máy chậm/đơ khi lồng tiếng hoặc podcast | RAM thấp; đóng bớt ứng dụng, để Ollama nhả mô hình, đặt thư mục dữ liệu **ngoài OneDrive** (`OPENSTUDIO_DATA_DIR`) |

---
## English summary
* **CPU tier (8–16 GB RAM)** runs subtitles, TTS, dubbing, highlights, podcast, campaigns and the assistant. GPU-only tools (avatar, image, video) are not built yet and are locked on weaker machines.
* Install **FFmpeg** (with libass) and **Ollama** (`ollama pull qwen3:4b`) yourself; the installer bundles neither. The Python environment is created on first launch with a bundled `uv` (internet required).
* Windows installer is unsigned (SmartScreen warning). macOS/Linux installers are built by CI and untested on real machines by the maintainers. Docker image publishes to `127.0.0.1` only — never expose it further.
