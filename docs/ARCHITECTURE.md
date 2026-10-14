# ARCHITECTURE — OpenStudio AI (bản nháp GĐ0, chờ duyệt)

## 1. Sơ đồ khối

```
┌──────────────── Electron (apps/desktop) ────────────────┐
│ chỉ: chọn thư mục, cửa sổ, tray, thông báo; khởi động daemon │
└───────────────┬──────────────────────────────────────────┘
                │ tải cùng một bản build
┌───────────────▼───────────────┐   HTTP + SSE (127.0.0.1, Bearer)
│ apps/web  React+Vite+TS       │◄─────────────────────────────┐
│ Dashboard · Công cụ · Agent   │                              │
│ Panel dùng chung + Adapter    │                              │
└───────────────────────────────┘                              │
                                            ┌──────────────────▼────────────────┐
                                            │ apps/daemon  Python 3.11 FastAPI   │
                                            │  api/      REST + SSE              │
                                            │  core/     Project·Job·Version·    │
                                            │            Artifact·Approval       │
                                            │  machines/ state machine từng công cụ│
                                            │  agent/    vòng lặp agent → Ollama │
                                            │  skills/   nạp SKILL.md            │
                                            │  models/   Model Manager           │
                                            │  media/    ffmpeg·yt-dlp wrapper   │
                                            │  workers/  asyncio + SQLite queue  │
                                            └───────┬────────────┬───────────────┘
                                                    │            │
                                  tiến trình con (subprocess,    SQLite + .runtime/
                                  cô lập, 1 mô hình/lúc):        (db, models, projects,
                                  faster-whisper · VieNeu ·      logs, consent)
                                  Demucs · MuseTalk · diffusers
                                  Ollama (dịch vụ riêng, :11434)
```

Nguyên tắc: **web là frontend duy nhất**; **một state machine cho mỗi công cụ**, UI và Agent cùng gửi *command* vào đó; mô hình AI nặng chạy ở **tiến trình con** (tránh xung đột phụ thuộc, giải phóng VRAM khi xong, cho phép gọi tiến trình GPL như Piper mà không link).

## 2. Cấu trúc monorepo

```
openstudio-ai/
  apps/
    web/            React 18, Vite, TS, Tailwind, XState, i18n (vi, en)
    daemon/         Python (uv), FastAPI, pytest
      openstudio/{api,core,machines,agent,skills,models,media,workers,security,tools}
    desktop/        Electron
  packages/
    protocol/       JSON Schema (sinh từ Pydantic) → type TS
  skills/<tên>/SKILL.md
  templates/<tên>/template.json
  models/registry.yaml
  docs/
  scripts/          dev, kiểm tra template, sinh protocol
  config.toml       cấu hình mặc định (+ biến môi trường OPENSTUDIO_*)
  .runtime/         (git-ignored) db, models, projects, logs, consent
```
Lệnh: `pnpm dev` (web+daemon), `pnpm test` (vitest + pytest), `pnpm desktop:dev`.

## 3. Runtime API v1

**Kết nối:** daemon chỉ nghe `127.0.0.1`, cổng ngẫu nhiên; stdout in một dòng JSON `{"address","token"}`. Mọi route trừ `GET /healthz` cần `Authorization: Bearer <token>`. Lỗi thống nhất:
`{"error":{"code","message","details?"}}` — 401 UNAUTHORIZED, 400 VALIDATION_FAILED, 404 *_NOT_FOUND, 409 *_CONFIRMATION_REQUIRED, 422 *_INVALID, 424 MODEL_MISSING, 503 HARDWARE_UNSUPPORTED.

