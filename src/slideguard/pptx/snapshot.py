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
    paragraph_level: int
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
    paragraphs: tuple["ParagraphSnapshot", ...]
    margin_left_pt: float
    margin_right_pt: float
    margin_top_pt: float
    margin_bottom_pt: float
    word_wrap: bool | None
    auto_size: str | None
    auto_fit_scale: float
    vertical: bool
    vertical_anchor: str | None


@dataclass(frozen=True, slots=True)
class ParagraphSnapshot:
    runs: tuple[TextRunSnapshot, ...]
    line_spacing_multiplier: float | None
    line_spacing_pt: float | None
    space_before_pt: float
    space_after_pt: float
    alignment: str | None

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.runs)

    def __getitem__(self, index: int) -> TextRunSnapshot:
        return self.runs[index]

    def __len__(self) -> int:
        return len(self.runs)


@dataclass(frozen=True, slots=True)
class TableCellSnapshot:
    key: str
    row: int
    column: int
    bounds_pt: Rect
    text_frame: TextFrameSnapshot


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
    table_cells: tuple[TableCellSnapshot, ...]
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
        table_cells=_table_cells(shape, key, theme_fonts),
        children=children,
    )


def _text_frame(shape, theme_fonts: ThemeFonts) -> TextFrameSnapshot:  # type: ignore[no-untyped-def]
    paragraph_snapshots: list[ParagraphSnapshot] = []
    offset = 0
    for paragraph_index, paragraph in enumerate(shape.text_frame.paragraphs):
        runs: list[TextRunSnapshot] = []
        for run in paragraph.runs:
            direct_or_inherited = run.font.name or paragraph.font.name or _placeholder_font(shape, paragraph_index)
            latin, east_asia = _effective_fonts(shape, direct_or_inherited, theme_fonts)
            font_size = run.font.size or paragraph.font.size or _placeholder_font_size(shape, paragraph_index)
            runs.append(
            TextRunSnapshot(
                text=run.text,
                font_name=latin,
                east_asia_font_name=east_asia,
                font_size_pt=font_size.pt if font_size is not None else None,
                bold=run.font.bold,
                italic=run.font.italic,
                paragraph_level=paragraph.level,
                start=offset,
                end=offset + len(run.text),
            )
            )
            offset += len(run.text)
        paragraph_snapshots.append(_paragraph_snapshot(paragraph, tuple(runs)))
        if paragraph_index < len(shape.text_frame.paragraphs) - 1:
            offset += 1
    frame = shape.text_frame
    return TextFrameSnapshot(
        text=shape.text,
        paragraphs=tuple(paragraph_snapshots),
        margin_left_pt=(frame.margin_left or 0) / EMU_PER_POINT,
        margin_right_pt=(frame.margin_right or 0) / EMU_PER_POINT,
        margin_top_pt=(frame.margin_top or 0) / EMU_PER_POINT,
        margin_bottom_pt=(frame.margin_bottom or 0) / EMU_PER_POINT,
        word_wrap=frame.word_wrap,
        auto_size=str(frame.auto_size) if frame.auto_size is not None else None,
        auto_fit_scale=_auto_fit_scale(shape.element),
        vertical=_is_vertical_text(shape.element),
        vertical_anchor=str(frame.vertical_anchor) if frame.vertical_anchor is not None else None,
    )


def _shape_text_frame(shape, theme_fonts: ThemeFonts) -> TextFrameSnapshot | None:  # type: ignore[no-untyped-def]
    if getattr(shape, "has_text_frame", False):
        return _text_frame(shape, theme_fonts)
    if not getattr(shape, "has_table", False):
        return None
    paragraphs: list[ParagraphSnapshot] = []
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
                            paragraph_level=paragraph.level,
                            start=offset,
                            end=offset + len(run.text),
                        )
                    )
                    offset += len(run.text)
                paragraphs.append(_paragraph_snapshot(paragraph, tuple(runs)))
                if paragraph_index < len(cell.text_frame.paragraphs) - 1:
                    offset += 1
            offset += 1
    return TextFrameSnapshot(
        text="\n".join(texts),
        paragraphs=tuple(paragraphs),
        margin_left_pt=0,
        margin_right_pt=0,
        margin_top_pt=0,
        margin_bottom_pt=0,
        word_wrap=True,
        auto_size=None,
        auto_fit_scale=1,
        vertical=False,
        vertical_anchor=None,
    )


