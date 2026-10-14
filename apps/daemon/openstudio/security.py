"""Token Bearer + che thông tin nhạy cảm trong log."""
from __future__ import annotations

import hmac
import re
import secrets
from pathlib import Path

from fastapi import Request

from .errors import ApiError


def new_token() -> str:
    return secrets.token_urlsafe(32)


def check_bearer(request: Request, token: str) -> None:
    header = request.headers.get("authorization", "")
    scheme, _, supplied = header.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.encode(), token.encode()):
        raise ApiError(401, "UNAUTHORIZED", "Thiếu hoặc sai token")


_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"), r"\1***"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\s*[=:]\s*)[^\s&\"']+"), r"\1***"),
    (re.compile(r"([?&](?:X-Amz-Signature|Signature|sig|token)=)[^&\s]+", re.I), r"\1***"),
]


def redact(text: str) -> str:
    home = str(Path.home())
    if home and home in text:
        text = text.replace(home, "~")
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


def safe_join(base: Path, rel: str) -> Path:
    """Chặn path traversal: kết quả luôn nằm trong base."""
    p = (base / rel).resolve()
    if base.resolve() not in p.parents and p != base.resolve():
        raise ApiError(400, "VALIDATION_FAILED", "Đường dẫn không hợp lệ")
    return p


def sign_file(token: str, pid: str, path: str, exp: int) -> str:
    """Chữ ký HMAC cho URL tải file ngắn hạn (thẻ <video>/<a> không gửi được header Authorization)."""
    return hmac.new(token.encode(), f"{pid}|{path}|{exp}".encode(), "sha256").hexdigest()


def verify_file_sig(token: str, pid: str, path: str, exp: int, sig: str, now_ts: float) -> bool:
    return exp >= now_ts and hmac.compare_digest(sign_file(token, pid, path, exp), sig)
