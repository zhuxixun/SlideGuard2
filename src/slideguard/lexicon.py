from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Iterable


class LexiconError(RuntimeError):
    """Raised when the local sensitive lexicon cannot be loaded or saved."""


@dataclass(frozen=True, slots=True)
class LexiconSnapshot:
    terms: tuple[str, ...]
    digest: str


def normalize_terms(terms: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_term in terms:
        term = raw_term.strip()
        if not term or term in seen:
            continue
        seen.add(term)
        normalized.append(term)
    return tuple(normalized)


class LexiconStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> LexiconSnapshot:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise LexiconError(f"无法读取敏感词库：{exc}") from exc
        terms = normalize_terms(raw.splitlines())
        return LexiconSnapshot(terms=terms, digest=_digest(terms))

    def save(self, terms: Iterable[str], *, expected_digest: str) -> LexiconSnapshot:
        current = self.load()
        if current.digest != expected_digest:
            raise LexiconError("敏感词库已被其他操作修改，请刷新后重试")

        normalized = normalize_terms(terms)
        content = "".join(f"{term}\n" for term in normalized)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=self.path.parent,
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, self.path)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise LexiconError(f"无法保存敏感词库：{exc}") from exc
        return LexiconSnapshot(terms=normalized, digest=_digest(normalized))


def _digest(terms: tuple[str, ...]) -> str:
    canonical = json.dumps(terms, ensure_ascii=False, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()

