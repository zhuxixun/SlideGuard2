from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import posixpath
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
PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
RELATIONSHIP_DOC_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


class PptxProbeError(RuntimeError):
    """Raised when a file cannot safely be treated as a supported PPTX."""


@dataclass(frozen=True, slots=True)
class PackageTextOccurrence:
    part_uri: str
    source: str
    slide_indices: tuple[int, ...]
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
            part_slide_map = _build_part_slide_map(package)
            occurrences: list[PackageTextOccurrence] = []
            for part_uri in sorted(name for name in names if TEXT_PART_PATTERN.match(name)):
                occurrences.extend(
                    _extract_part(
                        package,
                        part_uri,
                        slide_indices=part_slide_map.get(part_uri, ()),
                    )
                )
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


def _extract_part(
    package: ZipFile,
    part_uri: str,
    *,
    slide_indices: tuple[int, ...],
) -> list[PackageTextOccurrence]:
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
            slide_indices=slide_indices,
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


def _build_part_slide_map(package: ZipFile) -> dict[str, tuple[int, ...]]:
    slide_parts = _ordered_slide_parts(package)
    mapping: dict[str, set[int]] = {}
    for slide_index, slide_part in enumerate(slide_parts, start=1):
        pending = [slide_part]
        visited: set[str] = set()
        while pending:
            part_uri = pending.pop()
            if part_uri in visited:
                continue
            visited.add(part_uri)
            if TEXT_PART_PATTERN.match(part_uri):
                mapping.setdefault(part_uri, set()).add(slide_index)
            pending.extend(_related_text_parts(package, part_uri))
    return {part: tuple(sorted(indices)) for part, indices in mapping.items()}


def _ordered_slide_parts(package: ZipFile) -> tuple[str, ...]:
    parser = _secure_parser()
    try:
        presentation = etree.fromstring(package.read("ppt/presentation.xml"), parser=parser)
    except (etree.XMLSyntaxError, KeyError):
        return ()
    relationships = _read_relationships(package, "ppt/presentation.xml")
    slide_parts: list[str] = []
    for slide_id in presentation.findall(f".//{{{PRESENTATION_NS}}}sldId"):
        relationship_id = slide_id.get(f"{{{OFFICE_REL_NS}}}id")
        if relationship_id and relationship_id in relationships:
            target = relationships[relationship_id]
            if target.startswith("ppt/slides/slide"):
                slide_parts.append(target)
    if slide_parts:
        return tuple(slide_parts)

    fallback = sorted(
        name
        for name in package.namelist()
        if re.match(r"^ppt/slides/slide\d+\.xml$", name)
    )
    return tuple(fallback)


def _related_text_parts(package: ZipFile, part_uri: str) -> tuple[str, ...]:
    return tuple(
        target
        for target in _read_relationships(package, part_uri).values()
        if TEXT_PART_PATTERN.match(target)
    )


def _read_relationships(package: ZipFile, part_uri: str) -> dict[str, str]:
    directory, filename = posixpath.split(part_uri)
    relationship_part = posixpath.join(directory, "_rels", f"{filename}.rels")
    if relationship_part not in package.namelist():
        return {}
    try:
        root = etree.fromstring(package.read(relationship_part), parser=_secure_parser())
    except etree.XMLSyntaxError as exc:
        raise PptxProbeError(f"无法解析PPTX关系部件：{relationship_part}") from exc

    relationships: dict[str, str] = {}
    for relation in root.findall(f"{{{RELATIONSHIP_DOC_NS}}}Relationship"):
        if relation.get("TargetMode") == "External":
            continue
        relation_id = relation.get("Id")
        target = relation.get("Target")
        if not relation_id or not target:
            continue
        resolved = posixpath.normpath(posixpath.join(directory, target))
        if resolved.startswith("../") or resolved.startswith("/"):
            continue
        relationships[relation_id] = resolved
    return relationships


def _secure_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        recover=False,
        huge_tree=False,
    )
