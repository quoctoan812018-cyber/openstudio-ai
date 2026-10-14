# PROGRESS

## Giai đoạn 0 — Khảo sát & thiết kế: XONG (2026-10-13)
Tài liệu: REFERENCE_NOTES, MODEL_LICENSES, ARCHITECTURE, ROADMAP, models/registry.yaml. Quyết định đã chốt ghi ở ARCHITECTURE mục 9.

## Giai đoạn 1 — Nền móng: XONG, chờ review (2026-10-13)

**Đã có**
- Monorepo pnpm + uv: `apps/daemon` (FastAPI), `apps/web` (React/Vite/TS/Tailwind), `apps/desktop` (Electron), `packages/protocol` (type TS sinh từ Pydantic).
- Daemon: `/healthz`, Bearer token (so sánh hằng thời gian), chỉ nghe 127.0.0.1 (config từ chối host khác), CORS chỉ origin web nội bộ, lỗi thống nhất `{error:{code,message,details}}`.
- Project / Revision (không ghi đè, chống xung đột bằng `expectedRevision`) / Job (pool luồng, huỷ, khôi phục job dở khi khởi động) / SSE có phát lại theo `Last-Event-ID` / SQLite migration đánh số.
- Phát hiện phần cứng + phân hạng; công cụ vượt hạng bị khoá kèm lý do.
- Model Manager: đọc registry, tải có tiến độ, kiểm tra kích thước + SHA-256, ghi `.part` rồi đổi tên, cảnh báo + bắt xác nhận với mô hình phi thương mại, xoá mô hình.
- Web: Dashboard (lưới công cụ), Cài đặt (phần cứng, mô hình, ngôn ngữ, thư mục dữ liệu, nhãn AI), Thư viện file (+ tạo project), i18n vi/en.
- Desktop: khởi động daemon, nhận handshake, nạp web qua `app://`, preload chỉ lộ địa chỉ+token.
- Lệnh: `pnpm dev`, `pnpm test`, `pnpm typecheck`, `pnpm protocol:gen`, `pnpm desktop:dev`.

**Đã kiểm chứng thật (không chỉ test)**
- `pytest`: 27 pass. `vitest`: 9 pass. `tsc --noEmit`: sạch. `vite build`: OK. Test desktop (handshake): 3 pass.
- Tải thật `faster-whisper-tiny` (75MB) qua daemon: SHA-256 khớp, trạng thái `installed`.
- `pnpm dev`: daemon :8787 và web :5173 chỉ nghe loopback; CORS từ origin lạ bị từ chối; giao diện hiển thị đúng trên trình duyệt.
- `pnpm --filter @openstudio/desktop smoke`: Electron mở được, daemon chạy, UI qua cổng kết nối (`SMOKE_OK`).

**Chưa làm / hạn chế**
- Máy hiện tại ở hạng CPU nên không thử được công cụ GPU.
- `pnpm desktop:dev` dùng bản build web (`pnpm --filter @openstudio/web build` trước), hoặc đặt `OPENSTUDIO_DEV_URL`.
- Bảng `event` chưa có dọn dẹp (sẽ tăng dần). `approval`, `consent`, `artifact_source` mới có bảng, chưa có API.
- Chưa có lint (ESLint/ruff) và CI (thuộc GĐ 8).
- Chưa tải được trọng số có `download` ngoài `faster-whisper-tiny` — các mô hình khác chưa có URL/checksum trong registry (bổ sung ở giai đoạn dùng chúng).
- Không đóng gói bộ cài; chưa ký ứng dụng.
- Ollama đã cài nhưng chưa chạy; chưa kéo mô hình LLM nào (GĐ 2).
- Chưa commit git (repo đã `git init`).

**Rủi ro**
- Tải mô hình hiện không hỗ trợ tiếp tục (resume) khi đứt mạng — với file nhiều GB cần bổ sung.
- Dev token chỉ nằm trong biến môi trường tiến trình; trang web dev nhận token qua `VITE_DAEMON_TOKEN` (có trong bundle dev) — chấp nhận ở loopback dev, không dùng cho bản phát hành.

## Giai đoạn 2 — Phụ đề & Dịch: XONG, chờ review (2026-10-13)

