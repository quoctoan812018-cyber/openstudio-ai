# RELEASE_CHECK — kiểm tra cuối trước phát hành (2026-10-14)

Máy kiểm: Windows 11, CPU (không GPU), RAM trống thường 2–5 GB. Mô hình thật: faster-whisper large-v3-turbo, qwen3:4b (Ollama), VieNeu v3 Turbo, Kokoro, Demucs, FFmpeg. Daemon thật, không giả lập.

## 1. Ba kịch bản đầu-cuối (chạy lại sau khi sửa lỗi tìm thấy)

| # | Kịch bản | Script | Kết quả | Thời gian |
|---|---|---|---|---|
| 1 | **Lồng tiếng video**: video Việt 2 phút (có nhạc nền) → phụ đề → dịch Anh → đọc Kokoro, khớp từng câu → tách nền Demucs → trộn → ghép | `scripts/e2e_dubbing.py` | **TẤT CẢ ĐẠT** (17 kiểm tra: độ dài = nguồn ±0,3 s, mọi câu ≤ khung thời gian, nền còn nghe được ở khoảng lặng, nhãn AI trong metadata, giọng Việt gốc không lọt…) | 374 s |
| 2 | **Podcast**: tài liệu → kịch bản 2 người (qwen3) → VieNeu → nhạc mở/kết + nền ducking → MP3 chương + video sóng âm + show notes | `scripts/e2e_podcast.py` | **TẤT CẢ ĐẠT** (-16,9 LUFS, đỉnh -4,7 dBFS, chương nhúng đúng, nhận dạng lại bản thành phẩm khớp kịch bản 0,987) | 184 s |
| 3 | **Chiến dịch 3 ngôn ngữ** (Việt · Anh · Nhật; TikTok + Facebook; 7 ngày; 15 bài) | `scripts/e2e_campaign.py` | **26/26 đạt** ở lần chạy lại | 730 s |
| 4 | **Sáng tạo (GĐ4+5)**: TTS thật → avatar 16:9 → editor 9:16 (chuyển cảnh, chữ, nhạc) → 3 thumbnail | `scripts/e2e_creative.py` | **14/14 đạt** (chạy sau khi viết xong GĐ4+5; các số pytest/vitest bên dưới là của lần kiểm trước, bản mới: pytest 183, vitest 45) | ~3 phút (TTS 103 s) |

**Lỗi tìm thấy bởi kịch bản 3 và đã sửa:** lần chạy đầu 25/26 — một caption thị trường Mỹ lọt chữ có dấu tiếng Việt ("Tây Nguyên"). Nay bài tiếng Anh đổi tên riêng Việt về chữ không dấu (`plain_latin`, có test) rồi chạy lại cả kịch bản: 26/26.

Quan sát chất lượng (không phải tiêu chí đạt/trượt): qwen3:4b vẫn **bịa/sai chi tiết** trong caption, ví dụ gọi "Tây Nguyên" là "West Coast"/"Central Vietnam" và có bản JP dịch sai địa danh ("西原"). Đây là giới hạn của mô hình 4B → **luôn cần người bản ngữ rà soát** (đã ghi trong UI và gói xuất).

## 2. Kiểm thử tự động (đã chạy)
| Hạng mục | Kết quả |
|---|---|
| `pytest` (daemon) | **165 passed** |
| `vitest` (web) | **45 passed** (5 file) |
| Test desktop (`node --test`) | **6 passed** |
| `tsc --noEmit` | sạch |
| ESLint + ruff (`pnpm lint`) | sạch (đã sửa 31 lỗi ruff: biến thừa, B023 closure thật ở `subtitles/service.py`, v.v.) |
| `scripts/check_licenses.py` | 35 mô hình, 0 lỗi (kèm 3 test) |
| Quét route | `test_every_route_requires_token_except_allowlist`: mọi route (>50) trả 401 khi không có token, trừ `/healthz`, `/files/*` (có chữ ký/Bearer riêng) và docs |

