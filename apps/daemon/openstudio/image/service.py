"""Tạo ảnh AI cục bộ (FLUX.2 klein 4B lượng tử qua stable-diffusion.cpp, CPU): prompt (+ ảnh tham chiếu) → vài biến thể → vào kho tài nguyên."""
from __future__ import annotations

import json
import random
import re
import time

from ..assets import AssetStore
from ..config import Settings
from ..errors import ApiError
from ..jobs import JobContext, JobRunner
from ..models import ModelManager
from ..repo import Repo
from ..subtitles.llm import LLMClient
from ..tts.service import ai_label_enabled
from ..workers.runner import run_process
from . import engine as E
from .state import TOOL, dims, initial_state, new_id, reducer

PROMPT_SCHEMA = {"type": "object", "properties": {"prompt": {"type": "string"}}, "required": ["prompt"]}
_CJK = re.compile("[぀-ヿ㐀-䶿一-鿿가-힯]")


class ImageService:
    def __init__(self, settings: Settings, repo: Repo, runner: JobRunner, assets: AssetStore, models: ModelManager, llm: LLMClient):
        self.s, self.repo, self.runner, self.assets, self.models, self.llm = settings, repo, runner, assets, models, llm
        repo.reducers[TOOL] = reducer
        runner.register("image.generate", self._job)

    def state(self, pid: str) -> dict:
        st = self.repo.get_state(pid, TOOL)["state"]
        return {**initial_state(), **st} if st else initial_state()

    def commit(self, pid: str, type: str, payload: dict) -> dict:
        return self.repo.apply_command(pid, TOOL, type, payload, None, author="job")

    def status(self) -> dict:
        """Trạng thái engine/mô hình cho giao diện: cái gì đã cài, cái gì còn thiếu."""
        eid = E.engine_id()
        ids = {m["id"]: m["status"] for m in self.models.list()}
        return {"engine": eid, "engineInstalled": bool(eid and ids.get(eid) == "installed"), "model": E.MODEL_ID, "modelInstalled": ids.get(E.MODEL_ID) == "installed",
                "supported": eid is not None, "device": "cpu",
                "note": "Chạy trên CPU: ~vài phút mỗi ảnh (thời gian thật phụ thuộc máy). Ảnh có chữ tiếng Việt: hãy thêm chữ ở công cụ Thumbnail, đừng nhờ AI vẽ chữ."}

    def start(self, pid: str) -> dict:
        b = self.state(pid)["brief"]
        if not b["prompt"].strip():
            raise ApiError(409, "BRIEF_REQUIRED", "Hãy nhập mô tả ảnh (prompt)")
        eid = E.engine_id()
        if eid is None:
            raise ApiError(424, "ENGINE_UNSUPPORTED", "Chưa có bản engine tạo ảnh cho hệ điều hành/kiến trúc này")
        E.cli_path(self.s.models_dir, eid)                  # 424 sớm nếu thiếu
        E.model_paths(self.s.models_dir)
        if b["refAsset"]:
            if self.assets.get(pid, b["refAsset"])["kind"] != "image":
                raise ApiError(400, "VALIDATION_FAILED", "Ảnh tham chiếu phải là tài nguyên dạng ảnh")
        return self.runner.submit("image.generate", {}, pid, TOOL)

    def english_prompt(self, text: str) -> tuple[str, str | None]:
        """Dịch/làm giàu prompt sang tiếng Anh bằng LLM cục bộ (FLUX hiểu tiếng Anh tốt nhất). Trả (prompt, cảnh báo)."""
        try:
            self.llm.require()
            res = self.llm.json_object(
                "You write prompts for a text-to-image model. Translate the user's idea into ONE clear English prompt (max 60 words): subject, setting, style, lighting. "
                "Keep every concrete detail the user gave; do not add text/lettering to the image; do not add people or brands the user did not mention. "
                'Reply with ONLY JSON {"prompt": "..."}.', text, PROMPT_SCHEMA, max_tokens=300)
            out = str((res or {}).get("prompt", "")).strip()
            if out and not _CJK.search(out):
                return out, None
            return text, "LLM không dịch được prompt; dùng nguyên văn."
        except ApiError as e:
            return text, f"Không dùng được LLM để dịch prompt ({e.code}); dùng nguyên văn — nên viết prompt bằng tiếng Anh."

    def _job(self, ctx: JobContext) -> dict:
        pid = ctx.project_id
        base = self.s.projects_dir / pid
        b = self.state(pid)["brief"]
        eid = E.engine_id()
        cli = E.cli_path(self.s.models_dir, eid)             # type: ignore[arg-type]
        paths = E.model_paths(self.s.models_dir)
        w, h = dims(b["aspect"], b["quality"])
        warnings: list[str] = []
        prompt = b["prompt"].strip()
        if b["translate"] and b["language"] != "en":
            ctx.progress("prompt", 2, "Chuẩn bị prompt tiếng Anh")
            prompt, warn = self.english_prompt(prompt)
            if warn:
                warnings.append(warn)
        self.llm.unload()                                   # nhả RAM cho mô hình ảnh (Ollama giữ ~4 GB)
        ref = (base / self.assets.get(pid, b["refAsset"])["path"]) if b["refAsset"] else None
        out_dir = base / "exports" / "images"
        out_dir.mkdir(parents=True, exist_ok=True)
        seed0 = b["seed"] if b["seed"] is not None else random.randrange(0, 2**31 - 8)
        results = []
        n = b["count"]
        for i in range(n):
            ctx.check_cancel()
            seed = (seed0 + i) % 2**31
            name = f"image_{int(time.time())}_{seed}.png"
            out = out_dir / name
            t0 = time.time()
            lo, span = 5 + 93 * i / n, 93 / n
            last = {"step": 0}

            def on_line(line: str, lo=lo, span=span, i=i, last=last) -> None:
                st = E.parse_step(line)
                if st:
                    last["step"] = st[0]
                    ctx.progress("generate", lo + span * (0.15 + 0.7 * st[0] / max(1, st[1])), f"Ảnh {i + 1}/{n} · bước {st[0]}/{st[1]}", i, 0, n)

            ctx.progress("generate", lo, f"Ảnh {i + 1}/{n} · nạp mô hình", i, 0, n)
            code, tail = run_process(E.build_cmd(cli, paths, prompt, w, h, seed, out, ref), cwd=cli.parent, on_line=on_line, on_err_line=on_line, cancelled=ctx.cancelled)
            if code != 0 or not out.is_file():
                raise ApiError(422, "IMAGE_FAILED", "Tạo ảnh lỗi: " + (tail.strip().splitlines() or ["không rõ"])[-1][:300])
            if ai_label_enabled(self.s):                    # nhãn "AI tạo" dạng sidecar (PNG không có chỗ chuẩn cho metadata tuỳ ý)
                out.with_suffix(".png.json").write_text(json.dumps({"ai_generated": True, "generator": "OpenStudio AI", "model": E.MODEL_ID, "seed": seed,
                                                                     "prompt": prompt, "license": "Apache-2.0 (FLUX.2 klein 4B)"}, ensure_ascii=False, indent=1), encoding="utf-8")
            rel = f"exports/images/{name}"
            asset = self.assets.register_existing(pid, rel, name)
            results.append({"id": new_id(), "file": rel, "assetId": asset["id"], "seed": seed, "width": w, "height": h, "prompt": prompt,
                            "seconds": round(time.time() - t0, 1), "ai": ai_label_enabled(self.s)})
            self.commit(pid, "_add-results", {"results": [results[-1]], "last": {"warnings": warnings, "englishPrompt": prompt}})
        ctx.progress("done", 100, "Hoàn tất")
        return {"images": len(results), "seconds": [r["seconds"] for r in results], "warnings": warnings, "prompt": prompt}