**Đã có**
- Nguồn: tải file lên (stream, giới hạn đuôi media) hoặc link qua yt-dlp (chỉ http/https); FFmpeg tách audio 16kHz mono; ffprobe.
- STT: faster-whisper chạy **tiến trình con** (huỷ được, giải phóng RAM), `word_timestamps` + VAD; tự chọn cỡ mô hình theo phần cứng/RAM trong số mô hình đã cài (turbo → small → tiny); thiếu mô hình trả `424 MODEL_MISSING` kèm id để UI mời tải.
- Tách cue từ mốc thời gian từng từ: ngắt theo dấu câu/khoảng lặng/độ dài, không bỏ từ, đảm bảo không chồng dòng.
- LLM cục bộ (Ollama): sửa chính tả/dấu/viết hoa, dịch nhiều ngôn ngữ cùng lúc theo lô có ngữ cảnh, văn phong (trung tính/trang trọng/thân mật), thị trường, bảng thuật ngữ (đưa vào prompt + đếm dòng vi phạm). Giữ nguyên thời gian và số cue; lô sai thì chia đôi tới từng dòng, hết cách thì giữ bản gốc và báo `fallbacks`.
- State machine `subtitles` dùng chung cho UI/Agent/job: lệnh `set-source`, `set-track`, `delete-track`, `set-glossary`, `set-options`, `select-revision`. Mỗi lệnh tạo **revision mới** (snapshot), sửa bản gốc thì các bản dịch bị đánh dấu `stale`.
- Trình sửa web: video/audio + danh sách cue, sửa chữ/thời gian, tách/gộp/xoá, dời toàn bộ ±0.1s, đối chiếu bản gốc khi sửa bản dịch, lưu = phiên bản mới.
- Xuất SRT/VTT/ASS, song ngữ (ghép theo thời gian, chọn thứ tự), burn-in 16:9 hoặc 9:16 (viền đen hoặc cắt giữa), nguồn chỉ có audio thì tạo nền đen.
- Hạ tầng: URL tải file có chữ ký HMAC hết hạn 1 giờ (thẻ `<video>`/`<a>` không gửi được header), `result` của job, `/llm/status`, registry thêm whisper small + large-v3-turbo (kèm SHA-256).

**Nghiệm thu thật** (`scripts/e2e_subtitles.py`: daemon thật + Whisper large-v3-turbo thật + qwen3:4b thật, máy CPU 15.5GB, 172s tổng cộng)
Mẫu tiếng Việt 2 phút (giọng tổng hợp) → phụ đề Việt → phụ đề Anh: 32 cue, không chồng dòng, khoảng trống lớn nhất 1.0s, phủ 0.0s–119.2s/120.2s, độ khớp kịch bản gốc 0.916, bản Anh đủ 32/32 cue, giữ nguyên thời gian, 0 dòng chưa dịch, xuất song ngữ SRT/VTT/ASS. Tất cả đạt.
Test tự động: pytest 62 (gồm burn-in ffmpeg thật cho 16:9, 9:16, audio-only), vitest 17.

**Lỗi thật đã tìm và sửa trong lúc làm**
- `subprocess` trên Windows dùng codepage cp1258 → lỗi giải mã khi tên file/log có tiếng Việt (đã ép UTF-8).
- qwen3:4b qua endpoint OpenAI-compat vẫn "suy luận" hàng nghìn token (một lô 2 dòng không xong sau 5 phút). Đã chuyển sang API gốc Ollama với `think:false` + ép JSON bằng schema: 2 dòng ~3–4s. Provider `openai` vẫn hỗ trợ qua `response_format`.
- Một mục registry sai đường dẫn từng làm hỏng cả danh sách `/models`.

**Hạn chế đã biết**
- Chất lượng thật chỉ đo trên **giọng tổng hợp** (Edge TTS), chưa đo giọng người/nhiều người nói/nhiễu nền. Cần thêm mẫu thật trước khi coi là đạt.
- Lỗi nhận dạng tên riêng vẫn xảy ra (vd "Buôn Ma Thuột" → "Buma thuộc"); bảng thuật ngữ chỉ mồi (initial_prompt) + sửa bằng LLM, chưa đảm bảo tuyệt đối. Dịch có lúc lỗi nhỏ ("in 1: 1854").
- Có thể còn cue lẻ ngắn (vd "Việt Nam." đứng riêng) do giới hạn 84 ký tự; chưa có bước gộp cue mồ côi.
- Chưa đa người nói (diarization), chưa tự dịch lại phần bị `stale`, chưa kiểm tra yt-dlp với link thật (chỉ test chặn scheme và đường code), chưa test trình duyệt tự động cho trang Subtitles (mới kiểm bằng tay trên dữ liệu thật + vitest cho CueEditor).
- Tốc độ trên CPU: Whisper turbo ~114s cho 2 phút audio (kể cả sửa lỗi LLM), dịch 1 ngôn ngữ ~56s; video dài hoặc nhiều ngôn ngữ sẽ lâu.
- Revision lưu snapshot đầy đủ mỗi lần lưu (video vài giờ sẽ nặng DB); cần dedupe sau.
- Ollama do em bật bằng `ollama serve` trong phiên này; sau khi tắt máy cần tự chạy lại.

## Giai đoạn 3 — Giọng đọc, nhân bản giọng, lồng tiếng: XONG, chờ review (2026-10-13)

