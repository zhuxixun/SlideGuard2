from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from slideguard.pptx.importer import ImportedPresentation


@dataclass(frozen=True, slots=True)
class PresentationSession:
    presentation: ImportedPresentation
    managed_copy: bool = False


class SessionStore:
    """Thread-safe holder for the one presentation active in this process."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._current: PresentationSession | None = None

    def replace(
        self,
        presentation: ImportedPresentation,
        *,
        managed_copy: bool = False,
    ) -> PresentationSession:
        session = PresentationSession(presentation=presentation, managed_copy=managed_copy)
        with self._lock:
            previous = self._current
            self._current = session
        self._remove_managed(previous)
        return session

    def current(self) -> PresentationSession | None:
        with self._lock:
            return self._current

    def clear(self) -> None:
        with self._lock:
            previous = self._current
            self._current = None
        self._remove_managed(previous)

    @staticmethod
    def _remove_managed(session: PresentationSession | None) -> None:
        if session is None or not session.managed_copy:
            return
        path = session.presentation.path
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass
