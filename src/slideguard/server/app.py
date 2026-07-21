from __future__ import annotations

import secrets

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from slideguard.lexicon import LexiconError, LexiconStore


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

