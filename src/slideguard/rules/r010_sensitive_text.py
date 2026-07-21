from __future__ import annotations

from hashlib import sha256
from typing import Iterable

from slideguard.pptx.snapshot import PresentationSnapshot
from slideguard.rules.models import Issue, IssueStatus, Severity


RULE_ID = "R010"
STANDARD_SOURCE = "builtin-rules-v1.0 / PRD R010"


def check_sensitive_text(
    snapshot: PresentationSnapshot,
    terms: Iterable[str],
) -> tuple[Issue, ...]:
    normalized_terms = tuple(dict.fromkeys(term.strip() for term in terms if term.strip()))
    issues: list[Issue] = []
    seen_facts: set[str] = set()
    for occurrence in snapshot.text_occurrences:
        for term in normalized_terms:
            start = occurrence.text.find(term)
            while start >= 0:
                end = start + len(term)
                fact_key = (
                    f"{RULE_ID}:{occurrence.slide_index}:{occurrence.key}:"
                    f"characters:{start}:{end}:{term}"
                )
                if fact_key not in seen_facts:
                    seen_facts.add(fact_key)
                    issues.append(_issue(occurrence, term, start, end, fact_key))
                start = occurrence.text.find(term, start + 1)
    return tuple(issues)


def _issue(occurrence, term: str, start: int, end: int, fact_key: str) -> Issue:  # type: ignore[no-untyped-def]
    issue_id = sha256(fact_key.encode("utf-8")).hexdigest()[:20]
    return Issue(
        issue_id=issue_id,
        fact_key=fact_key,
        rule_id=RULE_ID,
        slide_index=occurrence.slide_index,
        object_keys=(occurrence.key,),
        severity=Severity.S1,
        status=IssueStatus.PENDING,
        actual_value=term,
        expected_value="不包含敏感或残留文本",
        standard_source=STANDARD_SOURCE,
        evidence=(
            f"在{occurrence.source.value}文本的字符范围 [{start}, {end}) "
            f"命中词条“{term}”"
        ),
        suggestion="请人工核实，并删除或改写相关文本。",
        can_auto_fix=False,
        fix_proposal=None,
    )
