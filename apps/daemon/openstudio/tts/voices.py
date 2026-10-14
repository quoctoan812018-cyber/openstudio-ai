"""Kho giọng nhân bản + bản ghi đồng ý (consent). Mọi nhân bản giọng PHẢI gắn với một consent hợp lệ, dùng một lần."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from ..db import Database, new_id, now
from ..errors import ApiError
from ..media import extract_audio, probe

CONSENT_STATEMENT = (
    "Tôi xác nhận rằng tôi có quyền sử dụng giọng nói trong mẫu âm thanh này, hoặc đã có sự đồng ý rõ ràng của "
    "người sở hữu giọng nói để tạo bản sao giọng nói bằng AI. Tôi sẽ không dùng nó để mạo danh, lừa đảo hoặc gây hại."
)
MIN_SAMPLE, MAX_SAMPLE = 3.0, 60.0
RECOMMENDED = (10.0, 30.0)


class ConsentStore:
    def __init__(self, db: Database, dir_: Path):
        self.db, self.dir = db, dir_

    def create(self, kind: str, subject: str, confirmed: bool, project_id: str | None = None) -> dict:
        if kind not in ("voice", "face"):
            raise ApiError(400, "VALIDATION_FAILED", "kind phải là voice hoặc face")
        subject = subject.strip()
        if not subject or len(subject) > 120:
            raise ApiError(400, "VALIDATION_FAILED", "Cần ghi tên người sở hữu giọng nói/gương mặt (tối đa 120 ký tự)")
        if confirmed is not True:
            raise ApiError(409, "CONSENT_REQUIRED", "Bạn phải xác nhận quyền sử dụng và sự đồng ý của người này", {"statement": CONSENT_STATEMENT})
        cid = new_id("cns_")
        self.dir.mkdir(parents=True, exist_ok=True)
        rec = {"id": cid, "kind": kind, "subject": subject, "statement": CONSENT_STATEMENT, "projectId": project_id, "createdAt": now(),
               "usedBy": None}
        evidence = self.dir / f"{cid}.json"
        evidence.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        self.db.execute("INSERT INTO consent(id, kind, subject, statement, project_id, created_at, evidence_path) VALUES(?,?,?,?,?,?,?)",
                        (cid, kind, subject, CONSENT_STATEMENT, project_id, rec["createdAt"], str(evidence)))
        return rec

    def get(self, cid: str) -> dict | None:
        r = self.db.one("SELECT * FROM consent WHERE id=?", (cid,))
        if not r:
            return None
        return {"id": r["id"], "kind": r["kind"], "subject": r["subject"], "statement": r["statement"], "projectId": r["project_id"],
                "createdAt": r["created_at"], "usedBy": r.get("used_by")}

    def list(self) -> list[dict]:
        return [c for c in (self.get(r["id"]) for r in self.db.all("SELECT id FROM consent ORDER BY created_at DESC")) if c]

    def consume(self, cid: str, kind: str, used_by: str, extra: dict) -> dict:
        c = self.get(cid)
        if not c or c["kind"] != kind:
            raise ApiError(409, "CONSENT_REQUIRED", "Cần một bản ghi đồng ý hợp lệ trước khi nhân bản", {"statement": CONSENT_STATEMENT})
        if c["usedBy"]:
            raise ApiError(409, "CONSENT_ALREADY_USED", "Bản ghi đồng ý này đã được dùng cho một giọng khác; hãy xác nhận lại")
        self.db.execute("UPDATE consent SET used_by=? WHERE id=?", (used_by, cid))
        c["usedBy"] = used_by
        path = self.dir / f"{cid}.json"
        path.write_text(json.dumps({**c, **extra}, ensure_ascii=False, indent=2), encoding="utf-8")
        return c


class VoiceLibrary:
    def __init__(self, root: Path, consents: ConsentStore):
        self.root, self.consents = root, consents

    def _meta(self, vid: str) -> dict | None:
        p = self.root / vid / "meta.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    def list(self, lang: str | None = None) -> list[dict]:
        out = []
        if self.root.is_dir():
            for d in sorted(self.root.iterdir()):
                m = self._meta(d.name)
                if m and (lang is None or lang.split("-")[0] in m["languages"]):
                    out.append(self.public(m))
        return out

    @staticmethod
    def public(m: dict) -> dict:
        return {"id": f"clone:{m['id']}", "name": m["name"], "engine": m["engine"], "lang": m["languages"][0], "languages": m["languages"],
                "description": f"Giọng nhân bản · {m['duration']:.0f}s mẫu · đồng ý: {m['subject']}", "gender": "", "kind": "clone",
                "consentId": m["consentId"], "createdAt": m["createdAt"]}

    def resolve(self, vid: str) -> tuple[dict, Path]:
        m = self._meta(vid)
        if not m:
            raise ApiError(404, "VOICE_NOT_FOUND", "Không có giọng này")
        return m, self.root / vid / "ref.wav"

    def create(self, name: str, engine: str, consent_id: str, data: bytes, languages: list[str]) -> dict:
        name = name.strip()
        if not name or len(name) > 60:
            raise ApiError(400, "VALIDATION_FAILED", "Tên giọng 1–60 ký tự")
        if not data:
            raise ApiError(400, "VALIDATION_FAILED", "File mẫu rỗng")
        consent = self.consents.get(consent_id)  # kiểm tra trước khi ghi bất cứ thứ gì
        if not consent or consent["kind"] != "voice" or consent["usedBy"]:
            self.consents.consume(consent_id, "voice", "-", {})  # ném đúng lỗi
        vid = new_id("vc_")
        d = self.root / vid
        d.mkdir(parents=True)
        try:
            raw = d / "upload.bin"
            raw.write_bytes(data)
            info = probe(raw)
            if not (MIN_SAMPLE <= info["duration"] <= MAX_SAMPLE):
                raise ApiError(400, "VALIDATION_FAILED", f"Mẫu giọng phải dài {MIN_SAMPLE:.0f}–{MAX_SAMPLE:.0f} giây (khuyến nghị {RECOMMENDED[0]:.0f}–{RECOMMENDED[1]:.0f}s), mẫu này {info['duration']:.1f}s")
            extract_audio(raw, d / "ref.wav")  # mono 16 kHz PCM
            raw.unlink()
            meta = {"id": vid, "name": name, "engine": engine, "languages": languages, "consentId": consent_id,
                    "subject": consent["subject"], "duration": info["duration"], "sha256": hashlib.sha256(data).hexdigest(),
                    "createdAt": now()}
            (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            self.consents.consume(consent_id, "voice", vid, {"voiceId": vid, "sampleSha256": meta["sha256"]})
            return self.public(meta)
        except BaseException:
            shutil.rmtree(d, ignore_errors=True)
            raise

    def delete(self, vid: str) -> None:
        if not self._meta(vid):
            raise ApiError(404, "VOICE_NOT_FOUND", "Không có giọng này")
        shutil.rmtree(self.root / vid, ignore_errors=True)
