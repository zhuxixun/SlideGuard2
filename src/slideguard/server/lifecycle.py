from __future__ import annotations

import asyncio
from collections.abc import Callable


class LifecycleController:
    def __init__(self, *, idle_seconds: float = 15.0) -> None:
        self.idle_seconds = idle_seconds
        self._clients = 0
        self._shutdown_callback: Callable[[], None] | None = None
        self._idle_task: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def connected_clients(self) -> int:
        return self._clients

    def set_shutdown_callback(self, callback: Callable[[], None]) -> None:
        self._shutdown_callback = callback

    async def connected(self) -> None:
        if self._closed:
            return
        self._clients += 1
        self._cancel_idle_task()

    async def disconnected(self) -> None:
        if self._clients > 0:
            self._clients -= 1
        if self._clients == 0 and not self._closed:
            self._cancel_idle_task()
            self._idle_task = asyncio.create_task(self._shutdown_after_idle())

    def request_shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cancel_idle_task()
        if self._shutdown_callback is not None:
            self._shutdown_callback()

    async def close(self) -> None:
        self._closed = True
        task = self._idle_task
        self._cancel_idle_task()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def _shutdown_after_idle(self) -> None:
        try:
            await asyncio.sleep(self.idle_seconds)
        except asyncio.CancelledError:
            return
        if self._clients == 0:
            self.request_shutdown()

    def _cancel_idle_task(self) -> None:
        if self._idle_task is not None:
            self._idle_task.cancel()
            self._idle_task = None

