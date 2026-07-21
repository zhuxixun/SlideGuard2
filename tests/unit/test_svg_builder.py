from xml.etree import ElementTree as ET

from slideguard.preview.svg_builder import PreviewObject, build_svg


def test_svg_uses_slide_coordinates_escapes_text_and_separates_overlay() -> None:
    svg = build_svg(
        slide_width_pt=960,
        slide_height_pt=540,
        objects=(
            PreviewObject("shape-1", 10, 20, 100, 40, '<script>alert("x")</script>'),
        ),
        highlighted_ids=frozenset({"shape-1"}),
    )

    root = ET.fromstring(svg)
    assert root.attrib["viewBox"] == "0 0 960 540"
    assert "<script>" not in svg
    assert '<script>alert("x")</script>' in "".join(root.itertext())
    overlays = [
        element
        for element in root.iter()
        if element.attrib.get("data-highlight-for") == "shape-1"
    ]
    assert len(overlays) == 1

