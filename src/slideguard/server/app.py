from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import (
    BackgroundTasks,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from slideguard.lexicon import LexiconError, LexiconStore
from slideguard.server.lifecycle import LifecycleController


class LexiconResponse(BaseModel):
    terms: list[str]
    digest: str
    count: int
    empty: bool


class LexiconUpdate(BaseModel):
    terms: list[str]
    expected_digest: str


def create_app(
    *,
    token: str,
    lexicon_store: LexiconStore | None = None,
    expected_host: str = "testserver",
    allowed_origin: str | None = None,
    frontend_dir: Path | None = None,
    lifecycle: LifecycleController | None = None,
) -> FastAPI:
    app = FastAPI(
        title="SlideGuard local service",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def secure_local_request(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.headers.get("host") != expected_host:
            return _error(status.HTTP_400_BAD_REQUEST, "invalid_host", "无效的本机服务地址")

        origin = request.headers.get("origin")
        if origin is not None and (allowed_origin is None or origin != allowed_origin):
            return _error(status.HTTP_403_FORBIDDEN, "invalid_origin", "请求来源不受信任")

        if request.url.path.startswith("/api/"):
            provided = request.headers.get("x-slideguard-token")
            if provided is None or not secrets.compare_digest(provided, token):
                return _error(status.HTTP_401_UNAUTHORIZED, "invalid_token", "会话令牌无效")

        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'"
        )
        return response

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    if lifecycle is not None:

        @app.post("/api/exit", status_code=status.HTTP_202_ACCEPTED)
        async def exit_application(background_tasks: BackgroundTasks) -> dict[str, str]:
            background_tasks.add_task(lifecycle.request_shutdown)
            return {"status": "shutting_down"}

        @app.websocket("/ws")
        async def websocket_session(websocket: WebSocket) -> None:
            if not _valid_websocket_request(
                websocket,
                token=token,
                expected_host=expected_host,
                allowed_origin=allowed_origin,
            ):
                await websocket.close(code=1008)
                return
            await websocket.accept(subprotocol="slideguard")
            await lifecycle.connected()
            try:
                while True:
                    message = await websocket.receive_text()
                    if message == "ping":
                        await websocket.send_text("pong")
            except WebSocketDisconnect:
                pass
            finally:
                await lifecycle.disconnected()

    if frontend_dir is not None:

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(frontend_dir / "index.html", media_type="text/html")

        @app.get("/assets/app.js", include_in_schema=False)
        def frontend_script() -> FileResponse:
            return FileResponse(
                frontend_dir / "app.js",
                media_type="text/javascript",
            )

    if lexicon_store is not None:

        @app.get("/api/lexicon", response_model=LexiconResponse)
        def get_lexicon() -> LexiconResponse:
            try:
                snapshot = lexicon_store.load()
            except LexiconError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={"code": "lexicon_read_failed", "message": str(exc)},
                ) from exc
            return _lexicon_response(snapshot.terms, snapshot.digest)

        @app.put("/api/lexicon", response_model=LexiconResponse)
        def put_lexicon(update: LexiconUpdate) -> LexiconResponse:
            try:
                snapshot = lexicon_store.save(
                    update.terms,
                    expected_digest=update.expected_digest,
                )
            except LexiconError as exc:
                code = "lexicon_conflict" if "其他操作修改" in str(exc) else "lexicon_save_failed"
                http_status = (
                    status.HTTP_409_CONFLICT
                    if code == "lexicon_conflict"
                    else status.HTTP_422_UNPROCESSABLE_CONTENT
                )
                raise HTTPException(
                    status_code=http_status,
                    detail={"code": code, "message": str(exc)},
                ) from exc
            return _lexicon_response(snapshot.terms, snapshot.digest)

    return app


def _lexicon_response(terms: tuple[str, ...], digest: str) -> LexiconResponse:
    return LexiconResponse(
        terms=list(terms),
        digest=digest,
        count=len(terms),
        empty=not terms,
    )


def _error(http_status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=http_status,
        content={"detail": {"code": code, "message": message}},
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _valid_websocket_request(
    websocket: WebSocket,
    *,
    token: str,
    expected_host: str,
    allowed_origin: str | None,
) -> bool:
    if websocket.headers.get("host") != expected_host:
        return False
    origin = websocket.headers.get("origin")
    if origin is not None and (allowed_origin is None or origin != allowed_origin):
        return False
    offered = {
        item.strip()
        for item in websocket.headers.get("sec-websocket-protocol", "").split(",")
    }
    return "slideguard" in offered and any(
        secrets.compare_digest(item, token) for item in offered
    )