| Nhóm | Endpoint |
|---|---|
| Hệ thống | `GET /healthz` · `GET /system/hardware` (cpu, ram, gpu, vram, tier) · `GET/PUT /settings` |
| Mô hình | `GET /models` (registry + trạng thái + license + cờ NC) · `POST /models/{id}/download` · `DELETE /models/{id}` |
| Project | `POST/GET /projects` · `GET/PATCH/DELETE /projects/{id}` · `GET /projects/{id}/files` |
| Tool | `GET /tools` (kèm `available`, `locked_reason`) · `POST /projects/{id}/tools/{tool}/commands` (body: `{type, payload, expectedRevision}`) · `GET /projects/{id}/tools/{tool}/state` |
| Job | `GET /jobs?projectId=` · `GET /jobs/{id}` · `POST /jobs/{id}/cancel` · `POST /jobs/{id}/resume` |
| Sự kiện | `GET /events?projectId=&jobId=` (SSE, hỗ trợ `Last-Event-ID`) |
| Phê duyệt | `GET /approvals` · `POST /approvals/{id}` `{decision: approve|reject}` |
| Phiên bản | `GET /projects/{id}/artifacts` · `GET /artifacts/{id}/content` · `POST /projects/{id}/versions/{vid}/select` |
| Đồng ý | `POST /consents` `{kind: voice|face, subject, statement}` → `consentId` (bắt buộc cho voice clone/avatar) |
| Agent | `POST /threads` · `POST /threads/{id}/messages` · `GET /threads/{id}` |
| Skills | `GET /skills` · `PUT /skills/{name}/enabled` · `POST /skills/import` · `GET /skills/{name}/export` |
| Lịch | CRUD `/schedules` · `POST /schedules/{id}/run-now` |
| Chẩn đoán | `GET /runs/{id}/diagnostics` (đã che thông tin nhạy cảm) |

### Sự kiện SSE
Mọi sự kiện: `id` tăng dần, `event:` = loại, `data:` = JSON có `projectId`, `jobId?`, `ts`.

| event | data chính |
|---|---|
| `job.queued / job.started / job.succeeded / job.failed / job.cancelled` | `{tool, stage, error?}` |
| `job.progress` | `{phase, percent, message, completed, failed, total}` (schema chuẩn hoá duy nhất cho tiến độ) |
| `model.download.progress` | `{modelId, bytes, totalBytes, percent}` |
| `state.changed` | `{tool, state, revision}` — nguồn sự thật duy nhất cho UI và Agent |
| `artifact.created / artifact.stale` | `{artifactId, kind, sourceArtifactIds}` |
| `approval.requested / approval.resolved` | `{approvalId, reason, cost}` (cost: thời gian/VRAM ước tính) |
| `agent.message / agent.tool_call / agent.tool_result` | luồng hội thoại |

## 4. State machine công cụ (mẫu chung)

`input → config → generating → review → editing → export`, mỗi bước là **stage**. Command có `expectedRevision` để chống ghi đè đồng thời; chạy `generating` tạo Job.
Quy tắc phiên bản:
- Sửa cấu hình hoặc kết quả → tạo **Revision/Version mới**, không ghi đè.
- Artifact có `sourceArtifactIds`; khi upstream đổi, artifact hạ nguồn bị đánh dấu `stale` (không tự xoá).
- "Chọn phiên bản kết quả" chỉ trỏ lại snapshot, không chạy lại stage.
- Một **CollaborationPanel duy nhất** ở web cho mọi công cụ; khác biệt qua `PanelAdapter` (nhãn stage, chuẩn hoá tiến độ, gợi ý composer).

## 5. Mô hình dữ liệu SQLite (rút gọn)

```
project(id, name, created_at, settings_json)
thread(id, project_id, title, created_at)                      -- hội thoại Agent
tool_state(project_id, tool, revision, state_json)             -- state machine hiện tại
revision(id, project_id, tool, n, parent_id, config_json, created_at, author[ui|agent])
job(id, project_id, tool, stage, revision_id, status, progress_json, error_json,
    created_at, started_at, finished_at, hw_requirement)
artifact(id, project_id, job_id, kind, path, sha256, bytes, meta_json,
         stale, created_at)
artifact_source(artifact_id, source_artifact_id)
result_snapshot(id, project_id, tool, revision_id, artifact_ids_json, selected)
approval(id, job_id, reason, estimate_json, status, decided_at)
consent(id, kind, subject, statement, project_id, created_at, evidence_path)
model(id, version, path, sha256, bytes, status, installed_at)
skill(name, path, enabled, source)
schedule(id, skill, cron, project_id, enabled, last_run_at)
event(id, project_id, type, payload_json, ts)                  -- nhật ký có thể phát lại SSE
memory(id, scope[global|project|thread], text, created_at)     -- tuỳ chọn, GĐ7
```
Migration: Alembic (hoặc script đánh số tay) chạy khi khởi động; có test mở lại DB.

