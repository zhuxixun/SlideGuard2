from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from slideguard.pptx.snapshot import FileIdentity


@dataclass(frozen=True, slots=True)
class FixOperation:
    object_key: str
    property_name: str
    original_value: str
    target_value: str
    issue_ids: tuple[str, ...]
    fact_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FixPlan:
    source_identity: FileIdentity
    rule_set_version: str
    destination: Path
    operations: tuple[FixOperation, ...]
    issue_ids: tuple[str, ...]
    selected_facts: tuple[tuple[str, str], ...]
    baseline_fact_keys: frozenset[str]