**Đã có**
- **TTS** (tiến trình con, nạp mô hình một lần cho cả lô): VieNeu-TTS v3 Turbo (tiếng Việt, +en yếu hơn) và Kokoro-82M ONNX (en/ja/zh/es/fr/hi/it/pt). Mô hình tải qua Model Manager có SHA-256, chạy offline (`HF_HUB_OFFLINE`).
- **Công cụ Giọng đọc**: kịch bản nhiều người nói (`[Người A]`), ngắt nghỉ (`[nghỉ 1.5s]`, `[pause 500ms]`), thẻ cảm xúc VieNeu giữ nguyên; chọn giọng từng người, tốc độ 0.5–2.0, khoảng nghỉ, WAV/MP3; chuẩn hoá âm lượng (-16 LUFS), nhãn AI trong metadata; nghe thử giọng; trang web đầy đủ.
- **Nhân bản giọng có đồng ý** (CLAUDE.md mục 6): phải tạo bản ghi đồng ý (`confirmed:true`, tên chủ giọng, câu cam kết) → lưu DB + file `.runtime/consent/<id>.json` (kèm SHA-256 mẫu và id giọng); **mỗi consent dùng một lần**, đúng loại; mẫu 3–60s (khuyến nghị 10–30s); lỗi mẫu không làm hỏng consent; UI khoá nút tới khi tick xác nhận.
- **Lồng tiếng video**: gộp cue thành câu → TTS từng câu → khớp khung thời gian: vừa thì giữ, hơi dài thì tăng tốc (trần 1.0–1.6×, mặc định 1.3×), quá dài thì **LLM rút gọn** (tối đa 3 lượt, có giới hạn ký tự), hết cách thì tăng tốc tối đa + gắn cờ → Demucs tách nền (cache theo file nguồn) → đặt giọng theo mốc (đẩy lùi tối đa 1s nếu lấn) → nền được ducking bằng sidechain + loudnorm → ghép vào video (giữ nguyên luồng hình, `-c:v copy`) → SRT khớp với giọng đã đọc. Sửa một câu chỉ tổng hợp lại câu đó.
- API/State: `tts`, `dubbing` dùng chung cơ chế revision; lệnh nội bộ `_set-*` bị chặn khỏi API công khai.

**Nghiệm thu thật** (`scripts/e2e_dubbing.py`; Whisper turbo + qwen3:4b + Kokoro + Demucs thật, máy CPU)
Video 640×360 dài 121s (giọng Việt + nhạc nền tổng hợp) → phụ đề Anh → lồng tiếng Anh: 23 câu, 13 vừa khung + 10 tăng tốc (tối đa ×1.29), **0 lỗi, 0 câu còn quá dài**; mọi câu ≤ khung thời gian; độ lệch do đẩy lùi ≤ 0.02s; video giữ h264 640×360, độ dài đúng 121.00s; nhãn AI có trong metadata; nhạc nền còn nghe được ở khoảng lặng; nhận dạng lại bản lồng tiếng khớp lời **0.960**; giọng Việt gốc **không** lọt vào bản trộn (khớp 0.093). Thời gian: tổng hợp 48s, Demucs + trộn + ghép 84s. SRT 23 cue hợp lệ.
Giọng đọc thật: VieNeu (nhận dạng lại khớp, kể cả số "1854"), Kokoro tiếng Anh, giọng nhân bản VieNeu — đều đọc lại bằng Whisper và đúng nội dung.
Test tự động: pytest 90, vitest 25, desktop 3, `tsc` sạch. Gồm mô phỏng TTS để kiểm tra vị trí giọng trên dòng thời gian (RMS), LLM rút gọn, mux mp4, sửa một câu, thiếu LLM, thiếu mô hình.

**Lỗi/điểm cần lưu ý khi làm**
- Đường dẫn `/tmp` của MSYS không dùng được với Python Windows (chỉ ảnh hưởng script thử, không ảnh hưởng ứng dụng).
- `vieneu` kéo theo gradio và nhiều gói khác (môi trường daemon nặng lên); nên tách môi trường TTS riêng khi đóng gói (GĐ8).
- Worker VieNeu phải vá `OnnxV3LiteEngine.__init__` để trỏ codec ra thư mục cục bộ (thư viện không công khai tham số này) → **gắn chặt vào phiên bản `vieneu==3.8.3`**; nâng cấp phải chạy lại test.

**Hạn chế đã biết**
- Chưa đo độ giống của giọng nhân bản (chỉ kiểm tra đọc đúng nội dung); chưa thử nhân bản bằng giọng người thật. Mẫu thử là giọng tổng hợp.
- Mẫu nghiệm thu là giọng tổng hợp đọc rõ, không nhiễu, một người nói; chưa thử nhiều người nói chồng tiếng, nhạc có lời, tiếng ồn. Demucs với nhạc thật chưa kiểm tra chất lượng.
- Chưa có Piper/Edge TTS (đã hoãn), chưa có watermark hiển thị trên video (chỉ metadata + watermark âm thanh của VieNeu), chưa lồng tiếng đa người nói tự động (không có diarization — mỗi câu có thể chọn giọng riêng bằng tay).
- Kokoro không có tiếng Việt/Hàn/Thái/Đức/Nga/Indo → không lồng tiếng sang các ngôn ngữ đó (UI/API báo `UNSUPPORTED_LANGUAGE`).
- Chất lượng bản dịch phụ thuộc qwen3:4b ("Ba Giang" cho Tây Nguyên trong một câu) — nên cho người dùng rà bản dịch trước khi lồng tiếng.
- Chưa kiểm tra trình duyệt tự động cho hai trang mới (mới kiểm bằng tay trên dữ liệu thật + vitest).

## Giai đoạn 6 — Tóm tắt & Highlight, Podcast: XONG, chờ review (2026-10-13)