## 6. Vòng đời Job

```
queued ─► waiting_model ─► waiting_approval? ─► running ─► succeeded
   │            │                  │               │   └► failed ─► (resume|retry)
   └────────────┴──────────────────┴───────────────┴────► cancelled
```
- `waiting_model`: thiếu mô hình → trả 424, UI mời tải.
- Cổng phần cứng: nếu `tier` máy < `hw_requirement` → 503 HARDWARE_UNSUPPORTED với lý do cụ thể.
- Worker: hàng đợi trong SQLite + asyncio; **mặc định 1 job GPU tại một thời điểm**; mỗi mô hình chạy trong tiến trình con, nạp khi cần, thoát khi xong.
- Resume: job chia checkpoint theo từng đoạn (ví dụ từng câu TTS), khởi động lại daemon vẫn tiếp tục được.
- Huỷ: kill cả cây tiến trình (ffmpeg + mô hình).

## 7. Agent

Vòng lặp tự viết (~vài trăm dòng): `messages → LLM (Ollama, OpenAI-compatible, tools) → tool_call → thực thi qua cùng command dispatcher của UI → tool_result → lặp`. Công cụ lộ ra dạng tool có JSON schema sinh từ Pydantic. Bước tốn tài nguyên/khó đảo ngược sinh `approval`. Provider khác cắm qua `config.toml` (`[llm] base_url, model, api_key_env`); cloud tắt mặc định, nhãn "Có thể mất phí".
Rủi ro: LLM cục bộ nhỏ gọi tool kém → dùng kế hoạch có cấu trúc (JSON), giới hạn số tool mỗi lượt, và Skill làm "kịch bản" cố định.

## 8. Bảo mật & đạo đức
- Chỉ nghe loopback; token ngẫu nhiên mỗi lần chạy; CORS chỉ nguồn web nội bộ; truy cập file qua API đã xác thực, chặn path traversal.
- Log qua bộ che (token, đường dẫn người dùng, khoá API, URL có chữ ký).
- Voice clone/avatar: API từ chối nếu thiếu `consentId` hợp lệ; consent lưu kèm thời gian, tên đối tượng, tuyên bố, ảnh/âm mẫu băm.
- Metadata "AI-generated" ghi vào file xuất (tuỳ chọn), watermark hiển thị tuỳ chọn.
- Không tải trọng số tự động; mô hình `non_commercial` hiện cảnh báo và phải bấm xác nhận.
- yt-dlp/FFmpeg gọi bằng danh sách đối số (không qua shell).

## 8b. API bổ sung (GĐ2)
| Route | Mô tả |
|---|---|
| `PUT /projects/{id}/subtitles/upload?filename=` | body thô = file media → job `subtitles.prepare` |
| `POST /projects/{id}/subtitles/fetch` `{url}` | yt-dlp (http/https) → job |
| `POST .../subtitles/transcribe` `{language?, model?, polish?}` | 424 `MODEL_MISSING` nếu chưa tải mô hình |
| `POST .../subtitles/translate` `{targets[], tone?, market?}` | 424 `LLM_UNAVAILABLE`/`LLM_MODEL_MISSING` |
| `POST .../subtitles/export` `{lang, format, second?, order, layout}` | ghi file vào `exports/`, trả đường dẫn |
| `POST .../subtitles/burn` `{lang, second?, order, layout, fit, font?, size?}` | ffmpeg burn-in → job, `result.path` |
| `POST /projects/{id}/file-url` `{path}` | URL ký HMAC, hết hạn 1 giờ, dùng cho `<video>`/`<a>` |
| `GET /files/{id}/{path}` | Bearer **hoặc** `?exp=&sig=` |
| `GET /llm/status` | Ollama sống? có mô hình cấu hình không? |
Job có thêm trường `result`. Lệnh state machine `subtitles`: `set-source`, `set-track`, `delete-track`, `set-glossary`, `set-options`, `select-revision`.

