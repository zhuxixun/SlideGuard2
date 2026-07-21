from __future__ import annotations
from collections.abc import Callable

from math import cos, radians, sin

from slideguard.pptx.snapshot import PresentationSnapshot, Rect, SlideObject
from slideguard.rules.factory import issue
from slideguard.rules.models import Issue, Severity


RULE_ID = "R003"


def check_off_slide_objects(snapshot: PresentationSnapshot, on_page: Callable[[int, int], None] | None = None) -> tuple[Issue, ...]:
    canvas = Rect(0, 0, snapshot.slide_width_pt, snapshot.slide_height_pt)
    issues: list[Issue] = []
    total = len(snapshot.slides)
    for position, slide in enumerate(snapshot.slides, 1):
        for obj in slide.objects:
            bounds = _rotated_bounds(obj.bounds_pt, obj.rotation)
            if not obj.visible or _intersects(bounds, canvas):
                continue
            has_text = bool(obj.text_frame and obj.text_frame.text.strip())
            severity = Severity.S2 if has_text else Severity.S3
            fact_key = f"{RULE_ID}:{slide.slide_index}:{obj.key}:outside-canvas"
            issues.append(
                issue(
                    fact_key=fact_key,
                    rule_id=RULE_ID,
                    slide_index=slide.slide_index,
                    object_keys=(obj.key,),
                    severity=severity,
                    actual_value=_format_bounds(bounds),
                    expected_value="对象可见区域与页面画布相交",
                    evidence=f"{obj.object_type} 的旋转后可见边界完全位于页面画布外。",
                    suggestion="请人工确认该对象是否为残留内容，并删除或调整位置。",
                )
            )
        if on_page is not None:
            on_page(position, total)
    return tuple(issues)


def _rotated_bounds(rect: Rect, rotation: float) -> Rect:
    angle = radians(rotation % 360)
    width = abs(rect.width * cos(angle)) + abs(rect.height * sin(angle))
    height = abs(rect.width * sin(angle)) + abs(rect.height * cos(angle))
    center_x = rect.left + rect.width / 2
    center_y = rect.top + rect.height / 2
    return Rect(center_x - width / 2, center_y - height / 2, width, height)


def _intersects(first: Rect, second: Rect) -> bool:
    return not (
        first.left + first.width <= second.left
        or first.top + first.height <= second.top
        or first.left >= second.left + second.width
        or first.top >= second.top + second.height
    )


def _format_bounds(rect: Rect) -> str:
    return f"left={rect.left:.2f}pt, top={rect.top:.2f}pt, width={rect.width:.2f}pt, height={rect.height:.2f}pt"
