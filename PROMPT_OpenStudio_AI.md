# PROMPT HOÀN CHỈNH — XÂY DỰNG "OPENSTUDIO AI"
### Bộ công cụ sáng tạo nội dung AI tất-cả-trong-một, MIỄN PHÍ & MÃ NGUỒN MỞ
**Dùng cho: Claude Code** (dán Phần A vào `CLAUDE.md` ở thư mục gốc dự án; dán lần lượt từng prompt ở Phần B khi bắt đầu mỗi giai đoạn)

---

## PHẦN A — FILE `CLAUDE.md` (bối cảnh cố định cho toàn dự án)

```markdown
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
```

---

## PHẦN B — PROMPT THEO TỪNG GIAI ĐOẠN

> Dán **một prompt mỗi lần**. Chỉ chuyển giai đoạn khi giai đoạn trước chạy được và test xanh.

### Giai đoạn 0 — Khảo sát & thiết kế
```
Đọc CLAUDE.md. Sau đó:
1. Clone github.com/krillinai/OpenCreator vào thư mục reference/ (chỉ để tham khảo, không sửa).
   Đọc README, apps/daemon, apps/web, skills/. Tóm tắt các mẫu thiết kế nên học
   (state machine, versioning, skills, runtime API, bảo mật).
2. Với mỗi năng lực trong bảng mô hình ứng viên: tra phiên bản mới nhất, license code và
   trọng số, yêu cầu VRAM, chất lượng tiếng Việt. Chọn 1 mặc định + 1 dự phòng cho mỗi năng lực.
   Ghi vào docs/MODEL_LICENSES.md và models/registry.yaml.
3. Viết docs/ARCHITECTURE.md: sơ đồ khối, cấu trúc thư mục monorepo, Runtime API v1
   (endpoint, schema sự kiện SSE), mô hình dữ liệu SQLite, vòng đời Job.
4. Viết docs/ROADMAP.md theo các giai đoạn 1–8 bên dưới, ước lượng độ khó.
Không viết code ứng dụng ở giai đoạn này. Dừng lại cho tôi duyệt thiết kế.
```

### Giai đoạn 1 — Nền móng
```
Dựng monorepo theo ARCHITECTURE.md đã duyệt:
- apps/web (React+Vite+TS+Tailwind), apps/daemon (FastAPI), apps/desktop (Electron), packages/protocol (schema dùng chung, sinh type TS từ Pydantic).
- Daemon: health check, Bearer token, quản lý Project/Job/Version, SSE tiến độ, SQLite migration.
- Model Manager: đọc registry.yaml, phát hiện CPU/GPU/VRAM, tải mô hình có thanh tiến độ + checksum, hiển thị license.
- Giao diện: Dashboard lưới công cụ, trang Cài đặt (phần cứng, mô hình, ngôn ngữ, thư mục dữ liệu), trang Thư viện file.
- Lệnh: `pnpm dev` chạy cả web + daemon; `pnpm test`; `pnpm desktop:dev`.
Hoàn thành khi: mở được app, thấy phần cứng được phát hiện, tải được 1 mô hình nhỏ, test xanh.
```

### Giai đoạn 2 — STT, phụ đề, dịch thuật
```
Xây công cụ "Phụ đề & Dịch":
- Nhập file video/audio hoặc link (yt-dlp). Tách audio bằng FFmpeg.
- STT bằng faster-whisper (chọn cỡ mô hình theo phần cứng), căn thời gian cấp từ.
- LLM cục bộ: tách câu tự nhiên, sửa lỗi chính tả, giữ thuật ngữ (bảng thuật ngữ người dùng tự nhập).
- Dịch sang nhiều ngôn ngữ cùng lúc; tùy chọn văn phong theo thị trường (trang trọng/thân mật).
- Trình sửa phụ đề: xem video + chỉnh dòng, gộp/tách, dời thời gian.
- Xuất SRT/VTT/ASS, phụ đề song ngữ, burn-in vào video (ngang/dọc 9:16).
Test: một file mẫu 2 phút tiếng Việt → phụ đề Anh, không chồng dòng, không mất đoạn.
```

### Giai đoạn 3 — TTS, nhân bản giọng, lồng tiếng
```
Xây 2 công cụ:
A. "Giọng đọc": nhập kịch bản → chọn giọng, tốc độ, cảm xúc, ngắt nghỉ → xuất WAV/MP3.
   Hỗ trợ nhiều giọng trong một kịch bản (gắn thẻ [Người A]/[Người B]).
   Voice clone từ mẫu 10–30 giây, bắt buộc hộp xác nhận đồng ý (CLAUDE.md mục 6).
B. "Lồng tiếng video": phụ đề đã dịch → lập kế hoạch lồng tiếng (gộp câu, giới hạn tốc độ,
   LLM rút gọn câu quá dài để khớp thời lượng) → TTS từng câu → căn chỉnh thời gian
   → Demucs tách nhạc nền gốc → trộn giọng mới + nhạc nền → ghép vào video.
   Tham khảo pipeline dubbing của OpenCreator (subtitle parsing → planning → TTS → assembly → muxing).
Xuất: video lồng tiếng, audio riêng, phụ đề khớp.
```

### Giai đoạn 4 — Avatar AI nói
```
Xây công cụ "Avatar AI":
- Đầu vào: ảnh chân dung hoặc video ngắn + audio (từ công cụ Giọng đọc hoặc file tải lên).
- Lip-sync bằng mô hình đã chọn ở Giai đoạn 0; có chế độ nhanh (chất lượng thấp, chạy CPU/GPU yếu) và chế độ đẹp.
- Thư viện avatar do người dùng tạo; bắt buộc xác nhận quyền với ảnh người thật.
- Ghép nền, khung, phụ đề; xuất ngang và 9:16.
Khóa công cụ nếu phần cứng không đủ, kèm giải thích.
```

