"""Cấu hình: config.toml + biến môi trường OPENSTUDIO_*. Không hard-code đường dẫn."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(ValueError):
    pass


def find_root(start: Path | None = None) -> Path:
    env = os.environ.get("OPENSTUDIO_ROOT")
    if env:
        return Path(env).resolve()
    here = (start or Path(__file__)).resolve()
    for p in [here, *here.parents]:
        if (p / "config.toml").is_file():
            return p
    raise ConfigError("Không tìm thấy config.toml (đặt OPENSTUDIO_ROOT)")


@dataclass
class Settings:
    root: Path
    data_dir: Path
    registry_path: Path
    host: str = "127.0.0.1"
    port: int = 0
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_model: str = "qwen3:4b"
    llm_provider: str = "ollama"
    llm_num_ctx: int = 8192
    cloud_enabled: bool = False
    web_dist: Path | None = None  # nếu đặt: daemon phục vụ luôn bản build web (chế độ Docker/web)
    remote_bind: bool = False     # CHỈ cho container: nghe 0.0.0.0 bên trong, máy chủ phải publish cổng vào 127.0.0.1
    dev_fake_tts: bool = False  # chỉ cho kiểm thử
    builtin_skills_dir: Path | None = None  # mặc định <root>/skills
    builtin_templates_dir: Path | None = None  # mặc định <root>/templates
    mcp_servers: list[dict] = field(default_factory=list)  # [[mcp.servers]] trong config.toml; mặc định rỗng
    web_origins: list[str] = field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )

    @property
    def skills_dir(self) -> Path:
        return self.builtin_skills_dir or self.root / "skills"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "openstudio.db"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def voices_dir(self) -> Path:
        return self.data_dir / "voices"

    @property
    def avatars_dir(self) -> Path:
        return self.data_dir / "avatars"

    @property
    def settings_file(self) -> Path:
        return self.data_dir / "settings.json"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.models_dir, self.projects_dir, self.data_dir / "logs", self.data_dir / "consent"):
            d.mkdir(parents=True, exist_ok=True)


def load_settings(root: Path | None = None, env: dict[str, str] | None = None) -> Settings:
    env = dict(os.environ if env is None else env)
    root = Path(env["OPENSTUDIO_ROOT"]).resolve() if env.get("OPENSTUDIO_ROOT") else (root or find_root())
    cfg: dict = {}
    cfg_file = root / "config.toml"
    if cfg_file.is_file():
        cfg = tomllib.loads(cfg_file.read_text(encoding="utf-8"))
    paths, server, llm = cfg.get("paths", {}), cfg.get("server", {}), cfg.get("llm", {})

    def resolve(p: str) -> Path:
        q = Path(p)
        return q if q.is_absolute() else (root / q).resolve()

    host = env.get("OPENSTUDIO_HOST", server.get("host", "127.0.0.1"))
    remote_bind = env.get("OPENSTUDIO_ALLOW_REMOTE_BIND") == "1"
    if host not in ("127.0.0.1", "localhost", "::1") and not (remote_bind and host == "0.0.0.0"):
        raise ConfigError("daemon chỉ được nghe loopback (127.0.0.1); riêng container có thể đặt OPENSTUDIO_ALLOW_REMOTE_BIND=1 với host 0.0.0.0")
    if remote_bind and not env.get("OPENSTUDIO_TOKEN"):
        raise ConfigError("OPENSTUDIO_ALLOW_REMOTE_BIND=1 bắt buộc kèm OPENSTUDIO_TOKEN do bạn đặt (không dùng token ngẫu nhiên in ra log)")
    return Settings(
        root=root,
        data_dir=resolve(env.get("OPENSTUDIO_DATA_DIR", paths.get("data_dir", ".runtime"))),
        registry_path=resolve(env.get("OPENSTUDIO_REGISTRY", paths.get("registry", "models/registry.yaml"))),
        host="127.0.0.1" if host == "localhost" else host,
        port=int(env.get("OPENSTUDIO_PORT", server.get("port", 0))),
        llm_base_url=env.get("OPENSTUDIO_LLM_BASE_URL", llm.get("base_url", "http://127.0.0.1:11434/v1")),
        llm_model=env.get("OPENSTUDIO_LLM_MODEL", llm.get("model", "qwen3:4b")),
        llm_provider=env.get("OPENSTUDIO_LLM_PROVIDER", llm.get("provider", "ollama")),
        llm_num_ctx=int(env.get("OPENSTUDIO_LLM_NUM_CTX", llm.get("num_ctx", 8192))),
        cloud_enabled=bool(llm.get("cloud_enabled", False)),
        web_dist=resolve(env["OPENSTUDIO_WEB_DIST"]) if env.get("OPENSTUDIO_WEB_DIST") else None,
        remote_bind=remote_bind and host == "0.0.0.0",
        dev_fake_tts=env.get("OPENSTUDIO_DEV_FAKE_TTS") == "1",
        mcp_servers=[x for x in cfg.get("mcp", {}).get("servers", []) if isinstance(x, dict)],
        web_origins=[*Settings.__dataclass_fields__["web_origins"].default_factory(),
                     *[o.strip() for o in env.get("OPENSTUDIO_WEB_ORIGINS", "").split(",") if o.strip()]],
    )
