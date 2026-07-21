from __future__ import annotations

from hashlib import sha256

from slideguard.rules.models import Issue, IssueStatus, Severity


def issue(
    *,
    fact_key: str,
    rule_id: str,
    slide_index: int,
    object_keys: tuple[str, ...],
    severity: Severity,
    actual_value: str,
    expected_value: str,
    evidence: str,
    suggestion: str,
    can_auto_fix: bool = False,
) -> Issue:
    return Issue(
        issue_id=sha256(fact_key.encode("utf-8")).hexdigest()[:20],
        fact_key=fact_key,
        rule_id=rule_id,
        slide_index=slide_index,
        object_keys=object_keys,
        severity=severity,
        status=IssueStatus.PENDING,
        actual_value=actual_value,
        expected_value=expected_value,
        standard_source=f"builtin-rules-v1.0 / PRD {rule_id}",
        evidence=evidence,
        suggestion=suggestion,
        can_auto_fix=can_auto_fix,
        fix_proposal=None,
    )
