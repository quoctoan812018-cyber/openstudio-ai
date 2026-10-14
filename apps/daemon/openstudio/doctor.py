"""Chẩn đoán môi trường: những thứ OpenStudio cần mà trình cài đặt KHÔNG đóng gói (FFmpeg, Ollama) và tài nguyên máy.
Dùng cho Cài đặt → Chẩn đoán, `python -m openstudio.doctor` và scripts/doctor.mjs."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from .config import Settings

INSTALL_HINT = {
    "win32": "winget install Gyan.FFmpeg   (hoặc choco install ffmpeg)",
    "darwin": "brew install ffmpeg",
    "linux": "sudo apt install ffmpeg   (hoặc dnf/pacman tương đương)",
}


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20).stdout


def check_ffmpeg() -> dict:
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"id": "ffmpeg", "ok": False, "required": True, "detail": "Không tìm thấy ffmpeg trong PATH",
                "fix": INSTALL_HINT.get(sys.platform if sys.platform in INSTALL_HINT else "linux")}
    try:
        ver = _run([exe, "-version"]).splitlines()[0]
        filters = _run([exe, "-hide_banner", "-filters"])
    except (OSError, subprocess.SubprocessError, IndexError) as e:
        return {"id": "ffmpeg", "ok": False, "required": True, "detail": f"ffmpeg chạy lỗi: {e}", "fix": None}
    missing = [f for f in ("subtitles", "ass", "amix", "sidechaincompress") if f" {f} " not in filters]
    if missing:
        return {"id": "ffmpeg", "ok": False, "required": True, "detail": f"{ver} — thiếu bộ lọc: {', '.join(missing)} (cần bản build có libass)",
                "fix": INSTALL_HINT.get(sys.platform if sys.platform in INSTALL_HINT else "linux")}
    return {"id": "ffmpeg", "ok": True, "required": True, "detail": ver, "fix": None}


def check_ffprobe() -> dict:
    ok = shutil.which("ffprobe") is not None
    return {"id": "ffprobe", "ok": ok, "required": True, "detail": "có" if ok else "Không tìm thấy ffprobe (đi kèm FFmpeg)", "fix": None if ok else "Cài FFmpeg đầy đủ"}


def check_llm(llm) -> dict:
    s = llm.status()
    if not s["available"]:
        return {"id": "llm", "ok": False, "required": False, "detail": "Không kết nối được Ollama — dịch, kịch bản, Agent sẽ không dùng được",
                "fix": "Cài Ollama (ollama.com) rồi chạy: ollama serve"}
    if not s["model_installed"]:
        return {"id": "llm", "ok": False, "required": False, "detail": f"Ollama chạy nhưng chưa có mô hình {s['model']}", "fix": f"ollama pull {s['model']}"}
    return {"id": "llm", "ok": True, "required": False, "detail": f"Ollama + {s['model']}", "fix": None}


def check_disk(data_dir: Path) -> dict:
    probe = data_dir if data_dir.exists() else next((p for p in data_dir.parents if p.exists()), Path("."))
    free = shutil.disk_usage(probe).free / 1e9
    return {"id": "disk", "ok": free >= 5, "required": False, "detail": f"Trống {free:.1f} GB tại {probe}",
            "fix": None if free >= 5 else "Mô hình và video cần nhiều dung lượng; nên có ≥ 5 GB trống"}


def check_data_dir(data_dir: Path) -> dict:
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        t = data_dir / ".write-test"
        t.write_text("x")
        t.unlink()
        return {"id": "data_dir", "ok": True, "required": True, "detail": str(data_dir), "fix": None}
    except OSError as e:
        return {"id": "data_dir", "ok": False, "required": True, "detail": f"Không ghi được {data_dir}: {e}", "fix": "Đặt OPENSTUDIO_DATA_DIR sang thư mục ghi được"}


def run_checks(settings: Settings, llm) -> dict:
    checks = [check_ffmpeg(), check_ffprobe(), check_data_dir(settings.data_dir), check_disk(settings.data_dir), check_llm(llm)]
    return {"ok": all(c["ok"] for c in checks if c["required"]), "checks": checks}


def main() -> int:
    from .config import load_settings
    from .subtitles.llm import LLMClient
    s = load_settings()
    res = run_checks(s, LLMClient(s.llm_base_url, s.llm_model, provider=s.llm_provider, num_ctx=s.llm_num_ctx))
    if "--json" in sys.argv:
        print(json.dumps(res, ensure_ascii=False))
    else:
        for c in res["checks"]:
            print(f"[{'OK' if c['ok'] else ('LỖI' if c['required'] else 'CẢNH BÁO')}] {c['id']}: {c['detail']}" + (f"\n      → {c['fix']}" if c["fix"] else ""))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
