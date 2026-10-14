# MODEL_LICENSES — tóm tắt lựa chọn mô hình (bản nháp GĐ0, 2026-10-13)

Nguồn chi tiết: [models/registry.yaml](../models/registry.yaml). **✔ = đã đọc trực tiếp từ GitHub/HuggingFace API; ? = nguồn thứ cấp, phải kiểm tra lại.**
Mọi mục "?" là việc bắt buộc của giai đoạn tích hợp tương ứng. Không phải tư vấn pháp lý.

| Năng lực | Mặc định | Dự phòng | License trọng số (mặc định) | Hạng tối thiểu |
|---|---|---|---|---|
| LLM / viết kịch bản | Qwen qua Ollama (cỡ theo máy) ? | Gemma (điều khoản riêng) ? | Apache-2.0 ? | CPU |
| Dịch | LLM cục bộ có bảng thuật ngữ | MADLAD-400 3B MT ✔ | Apache-2.0 ✔ | CPU |
| STT | faster-whisper + large-v3 ✔ | whisper.cpp ? | MIT ✔ | CPU (cỡ nhỏ) / GPU |
| Căn thời gian từ | word_timestamps của faster-whisper ✔ | WhisperX / stable-ts ? | MIT | CPU |
| TTS tiếng Việt | VieNeu-TTS v3 Turbo ✔ (đã chạy thật trên CPU; codec OpenMOSS Apache-2.0 ✔) | G-OmniVoice ?, Piper* | Apache-2.0 ✔ | CPU |
| TTS tiếng Anh | Kokoro-82M ✔ | Piper* | Apache-2.0 ✔ | CPU |
| Voice clone | VieNeu-TTS (mẫu 3–5s) | OpenVoice v2 ? | Apache-2.0 / MIT | CPU |
| Tách giọng/nhạc | Demucs htdemucs ✔ (đã chạy thật; ~0.75× thời gian thực trên CPU) | — | MIT (code) — nhãn license trọng số còn tranh luận trên HF | CPU (chậm) |
| Lip-sync nhanh | MuseTalk 1.5 ? | — | MIT theo card, còn cảnh báo | GPU 8GB |
| Lip-sync đẹp | LatentSync 1.5 (code Apache ✔) | LatentSync 1.6 (~18GB) | ? | GPU 8GB / 16GB+ |
| Ảnh | FLUX.2 klein 4B ✔ | FLUX.1 schnell ? | Apache-2.0 ✔ | GPU ~13GB (xem rủi ro) |
| Video | Wan2.2 TI2V-5B ✔ (license) | LTX-2.x (license riêng) ? | Apache-2.0 ✔ | GPU 16GB+ |
| Nhạc nền | Thư viện CC0 người dùng thêm | Stable Audio Open ? | tuỳ nhạc | CPU |

## Mô hình bị loại khỏi mặc định (gắn cờ `non_commercial: true`, người dùng tự tải)
- **F5-TTS** — mã MIT nhưng trọng số CC-BY-NC-4.0 (huấn luyện trên Emilia), lan sang fine-tune ✔.
- **NLLB-200** — CC-BY-NC-4.0 ?.
- **MusicGen** — mã MIT, trọng số CC-BY-NC-4.0 ?.
- **FLUX.2 klein 9B / FLUX.1 dev** — FLUX Non-Commercial ?.
- **Wav2Lip** — NC ?.
- **LivePortrait + InsightFace** — LivePortrait MIT nhưng InsightFace buffalo_l là NC; chỉ dùng khi thay bằng MediaPipe.

## Ghi chú GĐ5B (2026-10-14) — tạo ảnh trên CPU
- **FLUX.2 klein 4B GGUF** (`leejet/FLUX.2-klein-4B-GGUF`), **Qwen3-4B GGUF** (`unsloth/Qwen3-4B-GGUF`), **FLUX.2 VAE** (`unsloth/FLUX.2-VAE`, bản mirror): đều `apache-2.0` theo HF API ✔, không cần đăng nhập; SHA-256 lấy từ LFS và đã kiểm lại sau khi tải ✔. Bản 9B của klein là FLUX Non-Commercial (vẫn nằm trong danh sách loại).
- **stable-diffusion.cpp** (`leejet/stable-diffusion.cpp`, MIT): bản `master-964-1d0a58a`; SHA-256 theo digest GitHub, khớp sau khi tải ✔. Bản Linux/macOS chưa chạy thử.
- Đầu ra của mô hình Apache-2.0 không bị ràng buộc thêm bởi OpenStudio; người dùng chịu trách nhiệm về nội dung (không dùng để mạo danh người thật).