**Tóm tắt & Highlight** (dùng lại nguồn + transcript của công cụ Phụ đề & Dịch)
- **Tìm đoạn hay**: phân cảnh bằng FFmpeg (`select=scene`, ngưỡng 0.3) → dựng đoạn ứng viên luôn bắt đầu/kết thúc ở biên câu, "hít" biên tới mốc đổi cảnh chỉ khi khoảng dời không có lời nói → điểm heuristic (mật độ lời, câu hỏi/cảm thán, con số, từ khoá gây tò mò, trừ điểm chào hỏi/kết) + điểm LLM (tối đa 20 đoạn/ lần; 70% LLM + 30% heuristic) → chọn N đoạn không chồng, cách nhau ≥ 3s. Không có LLM vẫn chạy bằng heuristic.
- **Duyệt**: bật/tắt clip, sửa tiêu đề/hook/khung cắt (đổi thì xoá file đã xuất của clip đó), thêm clip thủ công, xem thử ngay trên video nguồn.
- **Xuất**: 9:16 (crop hoặc viền đen) hay 16:9, phụ đề burn-in (chọn ngôn ngữ phụ đề), tiêu đề giật tít 3.5s đầu.
- **Video tóm tắt có giọng dẫn**: LLM viết 1–2 câu dẫn mỗi clip → TTS → ghép; tiếng gốc hạ còn 18%; lời dẫn dài hơn clip thì giữ khung hình cuối (không cắt lời, không chồng lời); kèm phụ đề lời dẫn và file kịch bản.

**Podcast**
- Chủ đề và/hoặc tài liệu nguồn (.txt/.md, ≤200k ký tự) → dàn ý (chương) → lời thoại từng chương cho 2–3 người dẫn (ép JSON schema, bỏ markdown/tiền tố tên, chuẩn hoá tên người nói) → bạn sửa kịch bản được, hoặc tự viết hoàn toàn (không cần LLM).
- Giọng riêng cho từng người dẫn (VieNeu/Kokoro/giọng nhân bản), nhạc mở + nhạc kết + nhạc nền: **nhạc có sẵn do OpenStudio tự sinh (CC0)**, hoặc nhạc của bạn **kèm giấy phép bắt buộc**. Nhạc nền hạ tự động khi có người nói (ducking −12 dB, attack/release mượt), loudnorm −16 LUFS, MP3/WAV 48k stereo, **chương nhúng vào MP3**, video sóng âm + phụ đề lời thoại (16:9 hoặc 9:16), show notes `.md`, `chapters.txt` dạng YouTube.

**Nghiệm thu thật** (daemon thật + Whisper turbo + qwen3:4b + VieNeu, máy CPU 15.5GB)
- *Highlight* (`scripts/e2e_highlights.py`, video 121s hình đổi màu mỗi ~12s + giọng Việt): LLM chấm 20/24 đoạn; phát hiện **9/9** mốc đổi cảnh; chọn đủ 2 clip dài 34.3s và 22.3s, không chồng, **không cắt ngang lời** (kiểm tra với từng biên); xuất 1080×1920, độ dài đúng ±0.1s, có âm thanh; video tóm tắt dài 56.6s đúng bằng tổng các đoạn; nhận dạng lại lời dẫn khớp 0.80. Phân tích mất 147–363s tuỳ lần (LLM trên CPU).
- *Podcast* (`scripts/e2e_podcast.py`, 2 phút, 2 người dẫn): 2 chương, 10 lượt, 328 từ; MP3 98,1s, 2 chương nhúng đúng mốc; **−16,8 LUFS, đỉnh −4,8 dBFS**; không chồng lời; video 1280×720; show notes đủ mục; nhận dạng lại bản thành phẩm (có nhạc nền) khớp kịch bản **0.982**. Tổng 218s.
- Test tự động: pytest 120 (gồm ducking đo bằng RMS, cắt/ghép ffmpeg thật, chương MP3, nhạc người dùng + giấy phép), vitest 31, `tsc` sạch, desktop 3.

**Lỗi thật tìm thấy và đã sửa**
- Phát hiện cảnh: ngưỡng 0.35 + ảnh thử tối/giống nhau → bỏ sót hết. Hạ còn 0.3 và dùng ảnh thử tương phản (9/9). **Giới hạn thật**: chuyển cảnh mờ/tối có thể bị bỏ sót (chỉ ảnh hưởng việc hít biên).
- LLM chấm điểm chậm (363s/24 đoạn): rút `reason` ≤15 từ, cap 20 đoạn → 147–213s.
- Chỉ chọn được 1/2 clip vì bỏ hết đoạn chưa được LLM chấm → nay bù bằng đoạn heuristic, tránh trùng.
- Nhạc tổng hợp có sẵn bị vượt 1.0 (méo) khi các nốt chồng nhau → chuẩn hoá đỉnh.
- Tiêu đề giật tít vẽ bằng hộp nền nên các hộp từng dòng chồng lên nhau xấu → đổi sang viền chữ.
- **Phụ đề burn-in khung dọc (kể cả GĐ2) bị libass tự ngắt thành 3 dòng** vì chữ 96px quá to cho khung 1080 → chữ dọc 3.6% chiều cao (≈69px).
- qwen3:4b đôi khi chèn chữ Hán vào câu tiếng Việt ("người Pháp引入 cây này") → TTS đọc mất chữ. Thêm `strip_foreign_script` cho lời dẫn, kịch bản podcast, dịch, sửa lỗi, rút gọn (giữ nguyên khi ngôn ngữ đích là zh/ja/ko).
- qwen3:4b viết ngắn hơn yêu cầu ~35% (xin 440 từ, ra 277) → bù ×1.35 trong prompt.
- Giọng giả dùng `hash()` ngẫu nhiên giữa các tiến trình làm test ducking so sánh sai → dùng crc32.

**Hạn chế đã biết**
- Chất lượng chọn "đoạn hay" chỉ được đánh giá bằng độ hợp lý, không có đối chứng với người thật chọn; mẫu thử là một video 2 phút có lời tổng hợp. Chưa thử video dài (hàng giờ): cửa sổ ứng viên bị cắt còn tối đa 120 và LLM chỉ chấm 20 → có thể bỏ sót đoạn hay; thời gian phân tích tăng tuyến tính theo số cuộc gọi LLM.
- LLM 4B vẫn **bịa/ sai sự kiện** khi viết kịch bản và lời dẫn (vd "người dân dùng cà phê trứng để thay thế", "đất đỏ ba giang" do ASR sai ở nguồn) → luôn cần người rà trước khi đăng; UI cho sửa từng lượt/từng lời dẫn (lời dẫn: sửa qua kịch bản, chưa có ô sửa riêng).
- Video tóm tắt cần nguồn có hình; chưa lồng nhiều giọng trong một clip; chưa có chuyển cảnh giữa các clip (cắt thẳng).
- Podcast: chỉ nhận .txt/.md làm tài liệu nguồn (chưa PDF/DOCX/URL); nhạc tự sinh khá đơn giản (pad + arpeggio); chưa có "avatar" cho video (chờ GĐ4 trên máy có GPU); chưa kiểm tra giấy phép nhạc người dùng khai báo; chưa có tiếng cười/ngắt hơi tự nhiên giữa hai người dẫn (chỉ khoảng nghỉ cố định + 0.12s khi đổi người).
- Hai trang mới (Highlight, Podcast) mới kiểm bằng vitest + hàm render, chưa duyệt bằng trình duyệt tự động trên dữ liệu thật như hai trang trước.
- Ollama vẫn do em bật tay (`ollama serve`) trong phiên này.

## Giai đoạn 7 — AI Agent, Skills, lịch chạy, MCP: XONG, chờ review (2026-10-14)

**Đã có**
- **Vòng lặp Agent tự viết** (`agent/loop.py`) chạy trên Ollama; thiết kế cho LLM nhỏ: mỗi bước 2 lần gọi **ép JSON schema** (chọn 1 tool trong enum → điền tham số đúng schema của tool đó), Pydantic kiểm tra lại, lỗi thành observation để tự sửa. Giới hạn 14 bước, 3 lỗi liên tiếp, lặp y hệt 2 lần; bước bị từ chối không được nài lại; huỷ được giữa chừng (kể cả đang chờ duyệt).
- **23 tool** (`agent/tools.py`) gọi đúng service mà UI dùng → **cùng một state machine/revision** (lệnh của Agent ghi `author="agent"`): get_state, project_models, download_model, list_voices, subtitles_{fetch_url,transcribe,translate,glossary,export,burn}, dubbing_{setup,synthesize,mix}, highlights_{setup,analyze,export,summary}, podcast_{brief,write_script,produce}, speak_text, draft_text, ask_user.
- **Phê duyệt**: `render` (xuất/trộn media), `download` (tải mô hình), `external` (MCP) đều hỏi người dùng; mọi quyết định lưu bảng `approval`. "Tự duyệt" chỉ áp cho `render`, **không bao giờ** cho tải mô hình/MCP. Daemon tắt giữa chừng → yêu cầu đang chờ chuyển `expired`.
- **Skills** (`skills/<tên>/SKILL.md`, frontmatter + bước đánh số → checklist đưa vào prompt): 5 skill có sẵn (video-localization, youtube-to-shorts, podcast-from-article, multi-market-campaign, stickman-explainer); xem/bật-tắt/nhập/xuất/tạo từ giao diện; skill của bạn ở `.runtime/skills/`. Skill chỉ là văn bản, không chạy mã. LLM tự chọn skill hoặc dùng `/tên-skill` hoặc chọn tay.
- **Lịch chạy**: cron 5 trường (≥ 5 phút/lần), chạy nền, chạy bù 1 lần nếu trễ < 1 giờ, tự tắt khi project bị xoá, thử lại sau 5 phút khi LLM tắt; "Chạy ngay".
- **MCP client** tối giản (stdio JSON-RPC), mặc định không có server; tool MCP luôn qua phê duyệt, kết quả bị coi là dữ liệu không tin cậy.
- **Giao diện**: trang *Trợ lý AI* (hội thoại, thẻ tool_call/tool_result, thẻ duyệt Duyệt/Từ chối, nút huỷ, đính kèm media/tài liệu, chọn skill, tự duyệt) và *Skills & Lịch*.
- Hạ tầng: bảng `thread`, `message`, `schedule`; `agent.run` có pool riêng (4 luồng) để không làm đói job thật; `LLMClient.num_ctx=8192`.

