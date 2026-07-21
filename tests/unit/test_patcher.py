from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from lxml import etree

from slideguard.pptx.patcher import XmlAttributePatch, patch_pptx
from slideguard.pptx.probe import PptxProbeError


def _make_pptx(path: Path) -> None:
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as package:
        package.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        package.writestr(
            "ppt/presentation.xml",
            '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>',
        )
        package.writestr(
            "ppt/slides/slide1.xml",
            '''<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
                <a:rPr lang="zh-CN"/><a:t>测试</a:t></p:sld>''',
        )
        package.writestr("ppt/media/image1.png", b"unchanged-binary")


def test_patcher_changes_only_target_part_content(tmp_path: Path) -> None:
    source = tmp_path / "source.pptx"
    output = tmp_path / "output.pptx"
    _make_pptx(source)
    with ZipFile(source) as package:
        before_image = sha256(package.read("ppt/media/image1.png")).digest()

    patch_pptx(
        source,
        output,
        (
            XmlAttributePatch(
                part_uri="ppt/slides/slide1.xml",
                xpath="/p:sld/a:rPr",
                attributes=(("typeface", "Microsoft YaHei"),),
            ),
        ),
    )

    with ZipFile(output) as package:
        after_image = sha256(package.read("ppt/media/image1.png")).digest()
        slide = etree.fromstring(package.read("ppt/slides/slide1.xml"))
    assert before_image == after_image
    namespace = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    assert slide.xpath("string(/p:sld/a:rPr/@typeface)", namespaces={
        "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
        **namespace,
    }) == "Microsoft YaHei"


def test_patcher_refuses_overwrite_and_non_unique_target(tmp_path: Path) -> None:
    source = tmp_path / "source.pptx"
    output = tmp_path / "output.pptx"
    _make_pptx(source)
    output.write_bytes(b"existing")
    with pytest.raises(PptxProbeError, match="不允许覆盖"):
        patch_pptx(source, output, ())

    output.unlink()
    with pytest.raises(PptxProbeError, match="必须唯一匹配"):
        patch_pptx(
            source,
            output,
            (
                XmlAttributePatch(
                    "ppt/slides/slide1.xml",
                    "/p:sld/a:missing",
                    (("value", "x"),),
                ),
            ),
        )
    assert not output.exists()