## 8c. API bổ sung (GĐ3)
| Route | Mô tả |
|---|---|
| `GET /tts/engines` · `GET /voices?lang=` | engine (vieneu, kokoro) + trạng thái mô hình; giọng có sẵn + giọng nhân bản |
| `POST /consents` `{kind, subject, confirmed}` | **bắt buộc** `confirmed:true` (409 `CONSENT_REQUIRED` nếu không); lưu DB + `.runtime/consent/<id>.json` |
| `PUT /voices/clone?name=&consentId=&engine=` | body thô = mẫu giọng 3–60s; consent dùng **một lần**, đúng loại `voice`; lỗi mẫu không làm cháy consent |
| `DELETE /voices/{id}` | xoá giọng nhân bản |
| `POST /projects/{id}/tts/synthesize` · `/tts/preview` | job `tts.synthesize` / `tts.preview`; 424 `MODEL_MISSING` kèm `modelId` |
| `POST /projects/{id}/dubbing/plan` | gộp cue bản dịch thành câu + tính khung thời gian (đồng bộ) |
| `POST /projects/{id}/dubbing/synthesize` | job: TTS từng câu → khớp khung (tăng tốc ≤ trần, quá dài → LLM rút gọn, tối đa 3 lượt) |
| `POST /projects/{id}/dubbing/mix` | job: Demucs tách nền (cache) → đặt giọng theo mốc → ducking + loudnorm → mux video → SRT khớp giọng |

State machine `tts`: `set-script`, `set-voices`, `set-options`. `dubbing`: `set-options`, `set-item` (chỉ câu đó bị tổng hợp lại). Lệnh bắt đầu bằng `_` (kết quả/kế hoạch do job ghi) bị API công khai từ chối.
Worker tiến trình con mới: `tts_worker` (vieneu | kokoro), `separate_worker` (demucs). Giao thức: dòng JSON trên stdout.

## 8d. API bổ sung (GĐ6)
| Route | Mô tả |
|---|---|
| `POST /projects/{id}/highlights/analyze` | job: phân cảnh (ffmpeg `select=scene` ngưỡng 0.3) → dựng đoạn ứng viên theo biên câu → điểm heuristic + LLM (tối đa 20 đoạn, 3 đoạn/lần gọi) → chọn N đoạn không chồng, cách nhau ≥ 3s |
| `POST /projects/{id}/highlights/export` `{ids?}` | job: cắt + 9:16 (crop/pad) hoặc 16:9 + phụ đề burn-in + tiêu đề giật tít 3.5s đầu → `exports/clips/` |
| `POST /projects/{id}/highlights/summary` | job: LLM viết 1–2 câu dẫn cho mỗi clip → TTS → ghép clip (tiếng gốc ×0.18) + lời dẫn; lời dẫn dài hơn clip thì giữ khung hình cuối |
| `POST /projects/{id}/podcast/script` | job: dàn ý (chương) rồi từng chương lượt nói bằng LLM ép JSON schema |
| `POST /projects/{id}/podcast/produce` | job: TTS nhiều người → ghép → nhạc mở/kết/nền (ducking) → loudnorm → MP3/WAV có chương → video sóng âm + phụ đề → show notes |
| `GET/PUT/DELETE /music` | thư viện nhạc người dùng; **bắt buộc ghi giấy phép/nguồn** (400 `LICENSE_REQUIRED`); luôn có mục `builtin` (nhạc tự sinh, CC0) |

State machine `highlights`: `set-options`, `set-clip` (đổi khung cắt/tiêu đề thì xoá file đã xuất của clip đó), `add-clip`, `remove-clip`. `podcast`: `set-brief`, `set-script` (chuẩn hoá tên người nói theo danh sách người dẫn), `set-music`, `set-options`. Lệnh `_*` do job ghi.
`LLMClient.json_object(system, user, schema)` mới: gọi Ollama (`format` = JSON schema, `think:false`) hoặc `response_format` ở provider openai.

## 8e. Agent, Skills, lịch, MCP (GĐ7)
**Nguyên tắc: một nguồn sự thật.** Tool của Agent gọi đúng các hàm service mà trang web gọi (`start_transcribe`, `build_plan`, `repo.apply_command(..., author="agent")`…); kết quả nằm trong cùng state machine/revision, UI thấy qua `state.changed`/`job.*`. Hội thoại chỉ lưu *ai đã nói/gọi gì* (bảng `thread`, `message`, `approval`).

