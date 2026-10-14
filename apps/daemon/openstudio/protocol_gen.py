"""Xuất JSON Schema từ các model Pydantic → packages/protocol/schema.json (rồi sinh TS bằng scripts/gen-protocol.mjs)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic.json_schema import models_json_schema

from . import schemas
from .config import find_root

MODELS = [schemas.ApiErrorResponse, schemas.Progress, schemas.Job, schemas.Event, schemas.Hardware, schemas.Tool,
          schemas.ModelInfo, schemas.Project, schemas.ProjectCreate, schemas.ToolCommand, schemas.JobCreate,
          schemas.ModelDownloadRequest, schemas.UserSettings, schemas.LibraryFile]


def _strip_titles(node):
    """Bỏ `title` tự sinh của Pydantic để json-schema-to-typescript đặt tên theo khoá $defs (tránh type Tool/Tool1...)."""
    if isinstance(node, dict):
        return {k: _strip_titles(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


def build() -> dict:
    _, defs = models_json_schema([(m, "validation") for m in MODELS], ref_template="#/$defs/{model}")
    defs = {"$defs": {k: _strip_titles(v) for k, v in defs["$defs"].items()}}
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "OpenStudioProtocol",
        "type": "object",
        "properties": {m.__name__: {"$ref": f"#/$defs/{m.__name__}"} for m in MODELS},
        "additionalProperties": False,
        "$defs": defs["$defs"],
    }


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else find_root() / "packages" / "protocol" / "schema.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
