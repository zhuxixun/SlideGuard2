from __future__ import annotations

import secrets
import asyncio
from contextlib import asynccontextmanager
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
from fastapi.responses import FileResponse, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from slideguard.lexicon import LexiconError, LexiconStore
from slideguard.application.session import SessionStore
from slideguard.pptx.importer import PptxImportError, inspect_pptx
from slideguard.server.lifecycle import LifecycleController
from slideguard.server.native_dialog import NativeDialogService
from slideguard.scan.manager import ScanManager, ScanManagerSnapshot
from slideguard.scan.models import ScanMode, ScanRequest
from slideguard.rules.models import IssueStatus
from slideguard.preview.svg_builder import PreviewGuide, PreviewObject, build_svg
import re
from typing import Literal
from slideguard.reporting.exporters import default_report_name, export_html, export_xlsx
from slideguard.repair.manager import RepairManager
from slideguard.repair.planner import FixPlanError
from datetime import datetime


class LexiconResponse(BaseModel):
    terms: list[str]
    digest: str
    count: int
    empty: bool


class LexiconUpdate(BaseModel):
    terms: list[str]
    expected_digest: str


class ScanStart(BaseModel):
    mode: ScanMode
    selected_rules: list[str] = Field(default_factory=list)


class ReportExport(BaseModel):
    format: Literal["html", "xlsx"]


class RepairPrepare(BaseModel):
    issue_ids: list[str] = Field(default_factory=list)


class IssueStatusUpdate(BaseModel):
    status: Literal["pending", "ignored"]


