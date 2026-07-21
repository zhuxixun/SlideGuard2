from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from slideguard.pptx.importer import ImportedPresentation
from slideguard.pptx.probe import probe_text


EMU_PER_POINT = 12_700


class ParseStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class TextSource(StrEnum):
    SLIDE = "slide"
    LAYOUT = "layout"
    MASTER = "master"
    NOTES = "notes"
    CHART = "chart"


@dataclass(frozen=True, slots=True)
class FileIdentity:
    path: Path
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class Rect:
    left: float
    top: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class CharacterLocation:
    part_uri: str
    xml_path: str
    offset: int


@dataclass(frozen=True, slots=True)
class TextRunSnapshot:
    text: str
    font_name: str | None
    east_asia_font_name: str | None
    font_size_pt: float | None
    bold: bool | None
    italic: bool | None
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ThemeFonts:
    major_latin: str | None
    major_east_asia: str | None
    minor_latin: str | None
    minor_east_asia: str | None


@dataclass(frozen=True, slots=True)
class TextFrameSnapshot:
    text: str
    paragraphs: tuple[tuple[TextRunSnapshot, ...], ...]


@dataclass(frozen=True, slots=True)
class SlideObject:
    key: str
    name: str
    object_type: str
    bounds_pt: Rect
    rotation: float
    visible: bool
    has_visual_style: bool
    from_master: bool
    placeholder_type: str | None
    text_frame: TextFrameSnapshot | None
    children: tuple["SlideObject", ...]


@dataclass(frozen=True, slots=True)
class SlideSnapshot:
    slide_index: int
    slide_part: str
    layout_part: str | None
    hidden: bool
    objects: tuple[SlideObject, ...]
    parse_status: ParseStatus


@dataclass(frozen=True, slots=True)
class TextOccurrence:
    key: str
    slide_index: int
    source: TextSource
    text: str
    visible: bool
    character_map: tuple[CharacterLocation, ...]


@dataclass(frozen=True, slots=True)
class UnsupportedObject:
    slide_index: int
    key: str
    object_type: str


@dataclass(frozen=True, slots=True)
class PresentationSnapshot:
    file_identity: FileIdentity
    slide_width_pt: float
    slide_height_pt: float
    slides: tuple[SlideSnapshot, ...]
    text_occurrences: tuple[TextOccurrence, ...]
    unsupported_objects: tuple[UnsupportedObject, ...]


def build_snapshot(imported: ImportedPresentation) -> PresentationSnapshot:
    document = Presentation(imported.path)
    theme_fonts = _read_theme_fonts(imported.path)
    slides: list[SlideSnapshot] = []
    unsupported: list[UnsupportedObject] = []
    slide_ids = tuple(document.slides._sldIdLst)  # noqa: SLF001
    for index, slide in enumerate(document.slides, start=1):
        part_uri = str(slide.part.partname).lstrip("/")
        objects = tuple(
            _shape_snapshot(shape, part_uri, index, unsupported, theme_fonts)
            for shape in slide.shapes
        )
        slides.append(
            SlideSnapshot(
                slide_index=index,
                slide_part=part_uri,
                layout_part=str(slide.slide_layout.part.partname).lstrip("/"),
                hidden=_slide_hidden(slide_ids[index - 1]),
                objects=objects,
                parse_status=ParseStatus.COMPLETE,
            )
        )

    occurrences = tuple(
        occurrence
        for item in probe_text(imported.path)
        for occurrence in _text_occurrences(item)
    )
    return PresentationSnapshot(
        file_identity=FileIdentity(imported.path, imported.size_bytes, imported.digest),
        slide_width_pt=document.slide_width / EMU_PER_POINT,
        slide_height_pt=document.slide_height / EMU_PER_POINT,
        slides=tuple(slides),
        text_occurrences=occurrences,
        unsupported_objects=tuple(unsupported),
    )


