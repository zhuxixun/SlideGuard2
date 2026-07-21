from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from threading import Event

from slideguard.pptx.importer import ImportedPresentation
from slideguard.pptx.snapshot import PresentationSnapshot, build_snapshot
from slideguard.rules.models import Issue
from slideguard.rules.r002_blank_slide import check_blank_slides
from slideguard.rules.r003_off_slide import check_off_slide_objects
from slideguard.rules.r004_font import check_fonts
from slideguard.rules.r005_font_size import check_font_sizes
from slideguard.rules.r006_text_overflow import check_text_overflow
from slideguard.rules.r007_alignment import check_alignment
from slideguard.rules.r008_text_margin import check_text_margins
from slideguard.rules.r009_title import check_titles
from slideguard.rules.r010_sensitive_text import check_sensitive_text
from slideguard.scan.models import (
    RuleFailure,
    ScanMode,
    ScanProgress,
    ScanRequest,
    ScanResult,
    ScanStage,
)


RULE_SET_VERSION = "builtin-rules-v1.0"
ALL_RULES = tuple(f"R{number:03d}" for number in range(2, 11))
QUICK_RULES = ("R002", "R003", "R004", "R006", "R009", "R010")
Rule = Callable[[PresentationSnapshot, tuple[str, ...]], tuple[Issue, ...]]
ProgressCallback = Callable[[ScanProgress], None]


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


def run_scan(
    imported: ImportedPresentation,
    request: ScanRequest,
    *,
    cancellation: CancellationToken | None = None,
    on_progress: ProgressCallback | None = None,
    rules: Mapping[str, Rule] | None = None,
    snapshot_builder: Callable[[ImportedPresentation], PresentationSnapshot] = build_snapshot,
    unavailable_rules: Mapping[str, str] | None = None,
) -> ScanResult:
    cancellation = cancellation or CancellationToken()
    progress = on_progress or (lambda _: None)
    selected = select_rules(request)
    issues: list[Issue] = []
    completed: list[str] = []
    failures: list[RuleFailure] = []

    def page_progress(rule_id: str, current_page: int, total_pages: int) -> None:
        progress(
            _checking_progress(
                completed, selected, issues, rule_id,
                current_page=current_page, total_pages=total_pages,
            )
        )

    registry = dict(rules or _default_rules(page_progress))
    unavailable_rules = dict(unavailable_rules or {})
    missing = tuple(rule_id for rule_id in selected if rule_id not in registry)
    if missing:
        raise ValueError(f"未知检查规则：{', '.join(missing)}")
    terms = tuple(request.sensitive_terms)
    started = datetime.now(timezone.utc)
    progress(ScanProgress(ScanStage.PARSING, 0, len(selected)))
    snapshot = snapshot_builder(imported)
    progress(ScanProgress(ScanStage.PREVIEW, 0, len(selected)))

    for rule_id in selected:
        if cancellation.cancelled:
            break
        progress(_checking_progress(completed, selected, issues, rule_id))
        if rule_id in unavailable_rules:
            failures.append(RuleFailure(rule_id, unavailable_rules[rule_id]))
            progress(_checking_progress(completed, selected, issues, None))
            continue
        try:
            issues.extend(registry[rule_id](snapshot, terms))
        except Exception as exc:  # a rule failure must not abort sibling rules
            failures.append(RuleFailure(rule_id, str(exc) or type(exc).__name__))
        else:
            completed.append(rule_id)
        progress(_checking_progress(completed, selected, issues, None))
    progress(ScanProgress(ScanStage.SUMMARIZING, len(completed), len(selected)))
    unique_issues = _deduplicate_and_sort(issues)
    cancelled = cancellation.cancelled
    return ScanResult(
        mode=request.mode,
        rule_set_version=RULE_SET_VERSION,
        snapshot=snapshot,
        requested_rules=selected,
        completed_rules=tuple(completed),
        failures=tuple(failures),
        issues=unique_issues,
        complete=not cancelled and not failures and len(completed) == len(selected),
        cancelled=cancelled,
        started_at=started,
        finished_at=datetime.now(timezone.utc),
    )


def select_rules(request: ScanRequest) -> tuple[str, ...]:
    if request.mode is ScanMode.QUICK:
        return QUICK_RULES
    if request.mode is ScanMode.STANDARD:
        return ALL_RULES
    selected = tuple(dict.fromkeys(request.selected_rules))
    if not selected:
        raise ValueError("自定义检查至少选择一条规则")
    return tuple(rule_id for rule_id in ALL_RULES if rule_id in selected) + tuple(
        rule_id for rule_id in selected if rule_id not in ALL_RULES
    )


def _default_rules(on_page: Callable[[str, int, int], None]) -> Mapping[str, Rule]:
    return {
        "R002": lambda snapshot, _: check_blank_slides(snapshot, lambda page, total: on_page("R002", page, total)),
        "R003": lambda snapshot, _: check_off_slide_objects(snapshot, lambda page, total: on_page("R003", page, total)),
        "R004": lambda snapshot, _: check_fonts(snapshot, lambda page, total: on_page("R004", page, total)),
        "R005": lambda snapshot, _: check_font_sizes(snapshot),
        "R006": lambda snapshot, _: check_text_overflow(snapshot, lambda page, total: on_page("R006", page, total)),
        "R007": lambda snapshot, _: check_alignment(snapshot),
        "R008": lambda snapshot, _: check_text_margins(snapshot, lambda page, total: on_page("R008", page, total)),
        "R009": lambda snapshot, _: check_titles(snapshot),
        "R010": lambda snapshot, terms: check_sensitive_text(snapshot, terms),
    }


def _deduplicate_and_sort(issues: list[Issue]) -> tuple[Issue, ...]:
    unique = {found.fact_key: found for found in issues}
    severity_order = {"S1": 0, "S2": 1, "S3": 2, "S4": 3}
    return tuple(
        sorted(
            unique.values(),
            key=lambda found: (
                severity_order[found.severity.value],
                found.slide_index,
                found.rule_id,
                found.issue_id,
            ),
        )
    )


def _checking_progress(
    completed: list[str],
    selected: tuple[str, ...],
    issues: list[Issue],
    current_rule: str | None,
    *,
    current_page: int | None = None,
    total_pages: int | None = None,
) -> ScanProgress:
    unique_issues = _deduplicate_and_sort(issues)
    counts = tuple(
        sum(found.severity.value == level for found in unique_issues)
        for level in ("S1", "S2", "S3", "S4")
    )
    return ScanProgress(
        ScanStage.CHECKING,
        len(completed),
        len(selected),
        current_rule,
        tuple(completed),
        counts,  # type: ignore[arg-type]
        current_page,
        total_pages,
    )
