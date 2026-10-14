# Đóng góp cho OpenStudio AI / Contributing

Cảm ơn bạn đã quan tâm! Dự án giấy phép [Apache-2.0](LICENSE); đóng góp của bạn được cấp theo cùng giấy phép.
*English readers: the rules below apply equally; code comments and UI strings are Vietnamese-first with English i18n.*

## Nguyên tắc không thương lượng
1. **Chạy hoàn toàn cục bộ, không cần API key.** Nhà cung cấp cloud chỉ là tuỳ chọn, tắt mặc định, gắn nhãn "Có thể mất phí".
2. **Daemon chỉ nghe 127.0.0.1 + Bearer token.** Không thêm route công khai (test `test_every_route_requires_token_except_allowlist` sẽ fail).
3. **Đồng ý khi nhân bản giọng / avatar từ người thật**: phải qua cổng xác nhận và lưu bản ghi. Không thêm preset giọng người thật/nổi tiếng.
4. **License mô hình**: mọi mô hình mới phải vào [models/registry.yaml](models/registry.yaml) với `weights_license`, `commercial_ok`, `non_commercial`, nguồn tải + `sha256` (file > 5 MB), và được ghi trong [docs/MODEL_LICENSES.md](docs/MODEL_LICENSES.md). Mô hình phi thương mại phải có `non_commercial: true`, không là mặc định, không đóng gói. `pnpm check:licenses` kiểm tự động.
5. **Mọi sửa đổi tạo phiên bản mới** (revision), không ghi đè. Lệnh nội bộ của job đặt tên bắt đầu bằng `_` và bị chặn khỏi API công khai.
6. **Không hard-code đường dẫn.** Cấu hình qua `config.toml` + biến môi trường `OPENSTUDIO_*`.
7. **Không đưa dữ liệu nhạy cảm vào log** (dùng `security.redact`).

## Thiết lập
Cần Node ≥ 20 + pnpm, [uv](https://docs.astral.sh/uv/), FFmpeg (có libass), tuỳ chọn Ollama.
```bash
pnpm install
uv sync --project apps/daemon
pnpm dev
```

## Trước khi mở PR
```bash
pnpm lint            # ESLint + ruff
pnpm typecheck
pnpm test            # pytest + vitest + test desktop
pnpm check:licenses
pnpm protocol:gen    # nếu đổi schema Pydantic công khai
```
CI (`.github/workflows/ci.yml`) chạy đúng các bước này trên Ubuntu và Windows.

## Cấu trúc
- `apps/daemon` — FastAPI, SQLite, job runner, service từng công cụ (`subtitles/`, `tts/`, `dubbing/`, `highlights/`, `podcast/`, `campaign/`, `agent/`).
- `apps/web` — React + Vite + TypeScript; i18n ở `src/i18n/{vi,en}.json` (thêm khoá vào **cả hai**).
- `apps/desktop` — Electron (chỉ bọc web + khởi động daemon); `electron-builder.yml` cho bộ cài.
- `skills/<tên>/SKILL.md` — Skill (chỉ văn bản; không chạy mã).
- `docs/` — kiến trúc, tiến độ, license, kiểm tra phát hành.

## Thêm một công cụ mới (theo mẫu `campaign/`)
1. `state.py`: reducer thuần (`set-*` công khai, `_*` nội bộ cho job) + kiểm tra đầu vào.
2. `service.py`: đăng ký reducer + job; mọi thay đổi qua `repo.apply_command`.
3. `api.py` + nối vào `app.py`; thêm id vào `IMPLEMENTED` trong `tools.py`.
4. Tool cho Agent trong `agent/tools.py` (đặt `approval` nếu tốn tài nguyên) + cập nhật/ thêm skill.
5. Trang React + khoá i18n vi/en + test vitest.
6. Test pytest với FakeLLM (`tests/conftest.py`); không gọi mạng/LLM thật trong test tự động. Kịch bản thật đặt ở `scripts/e2e_*.py`.

## Commit
Nhỏ, rõ ràng: `feat(dubbing): …`, `fix(stt): …`, `docs: …`. Một thay đổi hành vi = kèm test.

## Báo lỗi
Nêu hệ điều hành, hạng phần cứng, bản `pnpm doctor`, và (nếu có) mã lỗi `error.code`. **Đừng dán token hay khoá API** — log đã được che nhưng hãy kiểm tra lại.
