# Ghi chú tham khảo OpenCreator (Giai đoạn 0 — bước 1, bản nháp)

Nguồn: `OpenCreator-master/OpenCreator-master` (Apache-2.0). Chỉ đọc, không sửa.

## Sự thật quan trọng ảnh hưởng thiết kế
1. **Daemon của OpenCreator viết bằng TypeScript/Node, không phải Python.** `apps/daemon/src/*`
   (runs, creator, smart-dubbing, scheduler, memory, security...). CLAUDE.md đang chọn Python/FastAPI → khác biệt có chủ đích, cần bạn xác nhận (xem "Câu hỏi mở").
2. **Agent engine = Codex CLI** (OpenCreator không tự viết vòng lặp agent). OpenStudio phải tự viết vòng lặp gọn gọi Ollama.
3. **Pipeline media chính nằm ở binary Go `krillinai` (CLI)** do skills `krillinai-*` gọi (subtitle, tts, render-horizontal/vertical, cover). Zip này không chứa mã Go; OpenStudio phải tự cài đặt các bước này bằng FFmpeg + mô hình mở.
4. Repo có nhiều tài liệu/quy tắc tiếng Trung (`AGENTS.md`) — chỉ là quy tắc nội bộ của họ, không áp dụng cho ta.

## Mẫu thiết kế nên học
| Mẫu | Nơi xem | Áp dụng cho OpenStudio |
|---|---|---|
| Web là frontend duy nhất, Desktop chỉ bọc OS | `apps/web`, `apps/desktop` | Giữ nguyên |
| Runtime cục bộ: `127.0.0.1` + Bearer token, in `{address, token}` ra stdout, `/healthz` không cần auth | `docs/runtime-api-for-ui-v1.md`, `src/security/token.ts` | Giữ nguyên |
| Lỗi thống nhất `{error:{code,message,details}}` (401/400/404/409/422/502) | cùng file | Giữ nguyên |
| Run bất đồng bộ: `POST /runs` trả ngay + SSE sự kiện; hàng đợi, ngắt-và-tiếp-tục, duyệt hai chiều | `src/runs/*`, `src/approvals` | Học, đơn giản hoá bằng asyncio+SQLite |
| Tiến độ chuẩn hoá `phase, percent, message, completed, failed, total` | `AGENTS.md` mục Panel | Dùng làm schema SSE |
| **Một** `CreatorCollaborationPanel` dùng chung + `CreatorPanelAdapter` cho từng công cụ | `AGENTS.md`, `apps/web` | Học: không nhân bản panel cho từng công cụ |
| Stage runner/scheduler, command dispatcher, mọi lệnh qua REST/Agent như nhau | `src/creator/stage-runner.ts`, `command-dispatcher.ts` | State machine dùng chung UI + Agent |
| Artifact + `sourceArtifactIds`, snapshot kết quả, stale khi upstream đổi, chọn phiên bản không sửa cái cũ | `docs/creator-artifact-versions.md`, `result-snapshots.ts` | Cốt lõi của versioning |
| Template khai báo + validate/compile trong CI | `template/`, `pnpm templates:ci` | Học cho GĐ 5D |
| Skills = `skills/<tên>/SKILL.md` (frontmatter name/description; Command, Inputs, Flags, Outputs, Verification) | `skills/krillinai-*` | Cùng định dạng |
| Che thông tin nhạy cảm trong log/diagnostics | `src/security/redaction.ts` | Giữ nguyên |
| Bộ nhớ 3 tầng (global/project/thread), snapshot input của Run | `src/memory` | Tuỳ chọn, GĐ 7 |
| Dubbing: parse phụ đề → lập kế hoạch → TTS → ghép → mux | `src/smart-dubbing`, `creator/smart-dubbing` | Đúng pipeline GĐ 3B |
| Quản lý yt-dlp có phiên bản, cập nhật an toàn, giữ bản cũ nếu lỗi | README "Managed Runtime Components" | Học |

## Câu hỏi mở (cần bạn duyệt trước khi sang bước 2–4)
1. **Ngôn ngữ daemon:** giữ Python/FastAPI (hệ sinh thái AI tốt hơn, đúng CLAUDE.md) hay dùng TypeScript để tái dùng được mẫu mã của OpenCreator? Đề xuất: **Python**.
2. Có đồng ý bước 2 (tra cứu web phiên bản/license/VRAM của ~12 nhóm mô hình) chạy không? Việc này tốn nhiều lượt tìm kiếm.