**Nghiệm thu thật** (`scripts/e2e_agent.py`: qwen3:4b thật + Whisper + ffmpeg + VieNeu, máy CPU)
- A. "Tạo phụ đề tiếng Việt rồi dịch sang tiếng Anh": tự chọn đúng skill; get_state → transcribe → translate → export; state có vi + en; **không tool thừa**; 289s.
- B. "Cắt 2 clip dọc cho TikTok": setup → analyze → **xin duyệt** → export (script duyệt) → 2 clip 1080×1920; câu trả lời cuối liệt kê đúng 2 file; 363s.
- C. Project trống "Lồng tiếng video": get_state → **ask_user** ("Chưa có video nguồn…"), không gọi tool tốn tài nguyên; 40s.
- D. Podcast 2 người dẫn từ một câu lệnh: brief (Minh, Lan, 2 phút, vi) → viết kịch bản → xin duyệt → produce → có MP3.
- Test tự động: pytest 150, vitest 39, desktop 3, `tsc` sạch. Gồm: prompt injection qua kết quả MCP vẫn bị chặn ở cổng duyệt; từ chối không nài lại; tự duyệt không áp cho tải mô hình/MCP; huỷ khi đang chờ duyệt; tự sửa tham số sai; ask_user rồi tiếp tục hội thoại; checklist đánh dấu bước đã xong; cron/lịch bằng đồng hồ giả; MCP thật qua server giả (kể cả server im lặng → timeout, lệnh hỏng → không sập).

**Lỗi thật tìm thấy và đã sửa**
- Ollama tự đặt ngữ cảnh **4096** khi không có VRAM → prompt Agent bị cắt cụt. Nay ép `num_ctx=8192` (`config.toml [llm]`).
- Câu trả lời cuối của qwen3:4b **chép lại nguyên yêu cầu** người dùng (lần chạy đầu) → nay phần dữ kiện (việc đã làm, **tệp thật**, bước bị từ chối/lỗi) do code dựng từ các bước; LLM chỉ viết 1–2 câu nhận xét (bị bỏ nếu là bản chép).
- Sau khi xuất xong, mô hình gọi `get_state` lặp 3 lần mới dừng (mất ~4 phút) → chặn lặp còn 2 lần + nhắc "bước trước thành công và yêu cầu đã đủ thì chọn final".
- Lần đầu e2e gặp LLM chưa sẵn sàng (Ollama chưa chạy lại sau khi bật máy) → API trả `424 LLM_UNAVAILABLE` rõ ràng.

**Hạn chế đã biết**
- **Độ tin cậy của LLM 4B**: không có đối chứng thống kê, chỉ 4 kịch bản chạy thật (đều đạt, nhưng đã thấy lỗi nhỏ: dịch kèm cả ngôn ngữ gốc `["vi","en"]` — daemon tự lọc; không xuất SRT bản Anh; 1 lần `get_state` thừa). Với yêu cầu phức tạp/mơ hồ nên dùng Skill hoặc dùng thẳng các trang công cụ. Mỗi bước tốn ~10–30s LLM trên CPU.
- Agent không thể tự tải file lên: người dùng phải đính kèm (UI) hoặc đưa link; tài liệu podcast chỉ .txt/.md.
- Mô hình bịa chi tiết ở các tool viết nội dung (kịch bản, lời dẫn, caption) → cần người rà.
- Một lần chạy podcast qua Agent mất **1401s ở bước produce** (đo lại riêng lẻ chỉ 57s): nghi nghẽn bộ nhớ (còn ~2,9GB RAM trống khi Ollama giữ qwen3 + VieNeu) hoặc OneDrive đồng bộ thư mục `.runtime` — chưa tái hiện/chưa xác định. Khuyến nghị đặt `data_dir` ngoài OneDrive và cho Ollama nhả mô hình (`keep_alive`) trước các job nặng.
- Chưa có "bộ nhớ" dài hạn (global/project/thread) như OpenCreator; lịch chạy dùng múi giờ máy; chưa hỏi lại khi thiếu tham số (LLM tự điền hoặc báo lỗi); chưa có test trình duyệt tự động cho hai trang mới.
- Skill `stickman-explainer` dừng ở kịch bản + giọng dẫn (chưa có công cụ vẽ hình, chờ GĐ5/GPU) và nói thẳng điều đó với người dùng.
- Ollama do em bật bằng `ollama serve` sau khi máy khởi động lại; cần tự chạy lại sau mỗi lần khởi động.

## Giai đoạn 8 — Chiến dịch nội dung, đóng gói, CI, tài liệu, kiểm tra cuối: XONG phần làm được trên máy này (2026-10-14)

**Đã có**
- **Chiến dịch nội dung** (`apps/daemon/openstudio/campaign/`, trang *Chiến dịch*, 4 tool Agent, skill `multi-market-campaign` viết lại): brief → kế hoạch 7/14/30 ngày (ý tưởng do LLM, **lịch + giá quy đổi + giới hạn nền tảng do code**) → tài sản từng bài bản địa hoá (caption, hashtag, kịch bản, thumbnail từ khung hình thật, phụ đề/video từng ngôn ngữ) → bảng theo dõi (duyệt/đã đăng) → xuất thư mục + `schedule.csv` (giờ địa phương + UTC) + zip. Chi tiết: ARCHITECTURE §8f.
- **Đóng gói** (ARCHITECTURE §8g): Electron đóng gói + `uv` đi kèm tạo môi trường Python ở lần mở đầu; Dockerfile/compose cho web; torch CPU cho Linux; `/system/doctor` + Cài đặt → Chẩn đoán; `LICENSE` Apache-2.0.
- **CI**: `ci.yml`, `release.yml`; lint (ESLint + ruff, đã dọn sạch), `scripts/check_licenses.py`, test quét toàn bộ route cần token.
- **Tài liệu**: README (vi + en), `docs/INSTALL.md` theo hạng phần cứng, `CONTRIBUTING.md`, `MODEL_LICENSES.md` bổ sung, `docs/RELEASE_CHECK.md`.

