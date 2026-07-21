from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from slideguard.pptx.snapshot import PresentationSnapshot
from slideguard.rules.models import Issue


class ScanMode(StrEnum):
    QUICK = "quick"
    STANDARD = "standard"
    CUSTOM = "custom"


class ScanStage(StrEnum):
    PARSING = "parsing"
    PREVIEW = "preview"
    CHECKING = "checking"
    SUMMARIZING = "summarizing"


@dataclass(frozen=True, slots=True)
class ScanRequest:
    mode: ScanMode
    selected_rules: tuple[str, ...] = ()
    sensitive_terms: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScanProgress:
    stage: ScanStage
    completed_rules: int
    total_rules: int
    current_rule: str | None = None


@dataclass(frozen=True, slots=True)
class RuleFailure:
    rule_id: str
    message: str


@dataclass(frozen=True, slots=True)
class ScanResult:
    mode: ScanMode
    rule_set_version: str
    snapshot: PresentationSnapshot
    requested_rules: tuple[str, ...]
    completed_rules: tuple[str, ...]
    failures: tuple[RuleFailure, ...]
    issues: tuple[Issue, ...]
    complete: bool
    cancelled: bool
    started_at: datetime
    finished_at: datetime
