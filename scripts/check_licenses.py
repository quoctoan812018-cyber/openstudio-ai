"""Kiểm tra models/registry.yaml theo quy tắc license của dự án (chạy trong CI và trước khi phát hành).

  uv run --project apps/daemon python scripts/check_licenses.py

Quy tắc:
  1. Mọi mô hình có `id` phải khai báo `weights_license`.
  2. License trọng số chứa dấu hiệu phi thương mại (NC / Non-Commercial / Research-only) thì BẮT BUỘC `non_commercial: true`.
  3. `non_commercial: true` thì `commercial_ok` không được là true.
  4. Mô hình tải được (`download.files`) phải có url https; file > 5 MB phải có sha256 (64 hex), file nhỏ phải có `bytes`.
  5. Mô hình phi thương mại phải được nêu tên trong docs/MODEL_LICENSES.md (cảnh báo hiển thị cho người dùng).
  6. Không có mô hình phi thương mại nào là mặc định (`default`) của một năng lực.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
NC = re.compile(r"(?:\bNC\b|-NC\b|non[- ]?commercial|research[- ]only|noncommercial)", re.I)
SMALL_FILE = 5_000_000   # file cấu hình/tokenizer nhỏ chỉ cần kiểm kích thước; trọng số phải có sha256
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def walk(node, path=()):
    if isinstance(node, dict):
        if "id" in node and isinstance(node["id"], str):
            yield path, node
        for k, v in node.items():
            yield from walk(v, (*path, str(k)))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, (*path, str(i)))


def check(registry: dict, docs: str) -> list[str]:
    errors: list[str] = []
    models = list(walk(registry.get("capabilities", {})))
    if not models:
        errors.append("registry.yaml không có mô hình nào")
    for path, m in models:
        where = f"{'.'.join(path)} ({m['id']})"
        lic = str(m.get("weights_license", ""))
        if not lic:
            errors.append(f"{where}: thiếu weights_license")
        nc = bool(m.get("non_commercial", False))
        if NC.search(lic) and not nc and not m.get("conditional_license"):
            errors.append(f"{where}: license '{lic}' có dấu hiệu phi thương mại nhưng không có non_commercial: true")
        if nc and m.get("commercial_ok") is True:
            errors.append(f"{where}: non_commercial: true mâu thuẫn với commercial_ok: true")
        if nc and m["id"] not in docs:
            errors.append(f"{where}: mô hình phi thương mại chưa được nêu trong docs/MODEL_LICENSES.md")
        if nc and path and path[-1] == "default":
            errors.append(f"{where}: mô hình phi thương mại không được là mặc định")
        for f in (m.get("download") or {}).get("files", []):
            if not str(f.get("url", "")).startswith("https://"):
                errors.append(f"{where}: url tải không phải https ({f.get('url')})")
            big = int(f.get("bytes", 0)) > SMALL_FILE
            if f.get("sha256") and not HEX64.match(str(f["sha256"]).lower()):
                errors.append(f"{where}: sha256 sai định dạng cho {f.get('path')}")
            elif big and not f.get("sha256"):
                errors.append(f"{where}: file > 5 MB phải có sha256 ({f.get('path')})")
            elif not f.get("sha256") and not f.get("bytes"):
                errors.append(f"{where}: file nhỏ phải có ít nhất `bytes` để kiểm kích thước ({f.get('path')})")
    return errors


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    registry = yaml.safe_load((ROOT / "models" / "registry.yaml").read_text(encoding="utf-8"))
    docs = (ROOT / "docs" / "MODEL_LICENSES.md").read_text(encoding="utf-8")
    errors = check(registry, docs)
    n = len(list(walk(registry.get("capabilities", {}))))
    for e in errors:
        print("LỖI:", e)
    print(f"Đã kiểm {n} mô hình: {'không có lỗi' if not errors else f'{len(errors)} lỗi'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
