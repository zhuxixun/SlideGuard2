from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from slideguard.pptx.snapshot import PresentationSnapshot, SlideObject, TextRunSnapshot
from slideguard.rules.factory import issue
from slideguard.rules.models import Issue, Severity


RULE_ID = "R005"
TITLE_TYPES = ("TITLE", "CENTER_TITLE")
AUXILIARY_TYPES = ("DATE", "FOOTER", "SLIDE_NUMBER")


@dataclass(frozen=True, slots=True)
class _Sample:
    slide_index: int
    layout_part: str | None
    obj: SlideObject
    run: TextRunSnapshot
    size: float
    category: str
    consistency_eligible: bool


def check_font_sizes(snapshot: PresentationSnapshot) -> tuple[Issue, ...]:
    samples = tuple(_samples(snapshot))
    issues = list(_minimum_size_issues(samples))
    issues.extend(_consistency_issues(samples))
    return tuple(issues)


def _samples(snapshot: PresentationSnapshot):  # type: ignore[no-untyped-def]
    for slide in snapshot.slides:
        for obj in _walk(slide.objects):
            category = _category(obj)
            if category == "title" or obj.text_frame is None:
                continue
            runs = [
                run
                for paragraph in obj.text_frame.paragraphs
                for run in paragraph
                if run.text.strip() and run.font_size_pt is not None
            ]
            uniform = len({round(run.font_size_pt, 2) for run in runs}) <= 1
            for run in runs:
                yield _Sample(
                    slide.slide_index,
                    slide.layout_part,
                    obj,
                    run,
                    run.font_size_pt,
                    category,
                    uniform,
                )


def _minimum_size_issues(samples: tuple[_Sample, ...]):
    for sample in samples:
        minimum = 10.0 if sample.category == "auxiliary" else 14.0
        if sample.size >= minimum:
            continue
        fact_key = (
            f"{RULE_ID}:{sample.slide_index}:{sample.obj.key}:minimum-size:"
            f"{sample.run.start}:{sample.run.end}"
        )
        yield issue(
            fact_key=fact_key,
            rule_id=RULE_ID,
            slide_index=sample.slide_index,
            object_keys=(sample.obj.key,),
            severity=Severity.S3,
            actual_value=f"{sample.size:g}pt",
            expected_value=f"不小于 {minimum:g}pt",
            evidence=f"该{_category_label(sample.category)}字号低于固定最小字号。",
            suggestion=f"将字号调整为不小于 {minimum:g}pt，并重新检查文本溢出。",
            can_auto_fix=True,
            fix_kind="replace_font_size",
            fix_target=f"{minimum:g}",
        )


def _consistency_issues(samples: tuple[_Sample, ...]):
    groups: dict[tuple[str | None, str, int], list[_Sample]] = defaultdict(list)
    for sample in samples:
        if not sample.consistency_eligible:
            continue
        group_type = sample.obj.placeholder_type or sample.obj.object_type
        groups[(sample.layout_part, group_type, sample.run.paragraph_level)].append(sample)
    for group_samples in groups.values():
        if len(group_samples) < 3:
            continue
        counts = Counter(round(sample.size, 2) for sample in group_samples)
        main_size, support = counts.most_common(1)[0]
        if support / len(group_samples) < 0.70:
            continue
        for sample in group_samples:
            if abs(sample.size - main_size) <= 2:
                continue
            fact_key = (
                f"{RULE_ID}:{sample.slide_index}:{sample.obj.key}:mainstream-size:"
                f"{sample.run.start}:{sample.run.end}:{main_size:g}"
            )
            yield issue(
                fact_key=fact_key,
                rule_id=RULE_ID,
                slide_index=sample.slide_index,
                object_keys=(sample.obj.key,),
                severity=Severity.S3,
                actual_value=f"{sample.size:g}pt",
                expected_value=f"同类文本主流字号 {main_size:g}pt",
                evidence=f"同组 {len(group_samples)} 个样本中有 {support} 个使用 {main_size:g}pt，目标偏差超过 2pt。",
                suggestion="请确认是否为局部强调；如不是，可统一为主流字号并重新检查文本溢出。",
                can_auto_fix=True,
                fix_kind="replace_font_size",
                fix_target=f"{main_size:g}",
            )


def _walk(objects: tuple[SlideObject, ...]):  # type: ignore[no-untyped-def]
    for obj in objects:
        yield obj
        yield from _walk(obj.children)


def _category(obj: SlideObject) -> str:
    placeholder = obj.placeholder_type or ""
    if placeholder.startswith(TITLE_TYPES):
        return "title"
    if placeholder.startswith(AUXILIARY_TYPES) or obj.object_type == "table":
        return "auxiliary"
    return "body"


def _category_label(category: str) -> str:
    return "辅助文字" if category == "auxiliary" else "正文或列表正文"
