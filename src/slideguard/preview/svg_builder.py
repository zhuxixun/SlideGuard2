from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET


SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


@dataclass(frozen=True, slots=True)
class PreviewObject:
    object_id: str
    x: float
    y: float
    width: float
    height: float
    text: str = ""


@dataclass(frozen=True, slots=True)
class PreviewGuide:
    axis: str
    value: float


def build_svg(
    *,
    slide_width_pt: float,
    slide_height_pt: float,
    objects: tuple[PreviewObject, ...],
    highlighted_ids: frozenset[str] = frozenset(),
    reference_ids: frozenset[str] = frozenset(),
    page_highlight: bool = False,
    guides: tuple[PreviewGuide, ...] = (),
) -> str:
    root = ET.Element(
        f"{{{SVG_NS}}}svg",
        {
            "viewBox": f"0 0 {_number(slide_width_pt)} {_number(slide_height_pt)}",
            "role": "img",
        },
    )
    ET.SubElement(
        root,
        f"{{{SVG_NS}}}rect",
        {
            "x": "0",
            "y": "0",
            "width": _number(slide_width_pt),
            "height": _number(slide_height_pt),
            "fill": "#ffffff",
        },
    )
    content = ET.SubElement(root, f"{{{SVG_NS}}}g", {"data-layer": "content"})
    overlay = ET.SubElement(root, f"{{{SVG_NS}}}g", {"data-layer": "overlay"})
    for item in objects:
        attributes = {
            "x": _number(item.x),
            "y": _number(item.y),
            "width": _number(item.width),
            "height": _number(item.height),
            "fill": "none",
            "stroke": "#808080",
            "data-object-id": item.object_id,
        }
        ET.SubElement(content, f"{{{SVG_NS}}}rect", attributes)
        if item.text:
            text = ET.SubElement(
                content,
                f"{{{SVG_NS}}}text",
                {
                    "x": _number(item.x),
                    "y": _number(item.y + 12),
                    "font-family": "Microsoft YaHei",
                    "font-size": "10",
                },
            )
            text.text = item.text
        if item.object_id in highlighted_ids:
            ET.SubElement(
                overlay,
                f"{{{SVG_NS}}}rect",
                {
                    **attributes,
                    "fill": "none",
                    "stroke": "#d00000",
                    "stroke-width": "2",
                    "data-highlight-for": item.object_id,
                },
            )
        if item.object_id in reference_ids:
            ET.SubElement(
                overlay,
                f"{{{SVG_NS}}}rect",
                {
                    **attributes,
                    "fill": "none",
                    "stroke": "#006dcc",
                    "stroke-width": "2",
                    "data-reference-for": item.object_id,
                },
            )
    if page_highlight:
        ET.SubElement(
            overlay,
            f"{{{SVG_NS}}}rect",
            {
                "x": "1",
                "y": "1",
                "width": _number(max(0, slide_width_pt - 2)),
                "height": _number(max(0, slide_height_pt - 2)),
                "fill": "none",
                "stroke": "#d00000",
                "stroke-width": "2",
                "data-page-highlight": "true",
            },
        )
    for guide in guides:
        attributes = {
            "stroke": "#006dcc",
            "stroke-width": "1.5",
            "stroke-dasharray": "5 3",
            "data-reference-line": guide.axis,
        }
        if guide.axis == "x":
            attributes.update({"x1": _number(guide.value), "y1": "0", "x2": _number(guide.value), "y2": _number(slide_height_pt)})
        else:
            attributes.update({"x1": "0", "y1": _number(guide.value), "x2": _number(slide_width_pt), "y2": _number(guide.value)})
        ET.SubElement(overlay, f"{{{SVG_NS}}}line", attributes)
    return ET.tostring(root, encoding="unicode", xml_declaration=False)


def _number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")