**Nghiệm thu** — xem [RELEASE_CHECK.md](RELEASE_CHECK.md): 3 kịch bản thật (lồng tiếng, podcast, chiến dịch 3 ngôn ngữ) đạt; pytest 165, vitest 41, desktop 6, tsc/lint sạch; bộ cài Windows dựng được và gói đã đóng gói qua smoke test.

**Lỗi thật tìm thấy và đã sửa**: caption Mỹ lọt dấu tiếng Việt (→ `plain_latin`); 31 lỗi ruff (gồm closure `i` trong `subtitles/service.py`); `app://` so sánh tiền tố thư mục lỏng; registry thiếu license/sha256 ở vài mục (kiểm tự động nay chặn); `to_ass` escape `\an` bị heredoc làm hỏng (đã sửa từ trước và test).

**Chưa kiểm chứng / còn lại (nói thẳng)**
- macOS & Linux installer, GitHub Actions, Docker image: **chưa chạy lần nào**. Bộ cài Windows dựng được nhưng **chưa cài thử** và **chưa ký số**.
- Chất lượng nội dung LLM 4B (bịa chi tiết, dịch sai địa danh) → người bản ngữ phải rà.
- Avatar, ảnh, video (Giai đoạn 4, 5) vẫn chưa làm (cần GPU).
- Chưa quét license phụ thuộc Python/JS; chưa test trình duyệt tự động cho các trang mới.
- **Chưa có commit nào** (repo chưa có commit đầu); chưa có remote.

## Giai đoạn 4 + 5 — Avatar, Chỉnh sửa video, Thumbnail, Template: XONG phần chạy được trên CPU (2026-10-14)

Máy kiểm **không có GPU** (Intel Graphics, 15 GB RAM) nên làm theo nguyên tắc "khoá công cụ vượt khả năng máy, nói thẳng": chỉ làm và kiểm thử thật những phần chạy được; **không viết code mô hình GPU mà không thể chạy thử**.

**Đã có (đều kiểm thử thật bằng FFmpeg/VieNeu)**
- **Kho tài nguyên project** (`assets.py`): tải lên video/ảnh/audio (dò bằng ffprobe, file hỏng bị xoá), đưa file có sẵn (vd. kết quả TTS) vào kho.
- **Chỉnh sửa video** (5C, `editor/`): dòng thời gian một track hình — cắt (in/out), cắt đôi, ghép, sắp xếp, **tốc độ 0,25–4×**, âm lượng, **chuyển cảnh** (fade/dissolve/wipe/slide) kèm acrossfade, **chữ** (vị trí/cỡ/màu, đủ dấu tiếng Việt), **ảnh/video chèn**, **nhạc nền tự hạ khi có lời** (sidechain), 16:9/9:16/1:1, xem trước nhanh 360p và xuất 480/720/1080p. Mọi sửa đổi vô hiệu hoá bản xuất cũ (tạo revision mới).
- **Thumbnail & ảnh bìa** (5A phần không-AI, `thumbnail/`): ảnh/khung hình video/gradient + tiêu đề tiếng Việt + logo; 4 bố cục × 5 bảng màu, nhiều biến thể thật sự khác nhau; 16:9, 9:16, 1:1.
- **Template** (5D, `templates.py` + thư mục `templates/`): `template.json` cho thumbnail và editor; 5 mẫu có sẵn (chỉ đọc) + template của người dùng trong `<data>/templates`; áp từ giao diện. *Chưa có ảnh mẫu `preview.png` và chưa có template "prompt" (chờ có công cụ tạo ảnh AI).*
- **Avatar AI** (4, `avatar/`): thư viện avatar do người dùng tạo; **bắt buộc khai báo có phải người thật không**; người thật cần bản ghi đồng ý (`consent` loại `face`, mỗi bản ghi chỉ dùng một lần, **kiểm lại lúc xuất**); hoạt hình theo giọng **"puppet"** trên CPU (miệng mở theo biên độ; ghép nền mờ/màu/ảnh, khung bo/tròn, viền, phụ đề từ công cụ Phụ đề, nhãn AI trong metadata, watermark tuỳ chọn); xuất 16:9, 9:16, 1:1.
- Agent: thêm `thumbnail_make`, `editor_render` (duyệt), `avatar_make` (duyệt). Giao diện: 3 trang mới (Avatar AI, Chỉnh sửa video, Thumbnail) + bảng tài nguyên, i18n vi/en.

**Nghiệm thu** — `scripts/e2e_creative.py` (daemon thật + VieNeu thật): giọng Việt 10 s → avatar 16:9 (dài khớp giọng ±0,01 s; độ tối vùng miệng dao động theo giọng thật) → editor 9:16 (thẻ tiêu đề + avatar + chuyển cảnh + chữ + nhạc; 12,04 s so với 12,03 s mong đợi) → 3 thumbnail từ khung hình video: **14/14 đạt**. pytest 183, vitest 45, desktop 6, lint/tsc sạch.

