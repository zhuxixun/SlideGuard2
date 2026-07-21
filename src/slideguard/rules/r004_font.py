from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
import unicodedata

from slideguard.pptx.snapshot import PresentationSnapshot, SlideObject
from slideguard.rules.factory import issue
from slideguard.rules.models import Issue, Severity


RULE_ID = "R004"
TARGET_FONT = "Microsoft YaHei"
ACCEPTED_FONTS = frozenset({"微软雅黑", "microsoft yahei"})


@dataclass(frozen=True, slots=True)
class _BadSpan:
    start: int
    end: int
    font_name: str


def check_fonts(snapshot: PresentationSnapshot, on_page: Callable[[int, int], None] | None = None) -> tuple[Issue, ...]:
    issues: list[Issue] = []
    total = len(snapshot.slides)
    for position, slide in enumerate(snapshot.slides, 1):
        for obj in _walk(slide.objects):
            if obj.text_frame is None or not obj.text_frame.text:
                continue
            for span in _bad_spans(obj):
                fact_key = (
                    f"{RULE_ID}:{slide.slide_index}:{obj.key}:font:"
                    f"{span.start}:{span.end}:{span.font_name}"
                )
                issues.append(
                    issue(
                        fact_key=fact_key,
                        rule_id=RULE_ID,
                        slide_index=slide.slide_index,
                        object_keys=(obj.key,),
                        severity=Severity.S3,
                        actual_value=f"{span.font_name}，字符范围 [{span.start}, {span.end})",
                        expected_value=TARGET_FONT,
                        evidence="连续字符的最终生效字体不是微软雅黑。",
                        suggestion="将该字符范围的字体替换为微软雅黑，并重新检查文本溢出。",
                        can_auto_fix=True,
                        fix_kind="replace_font",
                        fix_target=TARGET_FONT,
                    )
                )
        if on_page is not None:
            on_page(position, total)
    return tuple(issues)


def _walk(objects: tuple[SlideObject, ...]):  # type: ignore[no-untyped-def]
    for obj in objects:
        yield obj
        yield from _walk(obj.children)


def _bad_spans(obj: SlideObject) -> tuple[_BadSpan, ...]:
    spans: list[_BadSpan] = []
    assert obj.text_frame is not None
    for paragraph in obj.text_frame.paragraphs:
        for run in paragraph:
            current: _BadSpan | None = None
            for local_index, character in enumerate(run.text):
                if unicodedata.category(character).startswith("C"):
                    current = _flush(spans, current)
                    continue
                font = run.east_asia_font_name if _is_east_asian(character) else run.font_name
                display_font = font or "无法解析字体"
                if _accepted(font):
                    current = _flush(spans, current)
                    continue
                start = run.start + local_index
                if current and current.end == start and current.font_name == display_font:
                    current = _BadSpan(current.start, start + 1, display_font)
                else:
                    current = _flush(spans, current)
                    current = _BadSpan(start, start + 1, display_font)
            _flush(spans, current)
    return tuple(spans)


def _flush(spans: list[_BadSpan], current: _BadSpan | None) -> None:
    if current is not None:
        spans.append(current)
    return None


def _accepted(font: str | None) -> bool:
    return font is not None and font.strip().casefold() in ACCEPTED_FONTS


def _is_east_asian(character: str) -> bool:
    code = ord(character)
    return (
        0x3400 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    )
