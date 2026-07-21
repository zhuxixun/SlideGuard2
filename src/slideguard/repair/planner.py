from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from slideguard.repair.models import FixOperation, FixPlan
from slideguard.scan.models import ScanMode, ScanResult
from slideguard.rules.models import IssueStatus


PROPERTY_ORDER = {
    "replace_font": 0,
    "replace_font_size": 1,
    "set_title_style": 2,
    "scale_title_suffix": 3,
    "move_x": 4,
    "move_y": 4,
}


class FixPlanError(RuntimeError):
    pass


def build_fix_plan(
    result: ScanResult,
    selected_issue_ids: tuple[str, ...],
    destination: Path,
) -> FixPlan:
    if result.mode is not ScanMode.STANDARD or not result.complete:
        raise FixPlanError("只有完整完成的标准检查结果可以自动修复")
    selected_ids = tuple(dict.fromkeys(selected_issue_ids))
    if not selected_ids:
        raise FixPlanError("至少选择一个可自动修复的问题")
    issues = {found.issue_id: found for found in result.issues}
    missing = tuple(issue_id for issue_id in selected_ids if issue_id not in issues)
    if missing:
        raise FixPlanError("选中的问题不属于当前扫描结果")
    source = result.snapshot.file_identity.path.resolve()
    destination = destination.resolve()
    if source == destination:
        raise FixPlanError("修复结果必须保存为新文件")
    if destination.exists():
        raise FixPlanError("目标文件已存在，不允许覆盖")
    if destination.suffix.lower() != ".pptx":
        raise FixPlanError("修复结果必须使用 .pptx 扩展名")

    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for issue_id in selected_ids:
        found = issues[issue_id]
        if found.status is not IssueStatus.PENDING:
            raise FixPlanError(f"问题 {issue_id} 不是待处理状态")
        if not found.can_auto_fix or found.fix_proposal is None:
            raise FixPlanError(f"问题 {issue_id} 不支持自动修复")
        if not found.object_keys:
            raise FixPlanError(f"问题 {issue_id} 缺少唯一修复对象")
        if found.fix_proposal.kind not in PROPERTY_ORDER:
            raise FixPlanError(f"问题 {issue_id} 的修复类型不受支持")
        grouped[(found.object_keys[0], found.fix_proposal.kind)].append(found)

    operations: list[FixOperation] = []
    for (object_key, property_name), found_issues in grouped.items():
        targets = {found.fix_proposal.target_value for found in found_issues}
        if len(targets) != 1:
            raise FixPlanError(f"对象 {object_key} 的 {property_name} 存在冲突目标")
        operations.append(
            FixOperation(
                object_key=object_key,
                property_name=property_name,
                original_value="；".join(found.actual_value for found in found_issues),
                target_value=targets.pop(),
                issue_ids=tuple(found.issue_id for found in found_issues),
                fact_keys=tuple(found.fact_key for found in found_issues),
            )
        )
    operations.sort(
        key=lambda operation: (
            PROPERTY_ORDER[operation.property_name],
            operation.object_key,
            operation.property_name,
        )
    )
    return FixPlan(
        source_identity=result.snapshot.file_identity,
        rule_set_version=result.rule_set_version,
        destination=destination,
        operations=tuple(operations),
        issue_ids=selected_ids,
        selected_facts=tuple((issue_id, issues[issue_id].fact_key) for issue_id in selected_ids),
        baseline_fact_keys=frozenset(found.fact_key for found in result.issues),
    )


def validate_plan_source(plan: FixPlan) -> None:
    source = plan.source_identity.path
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise FixPlanError("原文件已无法读取") from exc
    if size != plan.source_identity.size_bytes:
        raise FixPlanError("原文件在扫描后发生变化，请重新扫描")
    digest = sha256()
    try:
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise FixPlanError("原文件已无法读取") from exc
    if digest.hexdigest() != plan.source_identity.sha256:
        raise FixPlanError("原文件在扫描后发生变化，请重新扫描")
    if plan.destination.exists():
        raise FixPlanError("目标文件已存在，不允许覆盖")


def select_fix_operations(plan: FixPlan, indexes: tuple[int, ...]) -> FixPlan:
    selected_indexes = tuple(dict.fromkeys(indexes))
    if not selected_indexes:
        raise FixPlanError("至少保留一个修复项")
    if any(index < 0 or index >= len(plan.operations) for index in selected_indexes):
        raise FixPlanError("修复项不属于当前修复计划")
    operations = tuple(plan.operations[index] for index in selected_indexes)
    issue_ids = tuple(dict.fromkeys(
        issue_id for operation in operations for issue_id in operation.issue_ids
    ))
    selected = frozenset(issue_ids)
    return replace(
        plan,
        operations=operations,
        issue_ids=issue_ids,
        selected_facts=tuple(item for item in plan.selected_facts if item[0] in selected),
    )