## 3. Đóng gói (đã thực hiện thật / chưa)
| Mục | Trạng thái |
|---|---|
| Windows `electron-builder --dir` | ✅ dựng được (308 MB giải nén) |
| Windows bộ cài NSIS `OpenStudio-AI-0.1.0-win-x64.exe` | ✅ **dựng được (94 MB), chưa ký số, chưa chạy thử cài đặt** (cài lên máy dev sẽ đổi hệ thống; để CI/máy sạch) |
| Smoke test **gói đã đóng gói** với userData sạch | ✅ `SMOKE_OK`: lần đầu tạo môi trường Python bằng `uv` đi kèm ~2 phút (cache uv đã ấm; máy chưa từng cài sẽ lâu hơn vì tải ~1,3 GB), lần hai 5,7 s; dữ liệu nằm ở `userData/data` |
| `fetch-uv.mjs` | ✅ tải uv 0.12.23 và **khớp SHA-256** |
| macOS arm64/x64 (`.dmg`), Linux (`.AppImage`) | ❌ **chưa dựng, chưa chạy** — cần máy/runner tương ứng. Cấu hình có trong `electron-builder.yml` + `release.yml` nhưng chưa được thử |
| GitHub Actions `ci.yml`, `release.yml` | ❌ **chưa chạy** (chưa có remote). Chỉ kiểm cú pháp YAML. Các hành động bên thứ ba (`setup-ffmpeg`, `setup-uv`, `action-gh-release`) và nhãn runner (`macos-13`…) có thể cần chỉnh khi chạy thật |
| Docker | ❌ **chưa build**: Docker Desktop không chạy trên máy kiểm (`docker info` lỗi pipe). `Dockerfile`/`docker-compose.yml` mới được viết, chưa xác minh (kể cả tag `ghcr.io/astral-sh/uv:0.12`). Phần daemon phục vụ web + bind 0.0.0.0 có test đơn vị |
| Torch CPU cho Linux | ✅ `uv lock` đã tách chỉ mục CPU (loại gói CUDA khỏi lock Linux); ❌ chưa cài thử trên Linux |
| Ký mã / notarize | ❌ chưa có chứng chỉ → cảnh báo SmartScreen/Gatekeeper |
| FFmpeg, Ollama | Không đóng gói; có chẩn đoán trong app (`/system/doctor`) |

## 4. Rà soát theo checklist Phần C
**An toàn**
- Loopback + token: cấu hình từ chối host khác 127.0.0.1; ngoại lệ container (`OPENSTUDIO_ALLOW_REMOTE_BIND=1`) chỉ nhận `0.0.0.0`, **bắt buộc** token do người dùng đặt, không in token ra log (có test). Compose chỉ publish `127.0.0.1`.
- Không lộ khoá: quét mã nguồn tìm mẫu `sk-`, `ghp_`, `AKIA`, khoá riêng, `hf_` → không có. Log qua `redact()` (Bearer, `sk-…`, `api_key=`, chữ ký URL, thư mục home).
- Electron: `contextIsolation`, `sandbox`, không `nodeIntegration`; preload chỉ lộ địa chỉ+token; giao thức `app://` chặn thoát khỏi thư mục web (sửa so sánh tiền tố thành `base + sep`).
- Voice clone/avatar: cổng đồng ý + bản ghi cục bộ (Giai đoạn 3, có test); chiến dịch không tạo giọng/mặt người thật.
- Không bịa số liệu nhạy cảm: giá chỉ quy đổi bằng tỷ giá người dùng nhập (đã kiểm: bài JP không có ¥/円/$ khi thiếu tỷ giá).

**License**: `registry.yaml` đầy đủ `weights_license`; NC đều có `non_commercial: true`, không mô hình NC nào là mặc định, không đóng gói trọng số; file > 5 MB có sha256. LTX-2.x gắn `conditional_license`. Một số mục vẫn `verified: false` (nguồn thứ cấp) — phải xác minh khi tích hợp. Chưa có LICENSE cho các dependency Python/JS (chưa chạy công cụ quét license phụ thuộc).

**Danh sách lỗi/rủi ro theo mức độ**
| Mức | Mục |
|---|---|
| **Cao** | Bộ cài macOS/Linux, CI, Docker **chưa được chạy bao giờ** — có thể hỏng ở lần chạy đầu. Chất lượng nội dung LLM 4B (bịa chi tiết, dịch sai địa danh) cần người rà |
| **Trung bình** | Bộ cài chưa ký số. Lần mở đầu cần Internet + ~1,3 GB (Windows). Không đóng gói FFmpeg/Ollama → người dùng phải cài (đã có hướng dẫn + chẩn đoán). Hiệu năng CPU chậm, RAM thấp từng gây chậm bất thường (1 lần podcast qua Agent 1401 s, không tái hiện) — nên đặt dữ liệu ngoài OneDrive |
| **Thấp** | Test giao diện chỉ bằng vitest (chưa có test trình duyệt tự động cho các trang Highlight/Podcast/Chiến dịch); chưa quét license phụ thuộc; avatar/ảnh/video chưa làm (cần GPU) |

## 5. Việc nên làm trước khi phát hành công khai
1. Đẩy lên GitHub, chạy `ci.yml` + `release.yml` (draft), sửa theo lỗi thật; chạy thử bộ cài trên Windows/macOS/Linux sạch.
2. `docker compose up --build` trên máy có Docker chạy; kiểm cổng chỉ nghe loopback.
3. Mua/cấu hình chứng chỉ ký (Windows) và notarize (macOS) nếu muốn bỏ cảnh báo.
4. Người bản ngữ đánh giá chất lượng caption/dịch (vi/en/ja) và thử LLM lớn hơn (qwen3:8b+) nếu máy cho phép.
