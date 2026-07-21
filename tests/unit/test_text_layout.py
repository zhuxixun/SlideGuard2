import pytest

from slideguard.preview.text_layout import measure_single_line


def test_microsoft_yahei_measurement_is_deterministic_and_uses_pt() -> None:
    first = measure_single_line("SlideGuard 中文", font_size_pt=24)
    second = measure_single_line("SlideGuard 中文", font_size_pt=24)

    assert first == second
    assert first.font_path.name.lower() == "msyh.ttc"
    assert first.width_pt > 0
    assert first.height_pt > 0


def test_bold_text_uses_bold_font_file() -> None:
    regular = measure_single_line("标题", font_size_pt=24)
    bold = measure_single_line("标题", font_size_pt=24, bold=True)

    assert bold.font_path.name.lower() == "msyhbd.ttc"
    assert bold.width_pt >= regular.width_pt


@pytest.mark.parametrize("font_size,dpi", [(0, 96), (-1, 96), (12, 0)])
def test_measurement_rejects_invalid_dimensions(font_size: float, dpi: int) -> None:
    with pytest.raises(ValueError):
        measure_single_line("text", font_size_pt=font_size, dpi=dpi)

