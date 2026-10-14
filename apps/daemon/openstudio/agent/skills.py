"""Skills: thư mục `skills/<tên>/SKILL.md` (có sẵn, chỉ đọc) + `.runtime/skills/<tên>/SKILL.md` (người dùng tạo/nhập).
Skill CHỈ là văn bản hướng dẫn cho LLM — không chạy mã. Mọi bước vẫn đi qua tool có kiểm tra tham số + phê duyệt,
nên một Skill nhập từ nguồn lạ không thể vượt qua cổng duyệt."""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from ..errors import ApiError

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
MAX_BODY = 20_000
_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)
_STEP = re.compile(r"^\s*\d+[.)]\s+.*?`([a-z_][a-z0-9_.-]*)`", re.M)

TEMPLATE = """---
name: ten-skill-cua-ban
description: Mô tả ngắn khi nào nên dùng Skill này (ví dụ "Khi người dùng muốn …").
tools: [subtitles_transcribe, subtitles_translate]
---
# Tên Skill

## Khi nào dùng
- …

## Các bước
1. `subtitles_transcribe` — …
2. `subtitles_translate` — …

## Tiêu chí đạt
- …
"""


@dataclass
class Skill:
    name: str
    description: str
    tools: list[str]
    body: str
    source: str                      # builtin | user
    enabled: bool = True
    steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def public(self, with_body: bool = False) -> dict:
        d = {"name": self.name, "description": self.description, "tools": self.tools, "source": self.source, "enabled": self.enabled,
             "steps": self.steps, "warnings": self.warnings}
        if with_body:
            d["body"] = self.body
        return d


def parse_skill(md: str, source: str, known_tools: set[str] | None = None) -> Skill:
    m = _FRONT.match(md.lstrip("﻿").replace("\r\n", "\n"))
    if not m:
        raise ApiError(400, "SKILL_INVALID", "SKILL.md phải bắt đầu bằng khối frontmatter `---` (name, description, tools)")
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise ApiError(400, "SKILL_INVALID", f"Frontmatter YAML lỗi: {str(e)[:120]}")
    if not isinstance(meta, dict):
        raise ApiError(400, "SKILL_INVALID", "Frontmatter phải là một mapping YAML")
    name, desc, body = str(meta.get("name", "")).strip(), str(meta.get("description", "")).strip(), m.group(2).strip()
    tools = meta.get("tools", [])
    if not NAME_RE.match(name):
        raise ApiError(400, "SKILL_INVALID", "name chỉ gồm a-z, 0-9, dấu gạch ngang (2–41 ký tự)")
    if not (10 <= len(desc) <= 400):
        raise ApiError(400, "SKILL_INVALID", "description phải dài 10–400 ký tự (mô tả khi nào dùng)")
    if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
        raise ApiError(400, "SKILL_INVALID", "tools phải là danh sách tên tool")
    if len(body) > MAX_BODY or not body:
        raise ApiError(400, "SKILL_INVALID", f"Nội dung phải có và tối đa {MAX_BODY} ký tự")
    warnings = []
    if known_tools is not None:
        unknown = [t for t in tools if t not in known_tools]
        if unknown:
            raise ApiError(400, "SKILL_INVALID", "tools không tồn tại: " + ", ".join(unknown[:5]), {"unknown": unknown})
    steps = [t for t in _STEP.findall(body) if t in tools]
    if tools and not steps:
        warnings.append("Không tìm thấy bước đánh số nào có tên tool trong dấu ` `; Agent sẽ không có checklist để bám theo.")
    return Skill(name, desc, [str(t) for t in tools], body, source, True, steps, warnings)


class SkillStore:
    def __init__(self, builtin_dir: Path, user_dir: Path, state_file: Path, known_tools: Callable[[], set[str]]):
        self.builtin_dir, self.user_dir, self.state_file, self._known = builtin_dir, user_dir, state_file, known_tools

    def _disabled(self) -> set[str]:
        try:
            return set(json.loads(self.state_file.read_text(encoding="utf-8")).get("disabled", []))
        except (OSError, ValueError):
            return set()

    def _scan(self, root: Path, source: str) -> list[Skill]:
        out = []
        if root.is_dir():
            for d in sorted(root.iterdir()):
                f = d / "SKILL.md"
                if f.is_file():
                    try:
                        out.append(parse_skill(f.read_text(encoding="utf-8"), source, self._known()))
                    except ApiError as e:  # skill hỏng không làm hỏng cả danh sách; hiện ra để người dùng sửa
                        out.append(Skill(d.name, f"(lỗi) {e.message}", [], "", source, False, [], [e.message]))
        return out

    def list(self) -> list[Skill]:
        off = self._disabled()
        skills = [*self._scan(self.builtin_dir, "builtin"), *self._scan(self.user_dir, "user")]
        seen: set[str] = set()
        out = []
        for s in skills:
            if s.name in seen:
                continue
            seen.add(s.name)
            s.enabled = s.enabled and s.name not in off
            out.append(s)
        return out

    def get(self, name: str) -> Skill:
        s = next((x for x in self.list() if x.name == name), None)
        if not s:
            raise ApiError(404, "SKILL_NOT_FOUND", f"Không có Skill '{name}'")
        return s

    def enabled(self) -> list[Skill]:
        return [s for s in self.list() if s.enabled and s.body]

    def set_enabled(self, name: str, enabled: bool) -> Skill:
        self.get(name)
        off = self._disabled()
        (off.discard if enabled else off.add)(name)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps({"disabled": sorted(off)}), encoding="utf-8")
        return self.get(name)

    def create(self, md: str) -> Skill:
        skill = parse_skill(md, "user", self._known())
        if any(s.name == skill.name and s.source == "builtin" for s in self._scan(self.builtin_dir, "builtin")):
            raise ApiError(409, "SKILL_EXISTS", f"Tên '{skill.name}' trùng Skill có sẵn; hãy đặt tên khác")
        d = self.user_dir / skill.name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(md.replace("\r\n", "\n"), encoding="utf-8")
        return self.get(skill.name)

    def delete(self, name: str) -> None:
        s = self.get(name)
        if s.source != "user":
            raise ApiError(403, "SKILL_READONLY", "Không xoá được Skill có sẵn (chỉ tắt được)")
        shutil.rmtree(self.user_dir / name, ignore_errors=True)

    def export(self, name: str) -> str:
        s = self.get(name)
        f = (self.builtin_dir if s.source == "builtin" else self.user_dir) / name / "SKILL.md"
        return f.read_text(encoding="utf-8")