def _shape_snapshot(shape, part_uri: str, slide_index: int, unsupported: list[UnsupportedObject], theme_fonts: ThemeFonts) -> SlideObject:  # type: ignore[no-untyped-def]
    key = f"{part_uri}:shape:{shape.shape_id}"
    shape_type = _shape_type_name(shape.shape_type)
    children = ()
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        children = tuple(
            _shape_snapshot(child, part_uri, slide_index, unsupported, theme_fonts)
            for child in shape.shapes
        )
    if shape.shape_type in {
        MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT,
        MSO_SHAPE_TYPE.LINKED_OLE_OBJECT,
        MSO_SHAPE_TYPE.MEDIA,
    }:
        unsupported.append(UnsupportedObject(slide_index, key, shape_type))
    placeholder_type = None
    if shape.is_placeholder:
        placeholder_type = str(shape.placeholder_format.type)
    return SlideObject(
        key=key,
        name=shape.name,
        object_type=shape_type,
        bounds_pt=Rect(
            shape.left / EMU_PER_POINT,
            shape.top / EMU_PER_POINT,
            shape.width / EMU_PER_POINT,
            shape.height / EMU_PER_POINT,
        ),
        rotation=float(shape.rotation or 0),
        visible=not _shape_hidden(shape),
        has_visual_style=_has_visual_style(shape),
        from_master=False,
        placeholder_type=placeholder_type,
        text_frame=_shape_text_frame(shape, theme_fonts),
        children=children,
    )


def _text_frame(shape, theme_fonts: ThemeFonts) -> TextFrameSnapshot:  # type: ignore[no-untyped-def]
    paragraph_snapshots: list[tuple[TextRunSnapshot, ...]] = []
    offset = 0
    for paragraph_index, paragraph in enumerate(shape.text_frame.paragraphs):
        runs: list[TextRunSnapshot] = []
        for run in paragraph.runs:
            direct_or_inherited = run.font.name or paragraph.font.name or _placeholder_font(shape, paragraph_index)
            latin, east_asia = _effective_fonts(shape, direct_or_inherited, theme_fonts)
            runs.append(
            TextRunSnapshot(
                text=run.text,
                font_name=latin,
                east_asia_font_name=east_asia,
                font_size_pt=run.font.size.pt if run.font.size is not None else None,
                bold=run.font.bold,
                italic=run.font.italic,
                start=offset,
                end=offset + len(run.text),
            )
            )
            offset += len(run.text)
        paragraph_snapshots.append(tuple(runs))
        if paragraph_index < len(shape.text_frame.paragraphs) - 1:
            offset += 1
    return TextFrameSnapshot(text=shape.text, paragraphs=tuple(paragraph_snapshots))


def _shape_text_frame(shape, theme_fonts: ThemeFonts) -> TextFrameSnapshot | None:  # type: ignore[no-untyped-def]
    if getattr(shape, "has_text_frame", False):
        return _text_frame(shape, theme_fonts)
    if not getattr(shape, "has_table", False):
        return None
    paragraphs: list[tuple[TextRunSnapshot, ...]] = []
    texts: list[str] = []
    offset = 0
    for row in shape.table.rows:
        for cell in row.cells:
            texts.append(cell.text)
            for paragraph_index, paragraph in enumerate(cell.text_frame.paragraphs):
                runs: list[TextRunSnapshot] = []
                for run in paragraph.runs:
                    runs.append(
                        TextRunSnapshot(
                            text=run.text,
                            font_name=run.font.name or paragraph.font.name or theme_fonts.minor_latin,
                            east_asia_font_name=run.font.name or paragraph.font.name or theme_fonts.minor_east_asia,
                            font_size_pt=run.font.size.pt if run.font.size is not None else None,
                            bold=run.font.bold,
                            italic=run.font.italic,
                            start=offset,
                            end=offset + len(run.text),
                        )
                    )
                    offset += len(run.text)
                paragraphs.append(tuple(runs))
                if paragraph_index < len(cell.text_frame.paragraphs) - 1:
                    offset += 1
            offset += 1
    return TextFrameSnapshot(text="\n".join(texts), paragraphs=tuple(paragraphs))


