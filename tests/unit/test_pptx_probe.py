from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from slideguard.pptx.probe import PptxProbeError, probe_text
from slideguard.rules.sensitive_text import find_sensitive_text


CONTENT_TYPES = b"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>
"""
PRESENTATION = b"""<?xml version="1.0" encoding="UTF-8"?>
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>
"""


def _write_package(path: Path, parts: dict[str, str]) -> None:
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", CONTENT_TYPES)
        package.writestr("ppt/presentation.xml", PRESENTATION)
        for name, text in parts.items():
            package.writestr(
                name,
                f'''<?xml version="1.0" encoding="UTF-8"?>
                <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
                  <p:cSld><a:t>{text}</a:t></p:cSld>
                </p:sld>''',
            )


def test_probe_extracts_all_supported_text_sources(tmp_path: Path) -> None:
    path = tmp_path / "sample.pptx"
    _write_package(
        path,
        {
            "ppt/slides/slide1.xml": "正文旧项目",
            "ppt/slideLayouts/slideLayout1.xml": "版式内部代号",
            "ppt/slideMasters/slideMaster1.xml": "母版禁用产品",
            "ppt/notesSlides/notesSlide1.xml": "备注不得外发",
            "ppt/charts/chart1.xml": "图表过期版本",
        },
    )

    occurrences = probe_text(path)

    assert {item.source for item in occurrences} == {
        "slide",
        "layout",
        "master",
        "notes",
        "chart",
    }
    assert {item.text for item in occurrences} == {
        "正文旧项目",
        "版式内部代号",
        "母版禁用产品",
        "备注不得外发",
        "图表过期版本",
    }
    assert all(item.xml_path for item in occurrences)


def test_sensitive_match_is_literal_case_sensitive_and_overlapping(tmp_path: Path) -> None:
    path = tmp_path / "sample.pptx"
    _write_package(path, {"ppt/slides/slide1.xml": "aaaa ProjectX projectx"})

    matches = find_sensitive_text(probe_text(path), ["aa", "ProjectX"])

    assert [(item.term, item.start, item.end) for item in matches] == [
        ("aa", 0, 2),
        ("aa", 1, 3),
        ("aa", 2, 4),
        ("ProjectX", 5, 13),
    ]


def test_probe_maps_related_parts_to_presentation_slide_order(tmp_path: Path) -> None:
    path = tmp_path / "related.pptx"
    presentation = b'''<?xml version="1.0" encoding="UTF-8"?>
    <p:presentation
      xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
      xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
      <p:sldIdLst><p:sldId id="256" r:id="rId9"/></p:sldIdLst>
    </p:presentation>'''
    relationships = b'''<?xml version="1.0" encoding="UTF-8"?>
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId9" Target="slides/slide7.xml"/>
    </Relationships>'''
    slide_relationships = b'''<?xml version="1.0" encoding="UTF-8"?>
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId1" Target="../slideLayouts/slideLayout3.xml"/>
      <Relationship Id="rId2" Target="../notesSlides/notesSlide4.xml"/>
      <Relationship Id="rId3" Target="../charts/chart2.xml"/>
    </Relationships>'''
    layout_relationships = b'''<?xml version="1.0" encoding="UTF-8"?>
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId1" Target="../slideMasters/slideMaster2.xml"/>
    </Relationships>'''
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", CONTENT_TYPES)
        package.writestr("ppt/presentation.xml", presentation)
        package.writestr("ppt/_rels/presentation.xml.rels", relationships)
        package.writestr("ppt/slides/_rels/slide7.xml.rels", slide_relationships)
        package.writestr(
            "ppt/slideLayouts/_rels/slideLayout3.xml.rels", layout_relationships
        )
        for part, text in {
            "ppt/slides/slide7.xml": "页面",
            "ppt/slideLayouts/slideLayout3.xml": "版式",
            "ppt/slideMasters/slideMaster2.xml": "母版",
            "ppt/notesSlides/notesSlide4.xml": "备注",
            "ppt/charts/chart2.xml": "图表",
        }.items():
            package.writestr(
                part,
                f'''<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                    xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
                    <a:t>{text}</a:t></p:sld>''',
            )

    occurrences = probe_text(path)

    assert {item.text: item.slide_indices for item in occurrences} == {
        "页面": (1,),
        "版式": (1,),
        "母版": (1,),
        "备注": (1,),
        "图表": (1,),
    }


def test_probe_rejects_non_pptx_and_missing_required_parts(tmp_path: Path) -> None:
    wrong_extension = tmp_path / "sample.zip"
    wrong_extension.write_bytes(b"not a pptx")
    with pytest.raises(PptxProbeError, match="仅支持"):
        probe_text(wrong_extension)

    incomplete = tmp_path / "incomplete.pptx"
    with ZipFile(incomplete, "w") as package:
        package.writestr("[Content_Types].xml", CONTENT_TYPES)
    with pytest.raises(PptxProbeError, match="缺少必要部件"):
        probe_text(incomplete)
