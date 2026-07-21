from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from statistics import median

from slideguard.pptx.snapshot import PresentationSnapshot, SlideObject
from slideguard.rules.factory import issue
from slideguard.rules.models import Issue, Severity


RULE_ID = "R007"
SIZE_TOLERANCE_RATIO = 0.10
ALIGNMENT_TOLERANCE_PT = 3.0
MIN_SUPPORT_RATIO = 0.70


@dataclass(frozen=True, slots=True)
class _Reference:
    feature: str
    value: float
    support: int
    total_error: float


def check_alignment(snapshot: PresentationSnapshot) -> tuple[Issue, ...]:
    issues: list[Issue] = []
    for slide in snapshot.slides:
        objects = tuple(obj for obj in slide.objects if obj.visible and obj.object_type != "group")
        for group in _candidate_groups(objects):
            orientation = _orientation(group)
            if orientation is None:
                continue
            features = ("top", "bottom", "vcenter") if orientation == "horizontal" else ("left", "right", "hcenter")
            reference = _best_reference(group, features)
            if reference is None:
                continue
            for obj in group:
                actual = _feature_value(obj, reference.feature)
                delta = actual - reference.value
                if abs(delta) <= ALIGNMENT_TOLERANCE_PT:
                    continue
                target_axis, target_position = _target_position(obj, reference)
                fact_key = f"{RULE_ID}:{slide.slide_index}:{obj.key}:alignment:{reference.feature}"
                issues.append(
                    issue(
                        fact_key=fact_key,
                        rule_id=RULE_ID,
                        slide_index=slide.slide_index,
                        object_keys=(
                            obj.key,
                            *tuple(
                                candidate.key
                                for candidate in group
                                if candidate.key != obj.key
                                and abs(_feature_value(candidate, reference.feature) - reference.value)
                                <= ALIGNMENT_TOLERANCE_PT
                            ),
                        ),
                        severity=Severity.S3,
                        actual_value=f"{reference.feature}={actual:.2f}pt，偏差 {delta:+.2f}pt",
                        expected_value=f"{reference.feature}={reference.value:.2f}pt",
                        evidence=(
                            f"同组 {len(group)} 个对象中有 {reference.support} 个形成参考线，"
                            f"当前对象偏差超过 3pt。"
                        ),
                        suggestion=f"仅将对象 {target_axis} 坐标调整为 {target_position:.2f}pt。",
                        can_auto_fix=True,
                        fix_kind=f"move_{target_axis}",
                        fix_target=f"{target_position:.2f}",
                    )
                )
    return tuple(_deduplicate(issues))


def _candidate_groups(objects: tuple[SlideObject, ...]) -> tuple[tuple[SlideObject, ...], ...]:
    remaining = list(objects)
    groups: list[tuple[SlideObject, ...]] = []
    while remaining:
        seed = remaining.pop(0)
        group = [seed]
        kept: list[SlideObject] = []
        for candidate in remaining:
            if candidate.object_type == seed.object_type and _similar_size(seed, candidate):
                group.append(candidate)
            else:
                kept.append(candidate)
        remaining = kept
        if len(group) >= 3:
            groups.append(tuple(group))
    return tuple(groups)


def _similar_size(first: SlideObject, second: SlideObject) -> bool:
    width_base = max(first.bounds_pt.width, second.bounds_pt.width, 0.01)
    height_base = max(first.bounds_pt.height, second.bounds_pt.height, 0.01)
    return (
        abs(first.bounds_pt.width - second.bounds_pt.width) / width_base <= SIZE_TOLERANCE_RATIO
        and abs(first.bounds_pt.height - second.bounds_pt.height) / height_base <= SIZE_TOLERANCE_RATIO
    )


def _orientation(group: tuple[SlideObject, ...]) -> str | None:
    centers_x = [_feature_value(obj, "hcenter") for obj in group]
    centers_y = [_feature_value(obj, "vcenter") for obj in group]
    spread_x = max(centers_x) - min(centers_x)
    spread_y = max(centers_y) - min(centers_y)
    if spread_x > max(1.0, spread_y * 2):
        return "horizontal"
    if spread_y > max(1.0, spread_x * 2):
        return "vertical"
    return None


def _best_reference(group: tuple[SlideObject, ...], features: tuple[str, ...]) -> _Reference | None:
    required = ceil(len(group) * MIN_SUPPORT_RATIO)
    candidates: list[_Reference] = []
    for feature in features:
        values = [_feature_value(obj, feature) for obj in group]
        for seed in values:
            members = [value for value in values if abs(value - seed) <= ALIGNMENT_TOLERANCE_PT]
            if len(members) < required:
                continue
            target = float(median(members))
            members = [value for value in values if abs(value - target) <= ALIGNMENT_TOLERANCE_PT]
            if len(members) >= required:
                candidates.append(
                    _Reference(feature, target, len(members), sum(abs(value - target) for value in members))
                )
    if not candidates:
        return None
    return min(candidates, key=lambda item: (-item.support, item.total_error, features.index(item.feature), item.value))


def _feature_value(obj: SlideObject, feature: str) -> float:
    rect = obj.bounds_pt
    return {
        "left": rect.left,
        "right": rect.left + rect.width,
        "hcenter": rect.left + rect.width / 2,
        "top": rect.top,
        "bottom": rect.top + rect.height,
        "vcenter": rect.top + rect.height / 2,
    }[feature]


def _target_position(obj: SlideObject, reference: _Reference) -> tuple[str, float]:
    if reference.feature == "left":
        return "x", reference.value
    if reference.feature == "right":
        return "x", reference.value - obj.bounds_pt.width
    if reference.feature == "hcenter":
        return "x", reference.value - obj.bounds_pt.width / 2
    if reference.feature == "top":
        return "y", reference.value
    if reference.feature == "bottom":
        return "y", reference.value - obj.bounds_pt.height
    return "y", reference.value - obj.bounds_pt.height / 2


def _deduplicate(issues: list[Issue]):  # type: ignore[no-untyped-def]
    seen: set[tuple[int, str]] = set()
    for found in issues:
        key = (found.slide_index, found.object_keys[0])
        if key not in seen:
            seen.add(key)
            yield found
