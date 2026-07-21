from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import ImageFont


DEFAULT_DPI = 96
MICROSOFT_YAHEI_REGULAR = Path("C:/Windows/Fonts/msyh.ttc")
MICROSOFT_YAHEI_BOLD = Path("C:/Windows/Fonts/msyhbd.ttc")


class FontUnavailableError(RuntimeError):
    """Raised when the required Microsoft YaHei font cannot be loaded."""


@dataclass(frozen=True, slots=True)
class TextMeasurement:
    width_pt: float
    height_pt: float
    font_path: Path
    font_size_pt: float
    dpi: int


def measure_single_line(
    text: str,
    *,
    font_size_pt: float,
    bold: bool = False,
    dpi: int = DEFAULT_DPI,
) -> TextMeasurement:
    if font_size_pt <= 0:
        raise ValueError("font_size_pt must be positive")
    if dpi <= 0:
        raise ValueError("dpi must be positive")
    font_path = MICROSOFT_YAHEI_BOLD if bold else MICROSOFT_YAHEI_REGULAR
    if not font_path.is_file():
        raise FontUnavailableError(f"缺少微软雅黑字体文件：{font_path}")
    pixel_size = max(1, round(font_size_pt * dpi / 72))
    try:
        font = ImageFont.truetype(str(font_path), size=pixel_size)
    except OSError as exc:
        raise FontUnavailableError(f"无法加载微软雅黑字体：{font_path}") from exc
    left, top, right, bottom = font.getbbox(text)
    width_px = max(float(font.getlength(text)), float(right - left))
    height_px = float(bottom - top)
    return TextMeasurement(
        width_pt=width_px * 72 / dpi,
        height_pt=height_px * 72 / dpi,
        font_path=font_path,
        font_size_pt=font_size_pt,
        dpi=dpi,
    )