### Giai đoạn 5 — Ảnh, video, chỉnh sửa
```
Xây:
A. "Tạo ảnh & Thumbnail": prompt + ảnh tham chiếu, tỉ lệ khung, nhiều biến thể, chèn chữ tiêu đề tiếng Việt (font hỗ trợ dấu đầy đủ).
B. "Tạo video": text/image-to-video bằng mô hình mở đã chọn (chỉ bật ở hạng GPU phù hợp).
C. "Chỉnh sửa video": timeline đơn giản — cắt, ghép, chèn chữ, chèn ảnh, nhạc nền, chuyển cảnh, tốc độ; xử lý bằng FFmpeg; xem trước nhanh.
D. Hệ thống Template: thư mục template/<tên>/template.json + ảnh mẫu, dùng lại prompt và cấu hình.
```

### Giai đoạn 6 — Video tóm tắt & Podcast
```
Xây:
A. "Tóm tắt & Cắt highlight": video dài → transcript → LLM chấm điểm đoạn hay + PySceneDetect
   → đề xuất N clip ngắn (có tiêu đề, hook, thời lượng) → người dùng duyệt → xuất 9:16 có phụ đề.
   Tùy chọn: tạo video tóm tắt có giọng đọc mới thuật lại nội dung.
B. "Podcast": chủ đề hoặc tài liệu nguồn → LLM viết kịch bản hội thoại 2–3 người
   → TTS nhiều giọng → nhạc mở/kết + nhạc nền (ducking tự động) → chuẩn hóa âm lượng (loudnorm)
   → xuất MP3 + video dạng sóng âm/avatar + show notes + chương (chapters).
```

### Giai đoạn 7 — AI Agent & Skills
```
Xây lớp Agent:
- Khung chat: người dùng ra lệnh tự nhiên ("dịch video này sang Anh và Nhật, lồng tiếng, cắt 3 clip TikTok").
- Agent loop: LLM cục bộ lập kế hoạch → gọi Tool (mỗi công cụ ở GĐ 2–6 lộ ra dạng tool có schema)
  → báo tiến độ → hỏi duyệt ở bước tốn tài nguyên hoặc khó đảo ngược.
- Hội thoại và giao diện trực quan dùng chung state machine (không có nguồn sự thật thứ hai).
- Skills: thư mục skills/<tên>/SKILL.md (mô tả khi nào dùng, các bước, tool cần gọi, tiêu chí đạt).
  Viết sẵn tối thiểu: video-localization, youtube-to-shorts, podcast-from-article,
  multi-market-campaign, stickman-explainer.
- Trình quản lý Skill: xem, bật/tắt, nhập/xuất, người dùng tự tạo Skill mới từ giao diện.
- Lịch tự động: chạy Skill theo lịch (ví dụ mỗi sáng tạo 1 clip từ video mới).
- Hỗ trợ MCP client để cắm công cụ ngoài (tùy chọn).
```

### Giai đoạn 8 — Chiến dịch đa thị trường, đóng gói, phát hành
```
A. "Chiến dịch nội dung": mục tiêu + thị trường + nền tảng → LLM lập kế hoạch 7/30 ngày
   → tự sinh bộ tài sản (kịch bản, video, phụ đề, thumbnail, caption, hashtag) cho từng ngôn ngữ
   → bảng theo dõi trạng thái → xuất gói (thư mục + CSV lịch đăng).
   Bản địa hóa: đơn vị, tiền tệ, cách xưng hô, văn hóa từng thị trường.
B. Đóng gói: bộ cài Windows x64, macOS (arm64/x64), Linux AppImage; script cài Python env tự động
   bằng uv; tùy chọn Docker cho bản web.
C. Tài liệu: README tiếng Việt + Anh, hướng dẫn cài theo hạng phần cứng, CONTRIBUTING, MODEL_LICENSES.
D. CI GitHub Actions: lint, typecheck, test, build bộ cài.
E. Kiểm tra cuối: chạy end-to-end 3 kịch bản mẫu (lồng tiếng video, podcast, chiến dịch 3 ngôn ngữ), ghi báo cáo vào docs/RELEASE_CHECK.md.
```

---

## PHẦN C — PROMPT KIỂM TRA CHẤT LƯỢNG (dùng sau mỗi giai đoạn)
```
Đóng vai người review độc lập. Kiểm tra giai đoạn vừa làm:
1. Chạy toàn bộ test, typecheck, lint. Báo kết quả thật.
2. Chạy thử luồng người dùng chính bằng file mẫu, ghi lại lỗi.
3. Rà bảo mật: daemon chỉ nghe 127.0.0.1, token, không lộ khóa, log đã che thông tin.
4. Rà license: mô hình mới thêm đã có trong registry.yaml chưa, cờ non_commercial đúng chưa.
5. Rà đạo đức: các luồng voice clone/avatar có hộp xác nhận chưa.
6. Liệt kê lỗi theo mức Nghiêm trọng / Trung bình / Nhỏ, sửa nhóm Nghiêm trọng ngay.
7. Cập nhật docs/PROGRESS.md.
```

---

## PHẦN D — CÁCH BẮT ĐẦU
1. Tạo thư mục trống `openstudio-ai`, mở bằng Claude Code.
2. Tạo file `CLAUDE.md`, dán nội dung Phần A.
3. Dán prompt Giai đoạn 0 → duyệt thiết kế → lần lượt Giai đoạn 1 đến 8.
4. Sau mỗi giai đoạn dán Phần C.
5. Giữ mỗi giai đoạn trong một phiên làm việc riêng để ngữ cảnh gọn.
