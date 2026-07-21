from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"


class IssueStatus(StrEnum):
    PENDING = "pending"
    IGNORED = "ignored"
    FIXED = "fixed"
    FIX_FAILED = "fix_failed"


@dataclass(frozen=True, slots=True)
class FixProposal:
    kind: str
    target_value: str


@dataclass(frozen=True, slots=True)
class Issue:
    issue_id: str
    fact_key: str
    rule_id: str
    slide_index: int
    object_keys: tuple[str, ...]
    severity: Severity
    status: IssueStatus
    actual_value: str
    expected_value: str
    standard_source: str
    evidence: str
    suggestion: str
    can_auto_fix: bool
    fix_proposal: FixProposal | None
    introduced_by_repair: bool = False
