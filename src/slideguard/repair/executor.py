from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import os
from pathlib import Path
import re
import tempfile
from zipfile import BadZipFile, ZipFile

from lxml import etree

from slideguard.pptx.importer import inspect_pptx
from slideguard.pptx.probe import PptxProbeError
from slideguard.repair.models import FixOperation, FixPlan
from slideguard.repair.planner import FixPlanError, validate_plan_source
from slideguard.scan.models import ScanMode, ScanRequest, ScanResult
from slideguard.scan.orchestrator import run_scan


A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
EMU_PER_POINT = 12_700


@dataclass(frozen=True, slots=True)
class RepairResult:
    destination: Path
    verification_scan: ScanResult
    fixed_issue_ids: tuple[str, ...]
    unresolved_issue_ids: tuple[str, ...]
    introduced_issue_count: int


def execute_fix_plan(plan: FixPlan) -> None:
    validate_plan_source(plan)
    grouped: dict[str, list[FixOperation]] = {}
    for operation in plan.operations:
        part_uri, _ = _object_locator(operation.object_key)
        grouped.setdefault(part_uri, []).append(operation)
    plan.destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{plan.destination.stem}.",
            suffix=".tmp.pptx",
            dir=plan.destination.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        with ZipFile(plan.source_identity.path, "r") as source, ZipFile(temporary_path, "w") as output:
            missing = set(grouped) - set(source.namelist())
            if missing:
                raise FixPlanError(f"修复目标部件不存在：{', '.join(sorted(missing))}")
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename in grouped:
                    data = _apply_part_operations(data, grouped[info.filename])
                output.writestr(info, data)
        imported = inspect_pptx(temporary_path)
        if imported.slide_count != len(_source_slide_count(plan)):
            raise FixPlanError("修复结果页数发生变化")
        temporary_path.rename(plan.destination)
    except (OSError, BadZipFile, etree.XMLSyntaxError, PptxProbeError) as exc:
        if isinstance(exc, FixPlanError):
            raise
        raise FixPlanError(f"无法安全生成修复文件：{exc}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def execute_and_recheck(
    plan: FixPlan,
    *,
    sensitive_terms: tuple[str, ...] = (),
) -> RepairResult:
    execute_fix_plan(plan)
    verification = run_scan(
        inspect_pptx(plan.destination),
        ScanRequest(ScanMode.STANDARD, sensitive_terms=sensitive_terms),
    )
    original_facts = {fact for _, fact in plan.selected_facts}
    remaining_facts = {found.fact_key for found in verification.issues}
    fixed = tuple(issue_id for issue_id, fact in plan.selected_facts if fact not in remaining_facts)
    unresolved = tuple(issue_id for issue_id, fact in plan.selected_facts if fact in remaining_facts)
    all_original_facts = plan.baseline_fact_keys
    introduced = 0
    marked = []
    for found in verification.issues:
        if found.fact_key not in all_original_facts:
            found = replace(found, introduced_by_repair=True)
            introduced += 1
        marked.append(found)
    verification = replace(verification, issues=tuple(marked))
    return RepairResult(plan.destination, verification, fixed, unresolved, introduced)


def _apply_part_operations(data: bytes, operations: list[FixOperation]) -> bytes:
    root = etree.fromstring(
        data,
        parser=etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, recover=False),
    )
    for operation in operations:
        _, shape_id = _object_locator(operation.object_key)
        matches = root.xpath(f"//*[local-name()='cNvPr' and @id='{shape_id}']/../..")
        if len(matches) != 1:
            raise FixPlanError(f"修复对象必须唯一匹配：{operation.object_key}")
        shape = matches[0]
        if operation.property_name in {"move_x", "move_y"}:
            _move(shape, operation)
        elif operation.property_name == "replace_font":
            for run in _target_runs(shape, operation):
                _set_font(_run_properties(run), operation.target_value)
        elif operation.property_name == "replace_font_size":
            size = str(round(float(operation.target_value) * 100))
            for run in _target_runs(shape, operation):
                _run_properties(run).set("sz", size)
        elif operation.property_name == "set_title_style":
            for run in _all_runs(shape):
                properties = _run_properties(run)
                _set_font(properties, "Microsoft YaHei")
                properties.set("sz", "2400")
                properties.set("b", "1")
                _set_color(properties, "C00000")
        elif operation.property_name == "scale_title_suffix":
            _scale_title_suffix(shape, int(operation.target_value))
        else:
            raise FixPlanError(f"不支持的修复操作：{operation.property_name}")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True)


