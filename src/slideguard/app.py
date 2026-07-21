from __future__ import annotations

import secrets

import uvicorn

from slideguard.server.app import create_app


def run() -> None:
    token = secrets.token_urlsafe(32)
    app = create_app(token=token)
    uvicorn.run(app, host="127.0.0.1", port=0, access_log=False)

