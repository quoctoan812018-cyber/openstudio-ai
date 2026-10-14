"""Engine tạo ảnh: stable-diffusion.cpp (`sd-cli`, MIT) chạy FLUX.2 klein 4B lượng tử hoá (GGUF) trên CPU.
Tệp nhị phân và trọng số do Model Manager tải (có SHA-256, hiển thị dung lượng) — không đóng gói sẵn."""
from __future__ import annotations

import platform
import re
import sys
import zipfile
from pathlib import Path

from ..errors import ApiError
from ..security import safe_join

MODEL_ID = "flux2-klein-4b"
MODEL_FILES = {"diffusion": "flux-2-klein-4b-Q4_0.gguf", "vae": "flux2-vae.safetensors", "llm": "Qwen3-4B-Q4_K_M.gguf"}
STEP_RE = re.compile(r"(\d+)\s*/\s*(\d+)\s*-\s*[\d.]+\s*(?:s/it|it/s)")


def engine_id() -> str | None:
    """Id mục registry của bản sd-cli hợp với máy này (None nếu chưa hỗ trợ)."""
    m = platform.machine().lower()
    if sys.platform == "win32" and m in ("amd64", "x86_64"):
        return "sd-cpp-win-x64"
    if sys.platform == "linux" and m in ("x86_64", "amd64"):
        return "sd-cpp-linux-x64"
    if sys.platform == "darwin" and m in ("arm64", "aarch64"):
        return "sd-cpp-macos-arm64"
    return None


def cli_path(models_dir: Path, eid: str) -> Path:
    """Giải nén zip đã tải (một lần) và trả đường dẫn sd-cli. Chống zip-slip: mọi mục phải nằm trong thư mục đích."""
    base = models_dir / "engines" / eid
    zp = base / "sd.zip"
    out = base / "bin"
    exe = out / ("sd-cli.exe" if sys.platform == "win32" else "sd-cli")
    if exe.is_file():
        return exe
    if not zp.is_file():
        raise ApiError(424, "MODEL_MISSING", f"Cần tải '{eid}' trước (Cài đặt → Mô hình)", {"modelId": eid})
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zp) as z:
        for info in z.infolist():
            safe_join(out, info.filename)            # ném lỗi nếu thoát khỏi thư mục đích
        z.extractall(out)
    found = next((p for p in out.rglob(exe.name)), None)
    if not found:
        raise ApiError(422, "ENGINE_INVALID", "Gói sd-cli không chứa tệp chạy được")
    if found != exe:
        for p in found.parent.iterdir():            # đưa về phẳng để DLL nằm cạnh tệp chạy
            p.replace(out / p.name)
    if sys.platform != "win32":
        exe.chmod(0o755)
    return exe


def model_paths(models_dir: Path) -> dict[str, Path]:
    d = models_dir / "image" / MODEL_ID
    paths = {k: d / v for k, v in MODEL_FILES.items()}
    if not all(p.is_file() for p in paths.values()):
        raise ApiError(424, "MODEL_MISSING", f"Cần tải mô hình '{MODEL_ID}' trước (Cài đặt → Mô hình, ~5 GB)", {"modelId": MODEL_ID})
    return paths


def build_cmd(cli: Path, paths: dict[str, Path], prompt: str, w: int, h: int, seed: int, out: Path, ref: Path | None = None, threads: int = -1) -> list[str]:
    cmd = [str(cli), "--diffusion-model", str(paths["diffusion"]), "--vae", str(paths["vae"]), "--llm", str(paths["llm"]), "-p", prompt,
           "--cfg-scale", "1.0", "--steps", "4", "-W", str(w), "-H", str(h), "-s", str(seed), "-t", str(threads), "-o", str(out)]
    if max(w, h) >= 1024:
        cmd.append("--vae-tiling")                   # giảm RAM khi giải mã ảnh lớn
    if ref is not None:
        cmd += ["-r", str(ref)]
    return cmd


def parse_step(line: str) -> tuple[int, int] | None:
    m = STEP_RE.search(line)
    return (int(m.group(1)), int(m.group(2))) if m else None
