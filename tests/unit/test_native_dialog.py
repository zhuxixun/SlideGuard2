import asyncio
from pathlib import Path
from threading import get_ident

from fastapi.testclient import TestClient

from slideguard.server.app import create_app
from slideguard.server.native_dialog import NativeDialogService


class FakeDialogBackend:
    def __init__(self, values: list[str | None]) -> None:
        self.values = values
        self.thread_ids: list[int] = []
        self.closed = False

    def open_pptx(self) -> str | None:
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


def test_dialog_api_returns_selected_path_and_cancel() -> None:
    backend = FakeDialogBackend(["C:/samples/one.pptx", None])
    service = NativeDialogService(lambda: backend)
    headers = {"X-SlideGuard-Token": "secret"}
    with TestClient(
        create_app(token="secret", native_dialog=service)
    ) as client:
        selected = client.post("/api/dialog/open-pptx", headers=headers)
        cancelled = client.post("/api/dialog/open-pptx", headers=headers)

    assert selected.json() == {
        "cancelled": False,
        "path": "C:\\samples\\one.pptx",
    }
    assert cancelled.json() == {"cancelled": True, "path": None}
    assert backend.closed is True