def create_app(
    *,
    token: str,
    lexicon_store: LexiconStore | None = None,
    expected_host: str = "testserver",
    allowed_origin: str | None = None,
    frontend_dir: Path | None = None,
    lifecycle: LifecycleController | None = None,
    native_dialog: NativeDialogService | None = None,
    session_store: SessionStore | None = None,
    scan_manager: ScanManager | None = None,
    repair_manager: RepairManager | None = None,
) -> FastAPI:
    session_store = session_store or SessionStore()
    @asynccontextmanager
    async def lifespan(_: FastAPI):  # type: ignore[no-untyped-def]
        try:
            yield
        finally:
            if native_dialog is not None:
                native_dialog.close()

    app = FastAPI(
        title="SlideGuard local service",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
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

    if scan_manager is not None:

        @app.post("/api/scans", status_code=status.HTTP_202_ACCEPTED)
        def start_scan(request: ScanStart) -> dict[str, str]:
            current = session_store.current()
            if current is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "no_presentation", "message": "请先打开 PPTX 文件"},
                )
            terms: tuple[str, ...] = ()
            unavailable_rules: dict[str, str] = {}
            if lexicon_store is not None:
                try:
                    terms = lexicon_store.load().terms
                except LexiconError as exc:
                    unavailable_rules["R010"] = str(exc)
            try:
                scan_id = scan_manager.start(
                    current.presentation,
                    ScanRequest(
                        request.mode,
                        selected_rules=tuple(request.selected_rules),
                        sensitive_terms=terms,
                    ),
                    unavailable_rules=unavailable_rules,
                )
            except (RuntimeError, ValueError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "scan_not_started", "message": str(exc)},
                ) from exc
            return {"scan_id": scan_id, "status": "running"}

        @app.get("/api/scans/current")
        def current_scan() -> dict[str, object]:
            return _scan_snapshot_response(scan_manager.snapshot())

        @app.post("/api/scans/current/cancel", status_code=status.HTTP_202_ACCEPTED)
        def cancel_scan() -> dict[str, object]:
            return {"accepted": scan_manager.cancel()}

        @app.put("/api/scans/current/issues/{issue_id}/status")
        def update_issue_status(issue_id: str, request: IssueStatusUpdate) -> dict[str, str]:
            try:
                updated = scan_manager.set_issue_status(issue_id, IssueStatus(request.status))
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "no_scan_result", "message": str(exc)},
                ) from exc
            if not updated:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": "issue_not_found", "message": "问题不存在"},
                )
            return {"issue_id": issue_id, "status": request.status}

        @app.get("/api/scans/current/slides/{slide_index}/preview")
        def slide_preview(slide_index: int, issue_id: str | None = None) -> Response:
            state = scan_manager.snapshot()
            if state.result is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "no_scan_result", "message": "当前没有可预览的扫描结果"},
                )
            snapshot = state.result.snapshot
            if slide_index < 1 or slide_index > len(snapshot.slides):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": "slide_not_found", "message": "幻灯片页码不存在"},
                )
            slide = snapshot.slides[slide_index - 1]
            found = next((item for item in state.result.issues if item.issue_id == issue_id), None)
            highlighted: frozenset[str] = frozenset()
            references: frozenset[str] = frozenset()
            guides: tuple[PreviewGuide, ...] = ()
            page_highlight = False
            if found is not None and found.slide_index == slide_index:
                if found.object_keys:
                    highlighted = frozenset(found.object_keys[:1])
                    if found.rule_id == "R007":
                        references = frozenset(found.object_keys[1:])
                        match = re.search(r"(left|right|hcenter|top|bottom|vcenter)=(-?\d+(?:\.\d+)?)pt", found.expected_value)
                        if match:
                            axis = "x" if match.group(1) in {"left", "right", "hcenter"} else "y"
                            guides = (PreviewGuide(axis, float(match.group(2))),)
                else:
                    page_highlight = True
            objects = tuple(_preview_objects(slide.objects))
            svg = build_svg(
                slide_width_pt=snapshot.slide_width_pt,
                slide_height_pt=snapshot.slide_height_pt,
                objects=objects,
                highlighted_ids=highlighted,
                reference_ids=references,
                page_highlight=page_highlight,
                guides=guides,
            )
            return Response(svg, media_type="image/svg+xml")

    if native_dialog is not None:

        @app.post("/api/dialog/open-pptx")
        async def open_pptx_dialog() -> dict[str, object]:
            if scan_manager is not None and scan_manager.snapshot().state.value == "running":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "scan_running", "message": "扫描正在执行，请先取消或等待完成"},
                )
            selected = await native_dialog.open_pptx()
            if selected is None:
                return {"cancelled": True, "file": None}
            try:
                imported = await asyncio.to_thread(inspect_pptx, selected)
            except PptxImportError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={"code": exc.code, "message": str(exc)},
                ) from exc
            session_store.replace(imported)
            if scan_manager is not None:
                scan_manager.reset()
            return {
                "cancelled": False,
                "file": {
                    "name": imported.file_name,
                    "path": str(imported.path),
                    "size_bytes": imported.size_bytes,
                    "slide_count": imported.slide_count,
                },
            }

        if scan_manager is not None:

            @app.post("/api/reports/export")
            async def export_report(request: ReportExport) -> dict[str, object]:
                state = scan_manager.snapshot()
                if state.result is None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={"code": "no_scan_result", "message": "当前没有可导出的扫描结果"},
                    )
                extension = f".{request.format}"
                selected = await native_dialog.save_report(
                    default_report_name(state.result, extension),
                    extension,
                )
                if selected is None:
                    return {"cancelled": True, "path": None}
                if selected.suffix.lower() != extension:
                    selected = selected.with_suffix(extension)
                try:
                    exporter = export_html if request.format == "html" else export_xlsx
                    await asyncio.to_thread(exporter, state.result, selected)
                except FileExistsError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={"code": "report_exists", "message": str(exc)},
                    ) from exc
                except (OSError, ValueError) as exc:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail={"code": "report_export_failed", "message": str(exc)},
                    ) from exc
                return {"cancelled": False, "path": str(selected.resolve())}

            if repair_manager is not None:

                @app.post("/api/repairs/prepare")
                async def prepare_repair(request: RepairPrepare) -> dict[str, object]:
                    state = scan_manager.snapshot()
                    if state.result is None:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail={"code": "no_scan_result", "message": "当前没有可修复的扫描结果"},
                        )
                    default_name = (
                        f"{state.result.snapshot.file_identity.path.stem}_SlideGuard_fixed_"
                        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.pptx"
                    )
                    selected = await native_dialog.save_report(default_name, ".pptx")
                    if selected is None:
                        return {"cancelled": True, "plan": None}
                    if selected.suffix.lower() != ".pptx":
                        selected = selected.with_suffix(".pptx")
                    try:
                        plan = repair_manager.prepare(
                            state.result,
                            tuple(request.issue_ids),
                            selected,
                        )
                    except (FixPlanError, RuntimeError) as exc:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail={"code": "repair_plan_failed", "message": str(exc)},
                        ) from exc
                    return {
                        "cancelled": False,
                        "plan": {
                            "destination": str(plan.destination),
                            "issue_count": len(plan.issue_ids),
                            "page_count": len({
                                found.slide_index
                                for found in state.result.issues
                                if found.issue_id in plan.issue_ids
                            }),
                            "object_count": len({operation.object_key for operation in plan.operations}),
                            "operations": [
                                {
                                    "object_key": operation.object_key,
                                    "property_name": operation.property_name,
                                    "original_value": operation.original_value,
                                    "target_value": operation.target_value,
                                }
                                for operation in plan.operations
                            ],
                        },
                    }

                @app.post("/api/repairs/execute")
                async def execute_repair() -> dict[str, object]:
                    terms: tuple[str, ...] = ()
                    if lexicon_store is not None:
                        try:
                            terms = lexicon_store.load().terms
                        except LexiconError as exc:
                            raise HTTPException(
                                status_code=status.HTTP_409_CONFLICT,
                                detail={"code": "lexicon_read_failed", "message": str(exc)},
                            ) from exc
                    try:
                        repaired = await asyncio.to_thread(
                            repair_manager.execute,
                            sensitive_terms=terms,
                        )
                    except (FixPlanError, RuntimeError, OSError) as exc:
                        raise HTTPException(
                            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail={"code": "repair_failed", "message": str(exc)},
                        ) from exc
                    scan_manager.adopt_result(repaired.verification_scan)
                    return {
                        "destination": str(repaired.destination),
                        "fixed_count": len(repaired.fixed_issue_ids),
                        "unresolved_count": len(repaired.unresolved_issue_ids),
                        "introduced_count": repaired.introduced_issue_count,
                        "verification_complete": repaired.verification_scan.complete,
                        "scan": _scan_snapshot_response(scan_manager.snapshot()),
                    }

                @app.delete("/api/repairs/prepare", status_code=status.HTTP_204_NO_CONTENT)
                def clear_repair_plan() -> Response:
                    repair_manager.clear()
                    return Response(status_code=status.HTTP_204_NO_CONTENT)

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
            queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=100)
            unsubscribe = None
            if scan_manager is not None:
                loop = asyncio.get_running_loop()

                def listener(snapshot: ScanManagerSnapshot) -> None:
                    def enqueue() -> None:
                        if queue.full():
                            queue.get_nowait()
                        queue.put_nowait({"type": "scan", "payload": _scan_snapshot_response(snapshot)})
                    loop.call_soon_threadsafe(enqueue)

                unsubscribe = scan_manager.subscribe(listener)
            try:
                while True:
                    receive = asyncio.create_task(websocket.receive_text())
                    event = asyncio.create_task(queue.get()) if scan_manager is not None else None
                    tasks = {receive} | ({event} if event is not None else set())
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in pending:
                        task.cancel()
                    if receive in done:
                        message = receive.result()
                        if message == "ping":
                            await websocket.send_text("pong")
                    elif event is not None and event in done:
                        await websocket.send_json(event.result())
            except WebSocketDisconnect:
                pass
            finally:
                if unsubscribe is not None:
                    unsubscribe()
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

        @app.get("/assets/app.css", include_in_schema=False)
        def frontend_styles() -> FileResponse:
            return FileResponse(frontend_dir / "app.css", media_type="text/css")

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