**Vòng lặp** (`agent/loop.py`, job `agent.run` chạy ở pool riêng 4 luồng để không chiếm worker của job thật): mỗi bước gọi LLM hai lần, đều **ép JSON schema** (Ollama `format`): (1) chọn một tool trong *enum* các tool (hoặc `final`), (2) điền tham số theo đúng schema của tool đó. Pydantic kiểm tra lại; lỗi thành observation để LLM tự sửa. Chặn: tối đa 14 bước, 3 lỗi liên tiếp, lặp y hệt 2 lần, bước đã bị từ chối không được nài lại. Câu trả lời cuối: phần dữ kiện (việc đã làm, tệp thật, bước bị từ chối/lỗi) do **code** dựng từ các bước, LLM chỉ viết 1–2 câu nhận xét (chép lại yêu cầu thì bị bỏ).

**An toàn**: kết quả tool/transcript/file là *dữ liệu* (system prompt nói rõ). Tool xuất media nặng (`render`), tải mô hình (`download`) và mọi tool MCP (`external`) **phải qua phê duyệt** (bảng `approval`, mọi quyết định có dấu vết). "Tự duyệt" chỉ áp cho `render`; `download` và `external` không bao giờ tự duyệt. Skill chỉ là văn bản dẫn đường, không chạy mã → một Skill độc hại không vượt được cổng duyệt.

| Route | Mô tả |
|---|---|
| `GET /agent/tools` | danh mục tool + schema + loại phê duyệt |
| `POST/GET /projects/{id}/threads` · `GET/PATCH /threads/{id}` | hội thoại; `GET` trả `messages`, `pendingApprovals`, `run` |
| `POST /threads/{id}/messages` `{text, skill?, autoApprove?}` | tạo job `agent.run` (409 nếu đang chạy; 424 nếu LLM tắt) · `POST /threads/{id}/cancel` |
| `GET /approvals?threadId=&status=` · `POST /approvals/{id}` `{decision}` | duyệt/từ chối (409 nếu đã quyết định) |
| `GET/POST /skills` · `GET /skills/{name}` `/export` · `PUT /skills/{name}/enabled` · `DELETE` · `GET /skills/template` | `skills/<tên>/SKILL.md` (có sẵn, chỉ đọc) + `.runtime/skills/` (của bạn); frontmatter `name, description, tools`, bước đánh số có tên tool → checklist |
| `GET/POST/PATCH/DELETE /schedules` · `POST /schedules/{id}/run-now` | cron 5 trường, tối thiểu 5 phút/lần; chạy bù 1 lần nếu trễ < 1 giờ |
| `GET /mcp/servers` | server MCP khai báo trong `config.toml` (`[[mcp.servers]]`), mặc định rỗng |

Sự kiện SSE mới: `agent.user|assistant|question|skill|tool_call|tool_result|approval|error`, `approval.requested|resolved`.

## 8f. Chiến dịch nội dung (GĐ8)
**Phân vai rõ giữa code và LLM** — phần sai là tốn tiền/uy tín nên làm bằng code: lịch đăng (`campaign/catalog.py::build_schedule`: số bài/tuần và giờ đăng mặc định theo nền tảng, rải lệch ngày để không dồn, múi giờ `zoneinfo` của từng thị trường, xen kẽ định dạng), giá quy đổi (`local_price`: **chỉ** dùng tỷ giá người dùng nhập; thiếu tỷ giá → không nhắc giá và cảnh báo), giới hạn caption/hashtag theo nền tảng (`state.py` từ chối, `service.py` cắt gọn), đơn vị/xưng hô/ngày tháng theo thị trường (`MARKETS[...]` đưa vào prompt). **LLM chỉ** đề xuất ý tưởng và viết caption/kịch bản/chữ thumbnail cho từng bài; kết quả được kiểm tra ngôn ngữ (`lang_ok`), lọc ký tự lạ (`strip_foreign_script`), thử lại 1 lần.

State machine `campaign`: `set-brief`, `set-post` (sửa caption/hashtag/giờ…; duyệt `planned→approved→posted`; sửa nội dung bài đã duyệt thì quay về `ready` để duyệt lại), nội bộ `_set-plan`, `_merge-posts`, `_set-export`. Mỗi lệnh = một revision.

| Route | Mô tả |
|---|---|
| `GET /campaign/catalog` | thị trường (ngôn ngữ, tiền tệ, múi giờ) và nền tảng |
| `POST /projects/{id}/campaign/plan` | job `campaign.plan`: ý tưởng (LLM, theo lô) + lịch tất định → `plan`, `posts[]`, cảnh báo |
| `POST /projects/{id}/campaign/assets` `{postIds?, force, renderVideos, autoTranslate}` | job `campaign.assets`: (nếu project có nguồn + transcript) dịch phụ đề các ngôn ngữ còn thiếu bằng job con, xuất SRT từng ngôn ngữ, tuỳ chọn dựng video có phụ đề từng ngôn ngữ; rồi từng bài: caption/hashtag/kịch bản + thumbnail (khung hình thật của video, hoặc nền màu nếu chỉ có audio) bằng ffmpeg + ASS. Bài lỗi → `failed` kèm ghi chú, chạy lại được |
| `POST /projects/{id}/campaign/export` | thư mục `exports/campaign/<slug>/<thị trường>/<nền tảng>/<ngày>_<id>/` (caption.txt, script.md, thumbnail.png, subtitles.srt), `schedule.csv` (UTF-8 BOM; giờ địa phương + múi giờ + UTC), `campaign.json`, `README.md`, và `.zip`. Chỉ bài đã có tài sản |

Agent: `campaign_setup|plan|assets|export` (+ `get_state` tool `campaign`); skill `multi-market-campaign` đã viết lại theo các tool này.

## 8g. Đóng gói, Docker, CI (GĐ8)
- **Desktop đóng gói** (`apps/desktop`): `electron-builder.yml`. Tài nguyên chỉ đọc trong `resources/` (`daemon/` mã Python + `pyproject.toml` + `uv.lock`, `web/`, `skills/`, `models/registry.yaml`, `config.toml`, `uv/` — bản uv theo từng nền tảng do `scripts/fetch-uv.mjs` tải và **kiểm SHA-256** do chính astral-sh công bố). **Python và thư viện không nằm trong bộ cài** (gói sẽ >3 GB và phụ thuộc nền tảng): lần mở đầu `main.cjs` chạy `uv sync --frozen --no-dev` với `UV_PROJECT_ENVIRONMENT`/`UV_CACHE_DIR`/`UV_PYTHON_INSTALL_DIR` trỏ vào `userData/env`, ghi dấu vân tay (`pyproject.toml`+`uv.lock`) để cập nhật app thì đồng bộ lại. Dữ liệu người dùng ở `userData/data` (`OPENSTUDIO_DATA_DIR`). Đường dẫn dev/đóng gói tách trong `src/paths.cjs` (có test). Cửa sổ khởi động hiển thị tiến trình và lỗi.
- **torch**: `[tool.uv.sources]` gắn chỉ mục CPU của PyTorch cho Linux (bản mặc định kèm CUDA ~2,5 GB); Windows/macOS dùng wheel PyPI gọn.
- **Web/Docker**: `OPENSTUDIO_WEB_DIST` → daemon phục vụ luôn bản build web (cùng origin, không cần CORS). `OPENSTUDIO_ALLOW_REMOTE_BIND=1` là **ngoại lệ duy nhất** của quy tắc loopback, chỉ chấp nhận `host=0.0.0.0`, bắt buộc kèm `OPENSTUDIO_TOKEN` do người dùng đặt, và không in token ra log; `docker-compose.yml` chỉ publish `127.0.0.1:8787`.
- **Chẩn đoán**: `openstudio/doctor.py` (`GET /system/doctor`, `python -m openstudio.doctor`, Cài đặt → Chẩn đoán): FFmpeg + bộ lọc libass/amix/sidechain, ffprobe, thư mục dữ liệu ghi được, dung lượng trống, Ollama + mô hình.
- **CI** (`.github/workflows`): `ci.yml` (lint ESLint+ruff, typecheck, `check_licenses`, pytest+vitest+desktop trên Ubuntu & Windows, build web, build Docker); `release.yml` (matrix Windows/macOS arm64/macOS x64/Linux, smoke test gói đã giải nén trên Windows & Linux, tải artifact, tạo **draft** release khi gắn tag `v*`). Các workflow chưa từng chạy trên GitHub (nhóm phát triển chưa có remote).

## 8h. Avatar, Chỉnh sửa video, Thumbnail, Template (GĐ4+5, phần CPU)
- **`assets.py`**: kho tài nguyên project (`assets/` + `index.json`), `probe_any` phân loại video/ảnh/audio. Endpoint `PUT/GET /projects/{id}/assets`, `POST …/assets/register`, `DELETE …/assets/{aid}`.
- **`editor/`**: state `editor` (`settings`, `segments`, `texts`, `overlays`, `music`); lệnh công khai `set-settings`, `update-segment`, `move-segment`, `split-segment`, `remove-segment`, `add/update/remove-text|overlay`, `set-music`, `apply-template`; việc gắn tài nguyên đi qua `POST …/editor/attach` (service tra thông tin media rồi ghi lệnh nội bộ `_add-segment|_add-overlay|_set-music`). `editor/render.py::build` là hàm thuần dựng `filter_complex` (trim/setpts/atempo, scale+pad|crop, `xfade`/`acrossfade` hoặc `concat` nối lần lượt, `overlay`, ASS cho chữ, `sidechaincompress` cho nhạc). Job `editor.render` (`preview` 360p ultrafast hoặc bản cuối).
- **`thumbnail/`**: tiêu đề/phụ đề bằng ASS (BorderStyle 3 = hộp màu), nền gradient/ảnh/khung hình video, logo; mỗi biến thể xoay vòng bố cục × bảng màu và lệch vùng cắt.
- **`templates.py`**: `templates/<id>/template.json` (có sẵn, chỉ đọc) + `<data>/templates/` (người dùng); `kind` = `thumbnail|editor`; chỉ là cấu hình JSON.
- **`avatar/`**: `library.py` (avatar + consent `face`, dùng một lần, kiểm lại lúc xuất), `engine.py` (đường bao biên độ → 12 mức mở miệng dựng sẵn → ghép nền, ghi khung thô vào ffmpeg qua stdin), `service.py` (job `avatar.render`, kiểm tra phụ đề/audio lệch). `GET /avatar/engines` trả trạng thái thật: chỉ `puppet` được cài; `musetalk`, `latentsync` hiện là "chưa tích hợp / cần GPU".

## 8i. Tạo ảnh AI và Tạo video từ ảnh (GĐ5B)
- **`image/`**: `engine.py` chọn bản `sd-cli` theo hệ điều hành (`sd-cpp-<os>-<arch>` trong registry, `models/engines/<id>/sd.zip` do Model Manager tải rồi giải nén một lần, chống zip-slip), dựng lệnh (`--steps 4 --cfg-scale 1.0`, `--vae-tiling` khi ≥ 1024 px, `-r` cho ảnh tham chiếu), đọc tiến độ bước từ stdout/stderr (`run_process(..., on_err_line=…)`). `service.py`: job `image.generate` (dịch prompt bằng LLM → nhả Ollama → từng biến thể một tiến trình `sd-cli` → đăng ký vào kho tài nguyên → sidecar nhãn AI). `GET /image/status`, `POST /projects/{id}/image/generate`.
- **`video/`**: `zoompan_filter` (hàm thuần) + job `video.motion`; `GET /video/engines` liệt kê rõ engine `motion` (generative=false) và `wan2.2-ti2v-5b` (khoá, chưa tích hợp).

## 9. Quyết định đã chốt / chờ duyệt
Đã chốt (2026-10-13):
1. Daemon: Python/FastAPI.
2. Ảnh trên GPU 8GB: thử bản lượng tử hoá FLUX.2 klein 4B ở GĐ5; nếu không đạt thì chuyển tạo ảnh sang hạng 12GB.
3. Mô hình phi thương mại (F5-TTS, MusicGen, NLLB…): cho phép người dùng tự bật, kèm cảnh báo "không dùng thương mại". Dự án dùng phi thương mại.
4. Piper (tiến trình ngoài) và Edge TTS: giữ làm tuỳ chọn, tắt mặc định.
