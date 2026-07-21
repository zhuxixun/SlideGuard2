from __future__ import annotations

from math import ceil
from statistics import median

from slideguard.pptx.snapshot import PresentationSnapshot, SlideObject
from slideguard.preview.text_layout import FontUnavailableError, measure_single_line
from slideguard.rules.factory import issue
from slideguard.rules.models import Issue, Severity


RULE_ID = "R009"
TARGET_FONT = "Microsoft YaHei"
TARGET_SIZE = 24.0
TARGET_COLOR = "C00000"
POSITION_TOLERANCE_PT = 3.0
OVERFLOW_TOLERANCE_PT = 2.0
ACCEPTED_FONTS = frozenset({"微软雅黑", "microsoft yahei"})


def check_titles(snapshot: PresentationSnapshot) -> tuple[Issue, ...]:
    titles = [
        (slide, obj)
        for slide in snapshot.slides
        for obj in slide.objects
        if _is_title(obj) and obj.text_frame is not None and obj.text_frame.text.strip()
    ]
    fallback = _fallback_references(titles)
    issues: list[Issue] = []
    for slide, obj in titles:
        style_actual = _style_mismatches(obj)
        if style_actual:
            issues.append(_style_issue(slide.slide_index, obj, style_actual))
        reference = slide.layout_title_left_pt
        if reference is None:
            reference = fallback.get(slide.layout_part)
        if reference is not None and abs(obj.bounds_pt.left - reference) > POSITION_TOLERANCE_PT:
            issues.append(_position_issue(slide.slide_index, obj, reference))
        overflow = _overflow_issue(slide.slide_index, obj)
        if overflow is not None:
            issues.append(overflow)
    return tuple(issues)


def _style_mismatches(obj: SlideObject) -> tuple[str, ...]:
    assert obj.text_frame is not None
    mismatches: list[str] = []
    runs = [run for paragraph in obj.text_frame.paragraphs for run in paragraph if run.text]
    if any(not _run_fonts_valid(run) for run in runs):
        mismatches.append("字体")
    if any(run.font_size_pt is None or abs(run.font_size_pt - TARGET_SIZE) > 0.01 for run in runs):
        mismatches.append("字号")
    if any(run.bold is not True for run in runs):
        mismatches.append("加粗")
    if any(run.color_rgb != TARGET_COLOR for run in runs):
        mismatches.append("颜色")
    return tuple(mismatches)


def _run_fonts_valid(run) -> bool:  # type: ignore[no-untyped-def]
    for character in run.text:
        if character.isspace():
            continue
        font = run.east_asia_font_name if _east_asian(character) else run.font_name
        if font is None or font.strip().casefold() not in ACCEPTED_FONTS:
            return False
    return True


def _style_issue(slide_index: int, obj: SlideObject, mismatches: tuple[str, ...]) -> Issue:
    fact_key = f"{RULE_ID}:{slide_index}:{obj.key}:title-style"
    return issue(
        fact_key=fact_key,
        rule_id=RULE_ID,
        slide_index=slide_index,
        object_keys=(obj.key,),
        severity=Severity.S3,
        actual_value="不符合项：" + "、".join(mismatches),
        expected_value="微软雅黑、24pt、加粗、RGB(192,0,0)",
        evidence="PowerPoint 标题占位符的全部文字必须使用统一标题样式。",
        suggestion="将标题样式统一为规定值，并重新检查文本溢出。",
        can_auto_fix=True,
        fix_kind="set_title_style",
        fix_target="font=Microsoft YaHei;size=24;bold=true;color=C00000",
    )


def _position_issue(slide_index: int, obj: SlideObject, reference: float) -> Issue:
    fact_key = f"{RULE_ID}:{slide_index}:{obj.key}:title-left"
    return issue(
        fact_key=fact_key,
        rule_id=RULE_ID,
        slide_index=slide_index,
        object_keys=(obj.key,),
        severity=Severity.S3,
        actual_value=f"left={obj.bounds_pt.left:.2f}pt",
        expected_value=f"版式或主流参考线 left={reference:.2f}pt",
        evidence=f"标题左侧与参考线偏差 {obj.bounds_pt.left - reference:+.2f}pt，超过 3pt。",
        suggestion="只调整标题占位符的横向位置，使其左侧对齐参考线。",
        can_auto_fix=True,
        fix_kind="move_x",
        fix_target=f"{reference:.2f}",
    )


def _overflow_issue(slide_index: int, obj: SlideObject) -> Issue | None:
    assert obj.text_frame is not None
    text = obj.text_frame.text
    available = obj.bounds_pt.width - obj.text_frame.margin_left_pt - obj.text_frame.margin_right_pt
    try:
        width = measure_single_line(text, font_size_pt=TARGET_SIZE, bold=True).width_pt
    except FontUnavailableError:
        return None
    if width - available <= OVERFLOW_TOLERANCE_PT:
        return None
    colon_at = min((index for index in (text.find("："), text.find(":")) if index >= 0), default=-1)
    suffix_size = _suffix_size(text, colon_at, available) if colon_at >= 0 else None
    fact_key = f"{RULE_ID}:{slide_index}:{obj.key}:title-overflow"
    if suffix_size is not None:
        return issue(
            fact_key=fact_key,
            rule_id=RULE_ID,
            slide_index=slide_index,
            object_keys=(obj.key,),
            severity=Severity.S3,
            actual_value=f"标题在 24pt 下宽度为 {width:.2f}pt，有效宽度为 {available:.2f}pt",
            expected_value=f"冒号前保持 24pt，冒号后缩小为 {suffix_size}pt 后单行不溢出",
            evidence="标题包含冒号，可在不低于 14pt 的范围内缩小冒号后文字。",
            suggestion="按建议拆分冒号后的 run，并在修复后重新检查文本溢出。",
            can_auto_fix=True,
            fix_kind="scale_title_suffix",
            fix_target=str(suffix_size),
        )
    return issue(
        fact_key=fact_key,
        rule_id=RULE_ID,
        slide_index=slide_index,
        object_keys=(obj.key,),
        severity=Severity.S3,
        actual_value=f"标题在 24pt 下宽度为 {width:.2f}pt，有效宽度为 {available:.2f}pt",
        expected_value="标题在 24pt 下单行显示，或冒号后不低于 14pt 时单行显示",
        evidence="标题没有可处理的冒号，或冒号后缩小至 14pt 仍然溢出。",
        suggestion="请人工精简标题或调整标题区域。",
    )


def _suffix_size(text: str, colon_at: int, available: float) -> int | None:
    prefix = text[: colon_at + 1]
    suffix = text[colon_at + 1 :]
    prefix_width = measure_single_line(prefix, font_size_pt=TARGET_SIZE, bold=True).width_pt
    for size in range(23, 13, -1):
        suffix_width = measure_single_line(suffix, font_size_pt=size, bold=True).width_pt
        if prefix_width + suffix_width - available <= OVERFLOW_TOLERANCE_PT:
            return size
    return None


def _fallback_references(titles) -> dict[str | None, float]:  # type: ignore[no-untyped-def]
    layouts: dict[str | None, list[float]] = {}
    for slide, obj in titles:
        if slide.layout_title_left_pt is None:
            layouts.setdefault(slide.layout_part, []).append(obj.bounds_pt.left)
    result: dict[str | None, float] = {}
    for layout, values in layouts.items():
        if len(values) < 3:
            continue
        required = ceil(len(values) * 0.70)
        clusters = [tuple(value for value in values if abs(value - seed) <= 3) for seed in values]
        members = max(clusters, key=lambda cluster: (len(cluster), -sum(abs(value - median(cluster)) for value in cluster)))
        if len(members) >= required:
            result[layout] = float(median(members))
    return result


def _is_title(obj: SlideObject) -> bool:
    return bool(obj.placeholder_type and obj.placeholder_type.startswith(("TITLE", "CENTER_TITLE")))


def _east_asian(character: str) -> bool:
    code = ord(character)
    return 0x3400 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF
