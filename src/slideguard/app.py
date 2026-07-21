from __future__ import annotations

from pathlib import Path
import secrets
import socket
import subprocess
import threading
import time
import webbrowser

import uvicorn

from slideguard.lexicon import LexiconStore
from slideguard.server.app import create_app
from slideguard.server.lifecycle import LifecycleController


def run() -> None:
    token = secrets.token_urlsafe(32)
    listener = _loopback_listener()
    port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    data_root = Path.cwd() / "data"
    lifecycle = LifecycleController(idle_seconds=15)
    app = create_app(
        token=token,
        lexicon_store=LexiconStore(data_root / "config" / "sensitive-terms.txt"),
        expected_host=f"127.0.0.1:{port}",
        allowed_origin=origin,
        frontend_dir=Path(__file__).parent / "frontend",
        lifecycle=lifecycle,
    )
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        access_log=False,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    lifecycle.set_shutdown_callback(lambda: setattr(server, "should_exit", True))
    url = f"{origin}/#token={token}"
    threading.Thread(
        target=_open_when_ready,
        args=(server, url),
        name="browser-launcher",
        daemon=True,
    ).start()
    server.run(sockets=[listener])


def _loopback_listener() -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    return listener


def _open_when_ready(server: uvicorn.Server, url: str) -> None:
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        return
    if _open_edge_app(url):
        return
    webbrowser.open(url, new=1, autoraise=True)


def _open_edge_app(url: str) -> bool:
    candidates = (
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
    )
    for executable in candidates:
        if executable.is_file():
            subprocess.Popen(  # noqa: S603
                [str(executable), f"--app={url}", "--no-first-run"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
    return False
