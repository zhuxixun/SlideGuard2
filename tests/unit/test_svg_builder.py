from xml.etree import ElementTree as ET

from slideguard.preview.svg_builder import PreviewGuide, PreviewObject, build_svg


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


def test_svg_supports_reference_and_page_highlights() -> None:
    svg = build_svg(
        slide_width_pt=100,
        slide_height_pt=50,
        objects=(PreviewObject("target", 1, 2, 10, 10), PreviewObject("reference", 20, 2, 10, 10)),
        highlighted_ids=frozenset({"target"}),
        reference_ids=frozenset({"reference"}),
        page_highlight=True,
        guides=(PreviewGuide("y", 12),),
    )
    root = ET.fromstring(svg)
    assert len([item for item in root.iter() if item.attrib.get("data-reference-for") == "reference"]) == 1
    assert len([item for item in root.iter() if item.attrib.get("data-page-highlight") == "true"]) == 1
    assert len([item for item in root.iter() if item.attrib.get("data-reference-line") == "y"]) == 1


def test_svg_can_focus_highlighted_object_with_context() -> None:
    svg = build_svg(
        slide_width_pt=720,
        slide_height_pt=540,
        objects=(PreviewObject("small", 600, 450, 20, 10, "x"),),
        highlighted_ids=frozenset({"small"}),
        focus_highlights=True,
    )
    root = ET.fromstring(svg)
    assert root.attrib["data-focused"] == "true"
    assert root.attrib["viewBox"] != "0 0 720 540"
