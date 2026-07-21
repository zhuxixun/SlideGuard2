from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from slideguard.repair.executor import RepairResult, execute_and_recheck
from slideguard.repair.models import FixPlan
from slideguard.repair.planner import build_fix_plan
from slideguard.scan.models import ScanResult


@dataclass(frozen=True, slots=True)
class RepairManagerSnapshot:
    plan: FixPlan | None
    result: RepairResult | None
    executing: bool


class RepairManager:
    def __init__(self) -> None:
        self._lock = RLock()
        self._plan: FixPlan | None = None
        self._result: RepairResult | None = None
        self._executing = False

    def prepare(
        self,
        scan_result: ScanResult,
        issue_ids: tuple[str, ...],
        destination: Path,
    ) -> FixPlan:
        plan = build_fix_plan(scan_result, issue_ids, destination)
        with self._lock:
            if self._executing:
                raise RuntimeError("修复正在执行")
            self._plan = plan
            self._result = None
        return plan

    def execute(self, *, sensitive_terms: tuple[str, ...]) -> RepairResult:
        with self._lock:
            if self._executing:
                raise RuntimeError("修复正在执行")
            if self._plan is None:
                raise RuntimeError("没有待确认的修复计划")
            plan = self._plan
            self._executing = True
        try:
            result = execute_and_recheck(plan, sensitive_terms=sensitive_terms)
        finally:
            with self._lock:
                self._executing = False
        with self._lock:
            self._result = result
            self._plan = None
        return result

    def clear(self) -> None:
        with self._lock:
            if not self._executing:
                self._plan = None

    def snapshot(self) -> RepairManagerSnapshot:
        with self._lock:
            return RepairManagerSnapshot(self._plan, self._result, self._executing)
