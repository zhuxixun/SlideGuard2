import asyncio
from pathlib import Path
from threading import get_ident

from fastapi.testclient import TestClient

from slideguard.server.app import create_app
from slideguard.server.native_dialog import NativeDialogService
from slideguard.application.session import SessionStore
from pptx import Presentation


class FakeDialogBackend:
    def __init__(self, values: list[str | None]) -> None:
        self.values = values
        self.thread_ids: list[int] = []
        self.closed = False

    def open_pptx(self) -> str | None:
        self.thread_ids.append(get_ident())
        return self.values.pop(0)

    def save_report(self, default_name: str, extension: str) -> str | None:
        self.thread_ids.append(get_ident())
        return self.values.pop(0)

    def close(self) -> None:
        self.thread_ids.append(get_ident())
        self.closed = True


def test_dialog_commands_run_serially_on_owned_thread() -> None:
    backend = FakeDialogBackend(["C:/samples/one.pptx", None])
    service = NativeDialogService(lambda: backend)

    async def scenario() -> tuple[Path | None, Path | None]:
        first, second = await asyncio.gather(service.open_pptx(), service.open_pptx())
        return first, second

    try:
        assert asyncio.run(scenario()) == (Path("C:/samples/one.pptx"), None)
    finally:
        service.close()

    assert backend.closed is True
    assert len(set(backend.thread_ids)) == 1
    assert backend.thread_ids[0] != get_ident()


def test_save_report_uses_same_owned_dialog_thread(tmp_path: Path) -> None:
    destination = tmp_path / "report.html"
    backend = FakeDialogBackend([str(destination)])
    service = NativeDialogService(lambda: backend)
    try:
        selected = asyncio.run(service.save_report("default.html", ".html"))
    finally:
        service.close()
    assert selected == destination
    assert backend.closed is True
    assert len(set(backend.thread_ids)) == 1


def test_dialog_api_imports_selected_file_and_cancel(tmp_path: Path) -> None:
    sample = tmp_path / "one.pptx"
    presentation = Presentation()
    presentation.slides.add_slide(presentation.slide_layouts[6])
    presentation.save(sample)
    backend = FakeDialogBackend([str(sample), None])
    service = NativeDialogService(lambda: backend)
    sessions = SessionStore()
    headers = {"X-SlideGuard-Token": "secret"}
    with TestClient(
        create_app(token="secret", native_dialog=service, session_store=sessions)
    ) as client:
        selected = client.post("/api/dialog/open-pptx", headers=headers)
        cancelled = client.post("/api/dialog/open-pptx", headers=headers)

    assert selected.json()["cancelled"] is False
    assert selected.json()["file"]["name"] == "one.pptx"
    assert selected.json()["file"]["slide_count"] == 1
    assert cancelled.json() == {"cancelled": True, "file": None}
    assert sessions.current().presentation.path == sample.resolve()
    assert backend.closed is True
