from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from slideguard.pptx.probe import PackageTextOccurrence


@dataclass(frozen=True, slots=True)
class SensitiveTextMatch:
    term: str
    part_uri: str
    source: str
    xml_path: str
    start: int
    end: int


def find_sensitive_text(
    occurrences: Iterable[PackageTextOccurrence],
    terms: Iterable[str],
) -> tuple[SensitiveTextMatch, ...]:
    matches: list[SensitiveTextMatch] = []
    for occurrence in occurrences:
        for term in terms:
            start = occurrence.text.find(term)
            while start >= 0:
                matches.append(
                    SensitiveTextMatch(
                        term=term,
                        part_uri=occurrence.part_uri,
                        source=occurrence.source,
                        xml_path=occurrence.xml_path,
                        start=start,
                        end=start + len(term),
                    )
                )
                start = occurrence.text.find(term, start + 1)
    return tuple(matches)

