from __future__ import annotations

from math import cos, radians, sin

from slideguard.pptx.snapshot import PresentationSnapshot, Rect, SlideObject, TextFrameSnapshot
from slideguard.preview.text_flow import measure_text_flow
from slideguard.rules.factory import issue
from slideguard.rules.models import Issue, Severity


RULE_ID = "R008"
SAFE_RATIO = 0.03
AUXILIARY_TYPES = ("DATE", "FOOTER", "SLIDE_NUMBER")


def check_text_margins(snapshot: PresentationSnapshot) -> tuple[Issue, ...]:
    issues: list[Issue] = []
    safe_left = snapshot.slide_width_pt * SAFE_RATIO
    safe_top = snapshot.slide_height_pt * SAFE_RATIO
    safe_right = snapshot.slide_width_pt - safe_left
    safe_bottom = snapshot.slide_height_pt - safe_top
    for slide in snapshot.slides:
        for obj in _walk(slide.objects):
            if _auxiliary(obj):
                continue
            targets = (
                tuple((cell.key, cell.bounds_pt, cell.text_frame) for cell in obj.table_cells)
                if obj.object_type == "table"
                else ((obj.key, obj.bounds_pt, obj.text_frame),)
            )
            for key, bounds, frame in targets:
                if frame is None or not frame.text.strip():
                    continue
                visible = _visible_text_bounds(bounds, frame, obj.rotation)
                if visible is None:
                    continue
                edges = _unsafe_edges(visible, safe_left, safe_top, safe_right, safe_bottom)
                if not edges:
                    continue
                fact_key = f"{RULE_ID}:{slide.slide_index}:{key}:safe-margin"
                issues.append(
                    issue(
                        fact_key=fact_key,
                        rule_id=RULE_ID,
                        slide_index=slide.slide_index,
                        object_keys=(key,),
                        severity=Severity.S3,
                        actual_value=_format_rect(visible),
                        expected_value=(
                            f"文字边界位于安全区域 left={safe_left:.2f}pt, top={safe_top:.2f}pt, "
                            f"right={safe_right:.2f}pt, bottom={safe_bottom:.2f}pt 内"
                        ),
                        evidence=f"文字实际可见边界进入页面{','.join(edges)}侧 3% 安全边距。",
                        suggestion="请人工调整文本位置或排版，使文字离开页面安全边距。",
                    )
                )
    return tuple(issues)


def _visible_text_bounds(bounds: Rect, frame: TextFrameSnapshot, rotation: float) -> Rect | None:
    available_width = max(0.0, bounds.width - frame.margin_left_pt - frame.margin_right_pt)
    available_height = max(0.0, bounds.height - frame.margin_top_pt - frame.margin_bottom_pt)
    measured = measure_text_flow(frame, available_width)
    if not measured.reliable:
        return None
    alignment = frame.paragraphs[0].alignment if frame.paragraphs else None
    left = bounds.left + frame.margin_left_pt
    if alignment and alignment.startswith("CENTER"):
        left += (available_width - measured.width_pt) / 2
    elif alignment and alignment.startswith("RIGHT"):
        left += available_width - measured.width_pt
    top = bounds.top + frame.margin_top_pt
    anchor = frame.vertical_anchor or ""
    if anchor.startswith("MIDDLE"):
        top += (available_height - measured.height_pt) / 2
    elif anchor.startswith("BOTTOM"):
        top += available_height - measured.height_pt
    text_rect = Rect(left, top, measured.width_pt, measured.height_pt)
    return _rotate_about(text_rect, bounds, rotation)


def _rotate_about(rect: Rect, owner: Rect, rotation: float) -> Rect:
    if rotation % 360 == 0:
        return rect
    angle = radians(rotation % 360)
    center_x = owner.left + owner.width / 2
    center_y = owner.top + owner.height / 2
    points: list[tuple[float, float]] = []
    for x, y in (
        (rect.left, rect.top),
        (rect.left + rect.width, rect.top),
        (rect.left, rect.top + rect.height),
        (rect.left + rect.width, rect.top + rect.height),
    ):
        dx, dy = x - center_x, y - center_y
        points.append((center_x + dx * cos(angle) - dy * sin(angle), center_y + dx * sin(angle) + dy * cos(angle)))
    xs, ys = zip(*points)
    return Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _unsafe_edges(rect: Rect, left: float, top: float, right: float, bottom: float) -> tuple[str, ...]:
    edges: list[str] = []
    if rect.left < left:
        edges.append("左")
    if rect.top < top:
        edges.append("上")
    if rect.left + rect.width > right:
        edges.append("右")
    if rect.top + rect.height > bottom:
        edges.append("下")
    return tuple(edges)


def _walk(objects: tuple[SlideObject, ...]):  # type: ignore[no-untyped-def]
    for obj in objects:
        yield obj
        yield from _walk(obj.children)


def _auxiliary(obj: SlideObject) -> bool:
    return bool(obj.placeholder_type and obj.placeholder_type.startswith(AUXILIARY_TYPES))


def _format_rect(rect: Rect) -> str:
    return f"left={rect.left:.2f}pt, top={rect.top:.2f}pt, width={rect.width:.2f}pt, height={rect.height:.2f}pt"
