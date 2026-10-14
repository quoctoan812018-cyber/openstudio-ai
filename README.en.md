# OpenStudio AI

[🇻🇳 Tiếng Việt](README.md) · 🇬🇧 English

A **local-first** AI content studio — free, open source ([Apache-2.0](LICENSE)). No API keys; your data, files and logs stay on your machine. Cloud providers (if ever added) are off by default and labelled "may cost money".

## What's in this release

| Tool | What it does | Hardware tier |
|---|---|---|
| **Subtitles & Translation** | Speech-to-text (faster-whisper), visual cue editor, multi-language translation with a local LLM and glossary, SRT/VTT/ASS export, burn-in for 16:9 / 9:16 video | CPU |
| **Text-to-speech** | VieNeu (Vietnamese), Kokoro (English/Japanese/Chinese…), voice cloning with **recorded consent** | CPU |
| **Dubbing** | Translate → speak → fit each line to its time slot → separate background music (Demucs) → remix → mux into the video | CPU |
| **Summaries & Highlights** | LLM + scene-based highlight picking, 9:16 clips with subtitles/headline, narrated summary video | CPU |
| **Podcast** | Topic/document → 2–3 host script → voices + intro/outro music, ducked music bed → chaptered MP3, waveform video, show notes | CPU |
| **Content campaign** | Goal + markets + platforms → 7/14/30-day plan, posting schedule per market time zone, localized captions/hashtags/scripts/thumbnails, per-language subtitles → tracking table → export package + `schedule.csv` | CPU |
| **AI assistant + Skills** | Natural-language control of the tools above; skills are `SKILL.md` files; cron schedules | CPU |
| **Video editor** | Cut/join, speed, transitions, text, overlays, music that ducks under speech, quick preview, 16:9 · 9:16 · 1:1 (FFmpeg) | CPU |
| **Thumbnails & Templates** | Image/video frame + accented title, several variants; reusable templates | CPU |
| **AI avatar (voice-driven animation)** | Portrait speaks along with a voice, with background/frame/subtitles; real-person photos need consent. *Not AI lip-sync* | CPU |
| AI lip-sync, AI image/video generation | **Not built yet** (need a GPU; tools are locked on machines without enough VRAM) | GPU |

Honest status, risks and known limits: [docs/PROGRESS.md](docs/PROGRESS.md) · release verification: [docs/RELEASE_CHECK.md](docs/RELEASE_CHECK.md) · architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (Vietnamese).

## Quick install

Full guide by hardware tier: **[docs/INSTALL.md](docs/INSTALL.md)** (Vietnamese, with an English summary).

- **Windows**: run `OpenStudio-AI-<version>-win-x64.exe` (not code-signed, so SmartScreen may warn). On first launch the app creates its Python environment with the bundled `uv` (internet needed, a few minutes).
- **macOS / Linux**: `.dmg` / `.AppImage` are built by CI (see [known limits](docs/RELEASE_CHECK.md)); or run from source.
- **Docker (web)**: `OPENSTUDIO_TOKEN=<your-secret> docker compose up --build`, then open http://127.0.0.1:8787.
- **From source**:
```bash
pnpm install
pnpm dev            # daemon :8787 + web :5173 (random token per run)
pnpm doctor         # check FFmpeg, Ollama, disk space
```

You also need **FFmpeg** (with libass) and, for translation/scripts/assistant, **[Ollama](https://ollama.com)** with a model (default `qwen3:4b`). The installer does **not** bundle FFmpeg, Ollama or model weights; models are downloaded on demand with checksum verification and size shown.

## Development

```bash
pnpm test           # pytest + vitest + desktop tests
pnpm lint           # ESLint + ruff
pnpm typecheck
pnpm check:licenses # validate models/registry.yaml against the license rules
pnpm protocol:gen   # regenerate TS types from Pydantic
pnpm dist:win       # build the Windows installer (Windows only)
```
See [CONTRIBUTING.md](CONTRIBUTING.md). Config: [config.toml](config.toml) + `OPENSTUDIO_*` env vars (`DATA_DIR`, `PORT`, `REGISTRY`, `LLM_MODEL`, …).

## Safety & ethics
- The daemon **listens on 127.0.0.1 only** and requires a Bearer token (single exception: the Docker container, whose port is published to the host's loopback only).
- Voice cloning / avatars from real people require the confirmation *"I have the rights and consent of this person"*, stored locally. There are no celebrity voice presets.
- Optional "AI-generated" metadata label. Logs redact tokens and keys.
- AI-written content (especially multi-market campaigns) **must be reviewed by a native speaker** before posting.

## Models & licenses
[docs/MODEL_LICENSES.md](docs/MODEL_LICENSES.md) and [models/registry.yaml](models/registry.yaml). Non-commercial models carry `non_commercial: true` and need your explicit confirmation before download. No weights are bundled.

## Credits
Architecture inspired by [OpenCreator](https://github.com/krillinai/OpenCreator) (Apache-2.0). Open models/libraries are listed in [docs/MODEL_LICENSES.md](docs/MODEL_LICENSES.md).