def _scan_snapshot_response(snapshot: ScanManagerSnapshot) -> dict[str, object]:
    response: dict[str, object] = {
        "scan_id": snapshot.scan_id,
        "state": snapshot.state.value,
        "error": snapshot.error,
        "progress": None,
        "result": None,
    }
    if snapshot.progress is not None:
        response["progress"] = {
            "stage": snapshot.progress.stage.value,
            "completed_rules": snapshot.progress.completed_rules,
            "total_rules": snapshot.progress.total_rules,
            "current_rule": snapshot.progress.current_rule,
        }
    if snapshot.result is not None:
        result = snapshot.result
        response["result"] = {
            "mode": result.mode.value,
            "rule_set_version": result.rule_set_version,
            "requested_rules": result.requested_rules,
            "completed_rules": result.completed_rules,
            "complete": result.complete,
            "cancelled": result.cancelled,
            "failures": [
                {"rule_id": failure.rule_id, "message": failure.message}
                for failure in result.failures
            ],
            "repair_comparison": (
                {
                    "selected_count": result.repair_comparison.selected_count,
                    "fixed_count": result.repair_comparison.fixed_count,
                    "unresolved_count": result.repair_comparison.unresolved_count,
                    "introduced_count": result.repair_comparison.introduced_count,
                }
                if result.repair_comparison is not None else None
            ),
            "issues": [
                {
                    "issue_id": found.issue_id,
                    "rule_id": found.rule_id,
                    "slide_index": found.slide_index,
                    "severity": found.severity.value,
                    "actual_value": found.actual_value,
                    "expected_value": found.expected_value,
                    "evidence": found.evidence,
                    "suggestion": found.suggestion,
                    "can_auto_fix": found.can_auto_fix,
                    "status": found.status.value,
                    "object_keys": found.object_keys,
                    "standard_source": found.standard_source,
                    "fix_proposal": (
                        {"kind": found.fix_proposal.kind, "target_value": found.fix_proposal.target_value}
                        if found.fix_proposal is not None else None
                    ),
                    "introduced_by_repair": found.introduced_by_repair,
                }
                for found in result.issues
            ],
            "started_at": result.started_at.isoformat(),
            "finished_at": result.finished_at.isoformat(),
        }
    return response


def _preview_objects(objects):  # type: ignore[no-untyped-def]
    for obj in objects:
        yield PreviewObject(
            object_id=obj.key,
            x=obj.bounds_pt.left,
            y=obj.bounds_pt.top,
            width=obj.bounds_pt.width,
            height=obj.bounds_pt.height,
            text=obj.text_frame.text if obj.text_frame is not None else "",
        )
        yield from _preview_objects(obj.children)


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
