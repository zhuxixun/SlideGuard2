from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from slideguard.pptx.importer import ImportedPresentation


@dataclass(frozen=True, slots=True)
class PresentationSession:
    presentation: ImportedPresentation


class SessionStore:
    """Thread-safe holder for the one presentation active in this process."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._current: PresentationSession | None = None

    def replace(self, presentation: ImportedPresentation) -> PresentationSession:
        session = PresentationSession(presentation=presentation)
        with self._lock:
            self._current = session
        return session

    def current(self) -> PresentationSession | None:
        with self._lock:
            return self._current