def _effective_fonts(shape, declared: str | None, theme: ThemeFonts) -> tuple[str | None, str | None]:  # type: ignore[no-untyped-def]
    major = bool(shape.is_placeholder and str(shape.placeholder_format.type).startswith(("TITLE", "CENTER_TITLE")))
    latin = theme.major_latin if major else theme.minor_latin
    east_asia = theme.major_east_asia if major else theme.minor_east_asia
    if declared:
        return (_resolve_theme_token(declared, theme, east_asia=False), _resolve_theme_token(declared, theme, east_asia=True))
    return latin, east_asia or latin


def _placeholder_font(shape, paragraph_index: int) -> str | None:  # type: ignore[no-untyped-def]
    current = shape
    while getattr(current, "is_placeholder", False):
        current = getattr(current, "_base_placeholder", None)
        if current is None or not getattr(current, "has_text_frame", False):
            break
        paragraphs = current.text_frame.paragraphs
        paragraph = paragraphs[min(paragraph_index, len(paragraphs) - 1)]
        if paragraph.font.name:
            return paragraph.font.name
    return None


def _resolve_theme_token(value: str, theme: ThemeFonts, *, east_asia: bool) -> str | None:
    mapping = {
        "+mj-lt": theme.major_latin,
        "+mj-ea": theme.major_east_asia,
        "+mn-lt": theme.minor_latin,
        "+mn-ea": theme.minor_east_asia,
    }
    if value in mapping:
        return mapping[value]
    return value


def _read_theme_fonts(path: Path) -> ThemeFonts:
    with ZipFile(path) as package:
        theme_name = next((name for name in package.namelist() if name.startswith("ppt/theme/theme") and name.endswith(".xml")), None)
        if theme_name is None:
            return ThemeFonts(None, None, None, None)
        root = etree.fromstring(package.read(theme_name), parser=etree.XMLParser(resolve_entities=False, no_network=True))
    ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    def font(kind: str, script: str) -> str | None:
        values = root.xpath(f"./a:themeElements/a:fontScheme/a:{kind}Font/a:{script}/@typeface", namespaces=ns)
        if values and values[0]:
            return values[0]
        hans = root.xpath(f"./a:themeElements/a:fontScheme/a:{kind}Font/a:font[@script='Hans']/@typeface", namespaces=ns)
        return hans[0] if hans else None
    return ThemeFonts(font("major", "latin"), font("major", "ea"), font("minor", "latin"), font("minor", "ea"))


def _text_occurrences(item) -> tuple[TextOccurrence, ...]:  # type: ignore[no-untyped-def]
    key = f"{item.part_uri}:{item.source}:{item.xml_path}"
    locations = tuple(
        CharacterLocation(item.part_uri, item.xml_path, offset)
        for offset in range(len(item.text))
    )
    slide_indices = item.slide_indices or (0,)
    return tuple(
        TextOccurrence(
            key=key,
            slide_index=slide_index,
            source=TextSource(item.source),
            text=item.text,
            visible=True,
            character_map=locations,
        )
        for slide_index in slide_indices
    )


def _shape_hidden(shape) -> bool:  # type: ignore[no-untyped-def]
    values = shape.element.xpath(".//*[local-name()='cNvPr']/@hidden")
    return bool(values and values[0] in {"1", "true"})


def _has_visual_style(shape) -> bool:  # type: ignore[no-untyped-def]
    if shape.shape_type in {
        MSO_SHAPE_TYPE.PICTURE,
        MSO_SHAPE_TYPE.CHART,
        MSO_SHAPE_TYPE.TABLE,
        MSO_SHAPE_TYPE.GROUP,
        MSO_SHAPE_TYPE.MEDIA,
        MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT,
        MSO_SHAPE_TYPE.LINKED_OLE_OBJECT,
    }:
        return True
    if shape.shape_type in {MSO_SHAPE_TYPE.TEXT_BOX, MSO_SHAPE_TYPE.PLACEHOLDER}:
        return bool(getattr(shape, "text", "").strip())
    return True


def _slide_hidden(slide_id) -> bool:  # type: ignore[no-untyped-def]
    return slide_id.get("show") in {"0", "false"}


def _shape_type_name(value) -> str:  # type: ignore[no-untyped-def]
    return getattr(value, "name", str(value)).lower()
