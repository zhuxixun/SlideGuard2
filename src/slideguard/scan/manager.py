from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from secrets import token_hex
from threading import RLock, Thread
from typing import Callable

from slideguard.pptx.importer import ImportedPresentation
from slideguard.scan.models import ScanProgress, ScanRequest, ScanResult
from slideguard.rules.models import IssueStatus
from slideguard.scan.orchestrator import CancellationToken, run_scan, select_rules


class ManagerState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ScanManagerSnapshot:
    scan_id: str | None
    state: ManagerState
    progress: ScanProgress | None
    result: ScanResult | None
    error: str | None


Listener = Callable[[ScanManagerSnapshot], None]


class ScanManager:
    def __init__(self) -> None:
        self._lock = RLock()
        self._scan_id: str | None = None
        self._state = ManagerState.IDLE
        self._progress: ScanProgress | None = None
        self._result: ScanResult | None = None
        self._error: str | None = None
        self._cancellation: CancellationToken | None = None
        self._listeners: set[Listener] = set()

    def start(
        self,
        imported: ImportedPresentation,
        request: ScanRequest,
        *,
        unavailable_rules: dict[str, str] | None = None,
    ) -> str:
        select_rules(request)
        with self._lock:
            if self._state is ManagerState.RUNNING:
                raise RuntimeError("已有扫描正在执行")
            scan_id = token_hex(12)
            self._scan_id = scan_id
            self._state = ManagerState.RUNNING
            self._progress = None
            self._result = None
            self._error = None
            self._cancellation = CancellationToken()
            cancellation = self._cancellation
        self._publish()
        Thread(
            target=self._run,
            args=(scan_id, imported, request, cancellation, unavailable_rules or {}),
            name=f"scan-{scan_id}",
            daemon=True,
        ).start()
        return scan_id

    def cancel(self) -> bool:
        with self._lock:
            if self._state is not ManagerState.RUNNING or self._cancellation is None:
                return False
            self._cancellation.cancel()
            return True

    def snapshot(self) -> ScanManagerSnapshot:
        with self._lock:
            return ScanManagerSnapshot(
                self._scan_id,
                self._state,
                self._progress,
                self._result,
                self._error,
            )

    def set_issue_status(self, issue_id: str, status: IssueStatus) -> bool:
        with self._lock:
            if self._result is None:
                raise RuntimeError("当前没有可更新的扫描结果")
            found = next((item for item in self._result.issues if item.issue_id == issue_id), None)
            if found is None:
                return False
            issues = tuple(
                replace(item, status=status) if item.issue_id == issue_id else item
                for item in self._result.issues
            )
            self._result = replace(self._result, issues=issues)
        self._publish()
        return True

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        with self._lock:
            self._listeners.add(listener)
        listener(self.snapshot())

        def unsubscribe() -> None:
            with self._lock:
                self._listeners.discard(listener)

        return unsubscribe

    def _run(
        self,
        scan_id: str,
        imported: ImportedPresentation,
        request: ScanRequest,
        cancellation: CancellationToken,
        unavailable_rules: dict[str, str],
    ) -> None:
        try:
            result = run_scan(
                imported,
                request,
                cancellation=cancellation,
                on_progress=lambda event: self._on_progress(scan_id, event),
                unavailable_rules=unavailable_rules,
            )
        except Exception as exc:
            with self._lock:
                if self._scan_id != scan_id:
                    return
                self._state = ManagerState.FAILED
                self._error = str(exc) or type(exc).__name__
                self._cancellation = None
            self._publish()
            return
        with self._lock:
            if self._scan_id != scan_id:
                return
            self._result = result
            self._state = ManagerState.COMPLETED if result.complete else ManagerState.INCOMPLETE
            self._cancellation = None
        self._publish()

    def _on_progress(self, scan_id: str, progress: ScanProgress) -> None:
        with self._lock:
            if self._scan_id != scan_id:
                return
            self._progress = progress
        self._publish()

    def _publish(self) -> None:
        snapshot = self.snapshot()
        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener(snapshot)
            except Exception:
                continue