def _object_locator(object_key: str) -> tuple[str, str]:
    marker = ":shape:"
    if marker not in object_key:
        raise FixPlanError(f"无法定位修复对象：{object_key}")
    part_uri, shape_id = object_key.rsplit(marker, 1)
    if not shape_id.isdigit():
        raise FixPlanError(f"无效对象ID：{object_key}")
    return part_uri, shape_id


def _move(shape, operation: FixOperation) -> None:  # type: ignore[no-untyped-def]
    offsets = shape.xpath("./*[local-name()='spPr']/*[local-name()='xfrm']/*[local-name()='off'] | ./*[local-name()='xfrm']/*[local-name()='off'] | ./*[local-name()='grpSpPr']/*[local-name()='xfrm']/*[local-name()='off']")
    if len(offsets) != 1:
        raise FixPlanError(f"对象位置必须唯一匹配：{operation.object_key}")
    axis = "x" if operation.property_name == "move_x" else "y"
    offsets[0].set(axis, str(round(float(operation.target_value) * EMU_PER_POINT)))


def _all_runs(shape):  # type: ignore[no-untyped-def]
    return shape.xpath(".//*[local-name()='r' or local-name()='fld']")


def _target_runs(shape, operation: FixOperation):  # type: ignore[no-untyped-def]
    runs = _all_runs(shape)
    ranges = [
        (int(match.group(1)), int(match.group(2)))
        for fact in operation.fact_keys
        if (match := re.search(r":(\d+):(\d+)(?::[^:]*)?$", fact))
    ]
    if not ranges:
        return runs
    selected = []
    offset = 0
    paragraphs = shape.xpath(".//*[local-name()='p']")
    for paragraph_index, paragraph in enumerate(paragraphs):
        for run in paragraph.xpath("./*[local-name()='r' or local-name()='fld']"):
            text = "".join(run.xpath("./*[local-name()='t']/text()"))
            start, end = offset, offset + len(text)
            if any(start < range_end and end > range_start for range_start, range_end in ranges):
                selected.append(run)
            offset = end
        if paragraph_index < len(paragraphs) - 1:
            offset += 1
    if not selected:
        raise FixPlanError(f"无法将字符范围映射到修复对象：{operation.object_key}")
    return selected


def _run_properties(run):  # type: ignore[no-untyped-def]
    properties = run.find(f"{{{A_NS}}}rPr")
    if properties is None:
        properties = etree.Element(f"{{{A_NS}}}rPr")
        run.insert(0, properties)
    return properties


def _set_font(properties, typeface: str) -> None:  # type: ignore[no-untyped-def]
    for tag in ("latin", "ea", "cs"):
        element = properties.find(f"{{{A_NS}}}{tag}")
        if element is None:
            element = etree.SubElement(properties, f"{{{A_NS}}}{tag}")
        element.set("typeface", typeface)


def _set_color(properties, rgb: str) -> None:  # type: ignore[no-untyped-def]
    solid = properties.find(f"{{{A_NS}}}solidFill")
    if solid is None:
        solid = etree.SubElement(properties, f"{{{A_NS}}}solidFill")
    for child in tuple(solid):
        solid.remove(child)
    etree.SubElement(solid, f"{{{A_NS}}}srgbClr", val=rgb)


def _scale_title_suffix(shape, size: int) -> None:  # type: ignore[no-untyped-def]
    runs = _all_runs(shape)
    colon_found = False
    for run in runs:
        text_element = run.find(f"{{{A_NS}}}t")
        text = text_element.text or "" if text_element is not None else ""
        if colon_found:
            _run_properties(run).set("sz", str(size * 100))
            continue
        indices = [index for index in (text.find("："), text.find(":")) if index >= 0]
        if not indices:
            continue
        index = min(indices)
        colon_found = True
        suffix = text[index + 1 :]
        text_element.text = text[: index + 1]
        if suffix:
            cloned = deepcopy(run)
            cloned.find(f"{{{A_NS}}}t").text = suffix
            _run_properties(cloned).set("sz", str(size * 100))
            run.addnext(cloned)
    if not colon_found:
        raise FixPlanError("标题中未找到可拆分的冒号")


def _source_slide_count(plan: FixPlan) -> tuple[object, ...]:
    # The scan snapshot is authoritative and does not require reopening with PowerPoint.
    with ZipFile(plan.source_identity.path) as package:
        root = etree.fromstring(package.read("ppt/presentation.xml"))
    return tuple(root.xpath("//*[local-name()='sldId']"))
