from __future__ import annotations

from slideguard.pptx.snapshot import PresentationSnapshot, SlideObject
from slideguard.preview.text_flow import measure_text_flow
from slideguard.rules.factory import issue
from slideguard.rules.models import Issue, Severity


RULE_ID = "R006"
TOLERANCE_PT = 2.0
TITLE_TYPES = ("TITLE", "CENTER_TITLE")
AUXILIARY_TYPES = ("DATE", "FOOTER", "SLIDE_NUMBER")


def check_text_overflow(snapshot: PresentationSnapshot) -> tuple[Issue, ...]:
    issues: list[Issue] = []
    for slide in snapshot.slides:
        for obj in _walk(slide.objects):
            frame = obj.text_frame
            if frame is None or not frame.text.strip() or obj.object_type == "table":
                continue
            effective_width = max(0.0, obj.bounds_pt.width - frame.margin_left_pt - frame.margin_right_pt)
            effective_height = max(0.0, obj.bounds_pt.height - frame.margin_top_pt - frame.margin_bottom_pt)
            measurement = measure_text_flow(frame, effective_width)
            if not measurement.reliable:
                continue
            width_excess = measurement.width_pt - effective_width
            height_excess = measurement.height_pt - effective_height
            below_minimum = _below_minimum_after_autofit(obj)
            page_excess = _page_excess(snapshot, obj, measurement.width_pt, measurement.height_pt)
            if max(width_excess, height_excess, page_excess) <= TOLERANCE_PT and not below_minimum:
                continue
            critical = _is_title(obj) or page_excess > TOLERANCE_PT
            severity = Severity.S2 if critical else Severity.S3
            fact_key = f"{RULE_ID}:{slide.slide_index}:{obj.key}:text-bounds"
            issues.append(
                issue(
                    fact_key=fact_key,
                    rule_id=RULE_ID,
                    slide_index=slide.slide_index,
                    object_keys=(obj.key,),
                    severity=severity,
                    actual_value=(
                        f"排版 {measurement.width_pt:.2f}×{measurement.height_pt:.2f}pt；"
                        f"有效区域 {effective_width:.2f}×{effective_height:.2f}pt"
                    ),
                    expected_value="排版宽高及页面越界不超过 2pt，自动缩小后字号不低于最小值",
                    evidence=_evidence(width_excess, height_excess, page_excess, below_minimum),
                    suggestion="请扩大文本区域、精简文字或人工调整排版。",
                )
            )
    return tuple(issues)


def _walk(objects: tuple[SlideObject, ...]):  # type: ignore[no-untyped-def]
    for obj in objects:
        yield obj
        yield from _walk(obj.children)


def _below_minimum_after_autofit(obj: SlideObject) -> bool:
    assert obj.text_frame is not None
    if obj.text_frame.auto_fit_scale >= 1:
        return False
    minimum = 10.0 if _is_auxiliary(obj) else 14.0
    return any(
        run.font_size_pt is not None and run.font_size_pt * obj.text_frame.auto_fit_scale < minimum
        for paragraph in obj.text_frame.paragraphs
        for run in paragraph
        if run.text.strip()
    )


def _page_excess(snapshot: PresentationSnapshot, obj: SlideObject, width: float, height: float) -> float:
    assert obj.text_frame is not None
    left = obj.bounds_pt.left + obj.text_frame.margin_left_pt
    top = obj.bounds_pt.top + obj.text_frame.margin_top_pt
    return max(0.0, -left, -top, left + width - snapshot.slide_width_pt, top + height - snapshot.slide_height_pt)


def _is_title(obj: SlideObject) -> bool:
    return bool(obj.placeholder_type and obj.placeholder_type.startswith(TITLE_TYPES))


def _is_auxiliary(obj: SlideObject) -> bool:
    return bool(obj.placeholder_type and obj.placeholder_type.startswith(AUXILIARY_TYPES))


def _evidence(width: float, height: float, page: float, below_minimum: bool) -> str:
    reasons: list[str] = []
    if width > TOLERANCE_PT:
        reasons.append(f"宽度超出 {width:.2f}pt")
    if height > TOLERANCE_PT:
        reasons.append(f"高度超出 {height:.2f}pt")
    if page > TOLERANCE_PT:
        reasons.append(f"文字超出页面 {page:.2f}pt")
    if below_minimum:
        reasons.append("自动缩小后的实际字号低于该文本类型最小字号")
    return "；".join(reasons)