**Không làm được / nói thẳng**
- *(Cập nhật: tạo ảnh AI và ảnh→video chuyển động đã làm ở mục "Giai đoạn 5B" bên dưới; hai gạch đầu về tạo ảnh/video AI trong danh sách này không còn đúng cho phần ảnh.)*
- **Lip-sync AI thật (MuseTalk, LatentSync) — chưa làm.** "Puppet" chỉ mở/đóng miệng theo âm lượng, **không khớp khẩu hình từng âm**; hợp ảnh minh hoạ/mascot, với ảnh chụp thật chỉ là hiệu ứng đơn giản (kéo giãn vùng miệng làm méo hàm nhẹ). Hai engine kia hiện trong giao diện với trạng thái khoá + lý do. Việc đọc license MuseTalk/LatentSync và chọn lượng tử hoá vẫn chờ máy có GPU.
- **Tạo ảnh AI (FLUX…) và tạo video (Wan/LTX…) — chưa làm**, công cụ `image`/`video` giữ nguyên trạng thái khoá theo hạng GPU. Quyết định "thử bản lượng tử hoá FLUX.2 klein ở Giai đoạn 5" **chưa thực hiện được**, cần máy GPU.
- Editor chỉ có **một track hình tuần tự** (chưa kéo-thả đa track, chưa keyframe, chưa lớp điều chỉnh màu); giao diện là danh sách có ô số, không có timeline đồ hoạ kéo thả. Xem trước là xuất 360p, chưa phát trực tiếp.
- Thumbnail không tự nhận diện mặt/chủ thể để cắt cho đẹp (chỉ cắt giữa + lệch nhẹ giữa các biến thể).
- Giao diện 3 trang mới chỉ kiểm bằng vitest cho các hàm/thành phần chính (chưa có test trình duyệt tự động).

## Giai đoạn 5B — Tạo ảnh AI (CPU) và Tạo video từ ảnh: XONG phần chạy được trên CPU (2026-10-14)

Anh chọn FLUX.2 klein 4B và "ảnh → video chuyển động bằng FFmpeg" cho video.

**Đã có**
- **Tạo ảnh AI** (`image/`): FLUX.2 klein 4B **GGUF Q4_0** + bộ mã hoá chữ **Qwen3-4B Q4_K_M** + VAE, chạy bằng **stable-diffusion.cpp** (`sd-cli`, MIT) trên **CPU**, 4 bước, cfg 1.0. Tất cả **Apache-2.0** (đọc từ HF API), tải qua Model Manager có **SHA-256** (engine ~18 MB + mô hình ~5,3 GB). Prompt tiếng Việt được LLM cục bộ dịch sang tiếng Anh (tuỳ chọn); hỗ trợ ảnh tham chiếu (`-r`), seed, 1–4 biến thể; nhả RAM Ollama trước khi chạy; ảnh vào kho tài nguyên để dùng ở Thumbnail/Editor/Avatar; nhãn "AI tạo" dạng sidecar `.png.json`.
- **Tạo video** (`video/`): ảnh → clip chuyển động (zoom in/out, lia trái/phải/lên/xuống) bằng `zoompan`, có nhạc/giọng tuỳ chọn, 16:9·9:16·1:1. **Không phải AI sinh video** (UI và API ghi rõ `generative:false`).
- Agent: `image_generate`, `video_from_image` (cần duyệt). Giao diện: 2 trang mới.

**Đo thật trên máy này (CPU, RAM trống 1–5 GB)**: ảnh 512×512 ≈ **248 s** (≈ 52 s/bước; nạp 15 s + giải mã VAE 26 s); ảnh 512×288 qua daemon ≈ **166 s**. Ảnh lớn hơn chậm theo ~bình phương cạnh (768 px ước ~9 phút, 1024 px ~16 phút — **ước lượng, chưa đo**). Chất lượng ảnh nhìn bằng mắt: tốt (ly cà phê, ánh nắng rõ nét); prompt "cà phê phin" cho ra bình/ly kim loại chứ không đúng dụng cụ phin → mô hình không hiểu chính xác đồ vật đặc thù Việt Nam.

**Nghiệm thu** — `scripts/e2e_images.py`: 9/9 đạt (engine/mô hình nhận đã cài, ảnh thật 313 KB, prompt được dịch, ảnh tự vào kho, nhãn AI, video 9:16 dài 5 s, thumbnail tiếng Việt đè lên ảnh AI). pytest 192, vitest 46.

**Không làm / nói thẳng**
- **Sinh video bằng AI (Wan, LTX…) vẫn chưa làm** — hiện trong giao diện ở trạng thái khoá; trên CPU không thực tế.
- **AI vẽ chữ tiếng Việt trong ảnh không đáng tin** → dùng công cụ Thumbnail để thêm chữ.
- Engine Linux/macOS (`sd-cpp-linux-x64` build trên Ubuntu 24.04, `sd-cpp-macos-arm64` build trên macOS 26) **chưa chạy thử**; có thể không chạy trên bản OS cũ hơn (Docker `bookworm`).
- Chưa thử Vulkan/iGPU (có bản `win-vulkan` của sd.cpp) — có thể nhanh hơn trên Intel Graphics nhưng chưa kiểm chứng.
- Chưa có template "prompt" cho ảnh; chưa có inpainting/ControlNet.
