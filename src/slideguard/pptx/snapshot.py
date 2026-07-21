from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

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
    font_size_pt: float | None
    bold: bool | None
    italic: bool | None


@dataclass(frozen=True, slots=True)
class TextFrameSnapshot:
    text: str
    paragraphs: tuple[tuple[TextRunSnapshot, ...], ...]


@dataclass(frozen=True, slots=True)
class SlideObject:
    key: str
    object_type: str
    bounds_pt: Rect
    rotation: float
    visible: bool
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
    slides: list[SlideSnapshot] = []
    unsupported: list[UnsupportedObject] = []
    slide_ids = tuple(document.slides._sldIdLst)  # noqa: SLF001
    for index, slide in enumerate(document.slides, start=1):
        part_uri = str(slide.part.partname).lstrip("/")
        objects = tuple(
            _shape_snapshot(shape, part_uri, index, unsupported)
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

    occurrences = tuple(_text_occurrence(item) for item in probe_text(imported.path))
    return PresentationSnapshot(
        file_identity=FileIdentity(imported.path, imported.size_bytes, imported.digest),
        slide_width_pt=document.slide_width / EMU_PER_POINT,
        slide_height_pt=document.slide_height / EMU_PER_POINT,
        slides=tuple(slides),
        text_occurrences=occurrences,
        unsupported_objects=tuple(unsupported),
    )


def _shape_snapshot(shape, part_uri: str, slide_index: int, unsupported: list[UnsupportedObject]) -> SlideObject:  # type: ignore[no-untyped-def]
    key = f"{part_uri}:shape:{shape.shape_id}"
    shape_type = _shape_type_name(shape.shape_type)
    children = ()
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        children = tuple(
            _shape_snapshot(child, part_uri, slide_index, unsupported)
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
        object_type=shape_type,
        bounds_pt=Rect(
            shape.left / EMU_PER_POINT,
            shape.top / EMU_PER_POINT,
            shape.width / EMU_PER_POINT,
            shape.height / EMU_PER_POINT,
        ),
        rotation=float(shape.rotation or 0),
        visible=not _shape_hidden(shape),
        from_master=False,
        placeholder_type=placeholder_type,
        text_frame=_text_frame(shape) if getattr(shape, "has_text_frame", False) else None,
        children=children,
    )


def _text_frame(shape) -> TextFrameSnapshot:  # type: ignore[no-untyped-def]
    paragraphs = tuple(
        tuple(
            TextRunSnapshot(
                text=run.text,
                font_name=run.font.name,
                font_size_pt=run.font.size.pt if run.font.size is not None else None,
                bold=run.font.bold,
                italic=run.font.italic,
            )
            for run in paragraph.runs
        )
        for paragraph in shape.text_frame.paragraphs
    )
    return TextFrameSnapshot(text=shape.text, paragraphs=paragraphs)


def _text_occurrence(item) -> TextOccurrence:  # type: ignore[no-untyped-def]
    slide_index = item.slide_indices[0] if item.slide_indices else 0
    key = f"{item.part_uri}:{item.source}:{item.xml_path}"
    locations = tuple(
        CharacterLocation(item.part_uri, item.xml_path, offset)
        for offset in range(len(item.text))
    )
    return TextOccurrence(
        key=key,
        slide_index=slide_index,
        source=TextSource(item.source),
        text=item.text,
        visible=True,
        character_map=locations,
    )


def _shape_hidden(shape) -> bool:  # type: ignore[no-untyped-def]
    values = shape.element.xpath(".//*[local-name()='cNvPr']/@hidden")
    return bool(values and values[0] in {"1", "true"})


def _slide_hidden(slide_id) -> bool:  # type: ignore[no-untyped-def]
    return slide_id.get("show") in {"0", "false"}


def _shape_type_name(value) -> str:  # type: ignore[no-untyped-def]
    return getattr(value, "name", str(value)).lower()