def _paragraph_snapshot(paragraph, runs: tuple[TextRunSnapshot, ...]) -> ParagraphSnapshot:  # type: ignore[no-untyped-def]
    spacing = paragraph.line_spacing
    multiplier = spacing if isinstance(spacing, float) else None
    spacing_pt = spacing.pt if spacing is not None and not isinstance(spacing, float) else None
    return ParagraphSnapshot(
        runs=runs,
        line_spacing_multiplier=multiplier,
        line_spacing_pt=spacing_pt,
        space_before_pt=paragraph.space_before.pt if paragraph.space_before is not None else 0,
        space_after_pt=paragraph.space_after.pt if paragraph.space_after is not None else 0,
        alignment=str(paragraph.alignment) if paragraph.alignment is not None else None,
    )


def _table_cells(shape, object_key: str, theme_fonts: ThemeFonts) -> tuple[TableCellSnapshot, ...]:  # type: ignore[no-untyped-def]
    if not getattr(shape, "has_table", False):
        return ()
    result: list[TableCellSnapshot] = []
    table = shape.table
    top = shape.top
    for row_index, row in enumerate(table.rows):
        left = shape.left
        for column_index, column in enumerate(table.columns):
            cell = table.cell(row_index, column_index)
            if not cell.is_spanned:
                width = sum(
                    table.columns[index].width
                    for index in range(column_index, min(len(table.columns), column_index + cell.span_width))
                )
                height = sum(
                    table.rows[index].height
                    for index in range(row_index, min(len(table.rows), row_index + cell.span_height))
                )
                result.append(
                    TableCellSnapshot(
                        key=f"{object_key}:cell:{row_index}:{column_index}",
                        row=row_index,
                        column=column_index,
                        bounds_pt=Rect(
                            left / EMU_PER_POINT,
                            top / EMU_PER_POINT,
                            width / EMU_PER_POINT,
                            height / EMU_PER_POINT,
                        ),
                        text_frame=_cell_text_frame(cell, theme_fonts),
                    )
                )
            left += column.width
        top += row.height
    return tuple(result)


def _cell_text_frame(cell, theme_fonts: ThemeFonts) -> TextFrameSnapshot:  # type: ignore[no-untyped-def]
    paragraphs: list[ParagraphSnapshot] = []
    offset = 0
    for paragraph_index, paragraph in enumerate(cell.text_frame.paragraphs):
        runs: list[TextRunSnapshot] = []
        for run in paragraph.runs:
            font = run.font.name or paragraph.font.name
            runs.append(
                TextRunSnapshot(
                    text=run.text,
                    font_name=font or theme_fonts.minor_latin,
                    east_asia_font_name=font or theme_fonts.minor_east_asia,
                    font_size_pt=(run.font.size or paragraph.font.size).pt if (run.font.size or paragraph.font.size) is not None else None,
                    bold=run.font.bold,
                    italic=run.font.italic,
                    paragraph_level=paragraph.level,
                    start=offset,
                    end=offset + len(run.text),
                )
            )
            offset += len(run.text)
        paragraphs.append(_paragraph_snapshot(paragraph, tuple(runs)))
        if paragraph_index < len(cell.text_frame.paragraphs) - 1:
            offset += 1
    return TextFrameSnapshot(
        text=cell.text,
        paragraphs=tuple(paragraphs),
        margin_left_pt=(cell.margin_left or 0) / EMU_PER_POINT,
        margin_right_pt=(cell.margin_right or 0) / EMU_PER_POINT,
        margin_top_pt=(cell.margin_top or 0) / EMU_PER_POINT,
        margin_bottom_pt=(cell.margin_bottom or 0) / EMU_PER_POINT,
        word_wrap=True,
        auto_size=None,
        auto_fit_scale=1,
        vertical=False,
        vertical_anchor=None,
    )


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


def _placeholder_font_size(shape, paragraph_index: int):  # type: ignore[no-untyped-def]
    current = shape
    while getattr(current, "is_placeholder", False):
        current = getattr(current, "_base_placeholder", None)
        if current is None or not getattr(current, "has_text_frame", False):
            break
        paragraphs = current.text_frame.paragraphs
        paragraph = paragraphs[min(paragraph_index, len(paragraphs) - 1)]
        if paragraph.font.size is not None:
            return paragraph.font.size
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


def _auto_fit_scale(element) -> float:  # type: ignore[no-untyped-def]
    values = element.xpath(".//*[local-name()='normAutofit']/@fontScale")
    if not values:
        return 1.0
    try:
        return max(0.0, min(1.0, int(values[0]) / 100_000))
    except ValueError:
        return 1.0


def _is_vertical_text(element) -> bool:  # type: ignore[no-untyped-def]
    values = element.xpath(".//*[local-name()='bodyPr']/@vert")
    return bool(values and values[0] not in {"horz", ""})


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