## Mã trong registry.yaml của các mô hình phi thương mại (`non_commercial: true`)
`nllb-200`, `f5-tts`, `wav2lip`, `flux2-klein-9b`, `flux1-dev`, `musicgen`. Không đóng gói trọng số; nếu sau này cho tải, UI phải hiện cảnh báo và người dùng xác nhận.
`scripts/check_licenses.py` (chạy trong CI) kiểm các quy tắc này tự động.

## Cảnh báo đặc biệt
- ***Piper**: repo hiện tại `OHF-Voice/piper1-gpl` là **GPL-3.0** ✔. Dự án OpenStudio là Apache-2.0 → không được import/link; chỉ gọi như tiến trình ngoài, cài tuỳ chọn.
- **Edge TTS**: dịch vụ trực tuyến không chính thức, điều khoản không rõ → tắt mặc định, nhãn "dịch vụ ngoài".
- **LTX-2.x**: Community License (miễn phí dưới 10 triệu USD doanh thu) — không phải mã nguồn mở theo OSI.
- **MuseTalk**: GitHub báo NOASSERTION, HF card ghi MIT, nguồn khác cảnh báo ràng buộc dataset → đọc LICENSE trước GĐ4.
- **Qwen3.8**: chỉ một nguồn nói đã mở trọng số; mặc định dùng dòng đã xác nhận (3.6).

## Rủi ro phát hiện ở bước tra cứu
1. **Hạng GPU 6–8GB không đủ cho ảnh mặc định**: FLUX.2 klein 4B cần ~13GB. Hoặc dùng bản lượng tử hoá/offload (phải benchmark ở GĐ5), hoặc nâng hạng ảnh lên 12GB. Cần bạn quyết (xem ROADMAP, câu hỏi mở).
2. **Chất lượng tiếng Việt chưa được đo** cho LLM, VieNeu, MADLAD. GĐ2/GĐ3 phải có bộ kiểm thử mẫu.
3. Một số kết quả đến từ blog/trang tổng hợp; số liệu VRAM và "2026" nên xem là ước lượng.

## Ghi chú GĐ3 (2026-10-13)
- **VieNeu-TTS v3 Turbo** (`pnnbao-ump/VieNeu-TTS-v3-Turbo`) + codec **OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX**: cả hai `apache-2.0` theo HF API ✔; SHA-256 từng file lấy từ LFS ✔. Gói `vieneu` có watermark âm thanh tích hợp (luôn bật).
  Các giọng có sẵn (Mai Anh, Hải Đăng…) do mô hình cung cấp; không xác minh được chúng có xuất phát từ người thật hay không → **cần kiểm tra điều khoản trước khi dùng thương mại** (CLAUDE.md mục 6: không có preset giọng người thật do OpenStudio tự thêm).
- **Kokoro-82M ONNX** (`kokoro-onnx`, MIT; trọng số Apache-2.0): SHA-256 do OpenStudio tự tính khi ghim (GitHub release không công bố checksum).
- **Demucs**: tên file trọng số `955717e8-8726e21a.th`, tiền tố `8726e21a` khớp SHA-256 (quy ước của Demucs, tự kiểm tra khi nạp).
- **Piper (GPL-3.0)** và **Edge TTS**: chưa tích hợp ở GĐ3 (quyết định "giữ làm tuỳ chọn tắt mặc định" vẫn còn hiệu lực, chưa làm).

## Ghi chú GĐ6 (2026-10-13)
- **Không thêm mô hình AI mới.** Chấm điểm đoạn hay, lời dẫn, kịch bản podcast dùng LLM Ollama (qwen3:4b); giọng dùng VieNeu/Kokoro đã có.
- **PySceneDetect không được dùng**: phân cảnh bằng bộ lọc `select=scene` của FFmpeg (không thêm phụ thuộc OpenCV). Hệ quả: chỉ bắt được cắt cảnh tương phản rõ (ngưỡng 0.3); chuyển cảnh mờ/tối có thể bị bỏ sót — chỉ ảnh hưởng việc "hít" biên cắt, không ảnh hưởng độ đúng.
- **Nhạc podcast**: MusicGen (CC-BY-NC) **không** dùng. Mặc định là nhạc do OpenStudio tự sinh bằng toán học (CC0). Nhạc người dùng thêm phải kèm ghi chú giấy phép (lưu trong `.runtime/music/<id>/meta.json`); OpenStudio không kiểm chứng giấy phép đó.
