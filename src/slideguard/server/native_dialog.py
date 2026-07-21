from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Protocol, TypeVar


T = TypeVar("T")


class DialogBackend(Protocol):
    def open_pptx(self) -> str | None: ...

    def save_report(self, default_name: str, extension: str) -> str | None: ...

    def close(self) -> None: ...


class NativeDialogService:
    def __init__(
        self,
        backend_factory: Callable[[], DialogBackend] | None = None,
    ) -> None:
        self._backend_factory = backend_factory or _TkDialogBackend
        self._commands: Queue[
            tuple[Callable[[DialogBackend], object], Future[object]] | None
        ] = Queue()
        self._thread = Thread(
            target=self._worker,
            name="native-dialog",
            daemon=True,
        )
        self._closed = False
        self._thread.start()

    async def open_pptx(self) -> Path | None:
        value = await asyncio.wrap_future(
            self._submit(lambda backend: backend.open_pptx())
        )
        return Path(value) if isinstance(value, str) and value else None

    async def save_report(self, default_name: str, extension: str) -> Path | None:
        value = await asyncio.wrap_future(
            self._submit(lambda backend: backend.save_report(default_name, extension))
        )
        return Path(value) if isinstance(value, str) and value else None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._commands.put(None)
        self._thread.join(timeout=5)

    def _submit(self, command: Callable[[DialogBackend], T]) -> Future[T]:
        if self._closed:
            raise RuntimeError("原生文件对话框服务已关闭")
        future: Future[T] = Future()
        self._commands.put((command, future))  # type: ignore[arg-type]
        return future

    def _worker(self) -> None:
        backend: DialogBackend | None = None
        try:
            backend = self._backend_factory()
            while True:
                item = self._commands.get()
                if item is None:
                    return
                command, future = item
                if future.set_running_or_notify_cancel():
                    try:
                        future.set_result(command(backend))
                    except BaseException as exc:
                        future.set_exception(exc)
        finally:
            if backend is not None:
                backend.close()


class _TkDialogBackend:
    def __init__(self) -> None:
        import tkinter

        self._filedialog = __import__("tkinter.filedialog", fromlist=["filedialog"])
        self._root = tkinter.Tk()
        self._root.withdraw()

    def open_pptx(self) -> str | None:
        value = self._filedialog.askopenfilename(
            parent=self._root,
            title="打开PPT文件",
            filetypes=(("PowerPoint 演示文稿", "*.pptx"),),
        )
        return value or None

    def save_report(self, default_name: str, extension: str) -> str | None:
        label = {".html": "HTML 报告", ".xlsx": "Excel 报告", ".pptx": "PowerPoint 演示文稿"}[extension]
        value = self._filedialog.asksaveasfilename(
            parent=self._root,
            title="导出质检报告",
            initialfile=default_name,
            defaultextension=extension,
            filetypes=((label, f"*{extension}"),),
        )
        return value or None

    def close(self) -> None:
        self._root.destroy()
