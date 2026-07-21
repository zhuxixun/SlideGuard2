from __future__ import annotations

from dataclasses import dataclass

from slideguard.pptx.snapshot import TextFrameSnapshot
from slideguard.preview.text_layout import FontUnavailableError, measure_single_line


ACCEPTED_FONT_NAMES = frozenset({"微软雅黑", "microsoft yahei"})


@dataclass(frozen=True, slots=True)
class TextFlowMeasurement:
    width_pt: float
    height_pt: float
    reliable: bool
    unavailable_fonts: tuple[str, ...]


def measure_text_flow(frame: TextFrameSnapshot, available_width_pt: float) -> TextFlowMeasurement:
    unavailable: set[str] = set()
    max_width = 0.0
    total_height = 0.0
    wrap = frame.word_wrap is not False
    scale = frame.auto_fit_scale
    for paragraph in frame.paragraphs:
        line_width = 0.0
        line_height = 0.0
        paragraph_width = 0.0
        paragraph_height = paragraph.space_before_pt
        for run in paragraph:
            if run.font_size_pt is None:
                unavailable.add("无法解析字号")
                continue
            size = run.font_size_pt * scale
            for character in run.text:
                font = run.east_asia_font_name if _is_east_asian(character) else run.font_name
                if font is None or font.strip().casefold() not in ACCEPTED_FONT_NAMES:
                    unavailable.add(font or "无法解析字体")
                    continue
                try:
                    measured = measure_single_line(
                        character,
                        font_size_pt=size,
                        bold=bool(run.bold),
                    )
                except FontUnavailableError:
                    unavailable.add(font)
                    continue
                char_width = measured.width_pt
                char_height = max(measured.height_pt, size * 1.2)
                if wrap and line_width > 0 and line_width + char_width > available_width_pt:
                    paragraph_width = max(paragraph_width, line_width)
                    paragraph_height += _line_height(line_height, paragraph)
                    line_width = 0.0
                    line_height = 0.0
                line_width += char_width
                line_height = max(line_height, char_height)
        paragraph_width = max(paragraph_width, line_width)
        paragraph_height += _line_height(line_height, paragraph)
        paragraph_height += paragraph.space_after_pt
        max_width = max(max_width, paragraph_width)
        total_height += paragraph_height
    if frame.vertical:
        max_width, total_height = total_height, max_width
    return TextFlowMeasurement(
        width_pt=max_width,
        height_pt=total_height,
        reliable=not unavailable,
        unavailable_fonts=tuple(sorted(unavailable)),
    )


def _is_east_asian(character: str) -> bool:
    code = ord(character)
    return 0x3400 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF


def _line_height(natural_height: float, paragraph) -> float:  # type: ignore[no-untyped-def]
    if natural_height <= 0:
        return 0
    if paragraph.line_spacing_pt is not None:
        return paragraph.line_spacing_pt
    if paragraph.line_spacing_multiplier is not None:
        return natural_height * paragraph.line_spacing_multiplier
    return natural_height
