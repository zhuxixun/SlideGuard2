from __future__ import annotations

from slideguard.pptx.snapshot import PresentationSnapshot, Rect, SlideObject
from slideguard.rules.factory import issue
from slideguard.rules.models import Issue, Severity


RULE_ID = "R002"
AUXILIARY_PLACEHOLDERS = ("DATE", "FOOTER", "SLIDE_NUMBER")


def check_blank_slides(snapshot: PresentationSnapshot) -> tuple[Issue, ...]:
    canvas = Rect(0, 0, snapshot.slide_width_pt, snapshot.slide_height_pt)
    issues: list[Issue] = []
    for slide in snapshot.slides:
        if slide.hidden or any(_is_subject(obj, canvas) for obj in slide.objects):
            continue
        fact_key = f"{RULE_ID}:{slide.slide_index}:subject-content"
        issues.append(
            issue(
                fact_key=fact_key,
                rule_id=RULE_ID,
                slide_index=slide.slide_index,
                object_keys=(),
                severity=Severity.S3,
                actual_value="未发现可见主体内容",
                expected_value="页面包含至少一个可见主体对象",
                evidence="排除背景、页码、Logo、页脚、不可见及画布外对象后，主体对象数为 0。",
                suggestion="请人工确认该页是否应删除或补充内容。",
            )
        )
    return tuple(issues)


def _is_subject(obj: SlideObject, canvas: Rect) -> bool:
    if not obj.visible or not obj.has_visual_style or not _intersects(obj.bounds_pt, canvas):
        return False
    if obj.placeholder_type and obj.placeholder_type.startswith(AUXILIARY_PLACEHOLDERS):
        return False
    if "logo" in obj.name.casefold():
        return False
    return True


def _intersects(first: Rect, second: Rect) -> bool:
    return not (
        first.left + first.width <= second.left
        or first.top + first.height <= second.top
        or first.left >= second.left + second.width
        or first.top >= second.top + second.height
    )
