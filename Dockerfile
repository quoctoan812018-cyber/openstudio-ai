# OpenStudio AI — chế độ web/Docker (CPU). Mở http://127.0.0.1:8787 và nhập token bạn đặt.
# Lưu ý: daemon bên trong container nghe 0.0.0.0 (bắt buộc để cổng publish hoạt động), nên docker-compose.yml CHỈ publish vào 127.0.0.1.
FROM node:24-slim AS web
WORKDIR /src
RUN npm install -g pnpm@12.11.2
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
COPY packages/protocol/package.json packages/protocol/
RUN pnpm install --frozen-lockfile --filter @openstudio/web...
COPY apps/web apps/web
COPY packages packages
RUN pnpm --filter @openstudio/web build

FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 espeak-ng ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
WORKDIR /app
COPY apps/daemon/pyproject.toml apps/daemon/uv.lock apps/daemon/
RUN UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --project apps/daemon --frozen --no-dev
COPY apps/daemon apps/daemon
COPY models models
COPY skills skills
COPY templates templates
COPY config.toml .
COPY --from=web /src/apps/web/dist /app/web
ENV PATH="/opt/venv/bin:$PATH" PYTHONPATH=/app/apps/daemon PYTHONUNBUFFERED=1 \
    OPENSTUDIO_ROOT=/app OPENSTUDIO_DATA_DIR=/data OPENSTUDIO_WEB_DIST=/app/web \
    OPENSTUDIO_HOST=0.0.0.0 OPENSTUDIO_PORT=8787 OPENSTUDIO_ALLOW_REMOTE_BIND=1 \
    OPENSTUDIO_LLM_BASE_URL=http://host.docker.internal:11434/v1
VOLUME /data
EXPOSE 8787
RUN useradd -m studio && mkdir -p /data && chown studio /data
USER studio
CMD ["python", "-m", "openstudio"]
