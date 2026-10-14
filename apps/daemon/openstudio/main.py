"""Điểm vào daemon: nghe 127.0.0.1, in {"address","token"} ra stdout để web/desktop kết nối."""
from __future__ import annotations

import json
import os
import socket
import sys

import uvicorn

from .app import create_app
from .config import load_settings
from .security import new_token


def run() -> None:
    settings = load_settings()
    token = os.environ.get("OPENSTUDIO_TOKEN") or new_token()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((settings.host, settings.port))
    port = sock.getsockname()[1]
    app = create_app(settings, token)
    # container: không in token ra log (token do người dùng đặt qua OPENSTUDIO_TOKEN)
    print(json.dumps({"address": f"http://{settings.host}:{port}", **({} if settings.remote_bind else {"token": token})}), flush=True)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    server.run(sockets=[sock])


if __name__ == "__main__":
    sys.exit(run())
