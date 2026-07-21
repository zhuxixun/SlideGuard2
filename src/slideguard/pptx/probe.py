from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from zipfile import BadZipFile, ZipFile

from lxml import etree


MAX_PPTX_BYTES = 200 * 1024 * 1024
REQUIRED_PARTS = frozenset({"[Content_Types].xml", "ppt/presentation.xml"})
TEXT_PART_PATTERN = re.compile(
    r"^ppt/(slides/slide\d+|slideLayouts/slideLayout\d+|"
    r"slideMasters/slideMaster\d+|notesSlides/notesSlide\d+|charts/chart\d+)\.xml$"
)
DRAWING_TEXT = "{http://schemas.openxmlformats.org/drawingml/2006/main}t"


class PptxProbeError(RuntimeError):
    """Raised when a file cannot safely be treated as a supported PPTX."""


@dataclass(frozen=True, slots=True)
class PackageTextOccurrence:
    part_uri: str
    source: str
    xml_path: str
    text: str


def probe_text(path: Path) -> tuple[PackageTextOccurrence, ...]:
    _validate_path(path)
    try:
        with ZipFile(path, "r") as package:
            names = frozenset(package.namelist())
            missing = REQUIRED_PARTS - names
            if missing:
                raise PptxProbeError(
                    f"PPTX缺少必要部件：{', '.join(sorted(missing))}"
                )
            occurrences: list[PackageTextOccurrence] = []
            for part_uri in sorted(name for name in names if TEXT_PART_PATTERN.match(name)):
                occurrences.extend(_extract_part(package, part_uri))
            return tuple(occurrences)
    except BadZipFile as exc:
        raise PptxProbeError("文件不是有效的PPTX ZIP包") from exc
    except OSError as exc:
        raise PptxProbeError(f"无法读取PPTX：{exc}") from exc


def _validate_path(path: Path) -> None:
    if path.suffix.lower() != ".pptx":
        raise PptxProbeError("仅支持.pptx文件")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PptxProbeError(f"无法读取PPTX：{exc}") from exc
    if size > MAX_PPTX_BYTES:
        raise PptxProbeError("PPTX文件大小超过200MB")


def _extract_part(package: ZipFile, part_uri: str) -> list[PackageTextOccurrence]:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        recover=False,
        huge_tree=False,
    )
    try:
        root = etree.fromstring(package.read(part_uri), parser=parser)
    except (etree.XMLSyntaxError, KeyError, OSError) as exc:
        raise PptxProbeError(f"无法解析PPTX部件：{part_uri}") from exc

    tree = root.getroottree()
    source = _source_kind(part_uri)
    return [
        PackageTextOccurrence(
            part_uri=part_uri,
            source=source,
            xml_path=tree.getpath(node),
            text=node.text or "",
        )
        for node in root.iter(DRAWING_TEXT)
        if node.text
    ]


def _source_kind(part_uri: str) -> str:
    if "/slides/" in part_uri:
        return "slide"
    if "/slideLayouts/" in part_uri:
        return "layout"
    if "/slideMasters/" in part_uri:
        return "master"
    if "/notesSlides/" in part_uri:
        return "notes"
    if "/charts/" in part_uri:
        return "chart"
    raise AssertionError(f"Unexpected text part: {part_uri}")

