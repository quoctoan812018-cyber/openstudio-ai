"""Phát hiện phần cứng và phân hạng: cpu < gpu8 < gpu12 < gpu16plus."""
from __future__ import annotations

import platform
import shutil
import subprocess

import psutil

TIERS = ["cpu", "gpu8", "gpu12", "gpu16plus"]
TIER_LABELS = {"cpu": "CPU", "gpu8": "GPU 6–8GB", "gpu12": "GPU 12GB", "gpu16plus": "GPU 16GB+"}


def tier_for_vram(vram_gb: float | None) -> str:
    if vram_gb is None:
        return "cpu"
    if vram_gb >= 16:
        return "gpu16plus"
    if vram_gb >= 11.5:
        return "gpu12"
    if vram_gb >= 5.5:
        return "gpu8"
    return "cpu"


def tier_allows(machine_tier: str, required: str) -> bool:
    return TIERS.index(machine_tier) >= TIERS.index(required)


def _nvidia() -> list[dict]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return []
    gpus = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[1].replace(".", "").isdigit():
            gpus.append({"name": parts[0], "vram_gb": round(float(parts[1]) / 1024, 1),
                         "driver": parts[2] if len(parts) > 2 else None, "vendor": "nvidia"})
    return gpus


def detect() -> dict:
    gpus = _nvidia()
    best = max((g["vram_gb"] for g in gpus), default=None)
    tier = tier_for_vram(best)
    mem = psutil.virtual_memory()
    return {
        "os": f"{platform.system()} {platform.release()}",
        "cpu": {"name": platform.processor() or platform.machine(), "cores": psutil.cpu_count(logical=False) or 1,
                "threads": psutil.cpu_count(logical=True) or 1},
        "ram_gb": round(mem.total / 1024**3, 1),
        "gpus": gpus,
        "cuda_available": bool(gpus),
        "tier": tier,
        "tier_label": TIER_LABELS[tier],
        "note": None if gpus else "Không phát hiện GPU NVIDIA — chạy ở hạng CPU.",
    }
