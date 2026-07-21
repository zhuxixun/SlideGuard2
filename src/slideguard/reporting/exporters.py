from __future__ import annotations

from collections import Counter
from html import escape
from pathlib import Path
from tempfile import NamedTemporaryFile

from openpyxl import Workbook
from openpyxl.styles import Font

from slideguard.preview.svg_builder import PreviewObject, build_svg
from slideguard.scan.models import ScanResult


def export_html(result: ScanResult, destination: Path, *, software_version: str = "0.1.0") -> None:
    _validate_destination(destination, ".html")
    severity = Counter(found.severity.value for found in result.issues)
    rules = Counter(found.rule_id for found in result.issues)
    affected_pages = len({found.slide_index for found in result.issues if found.slide_index > 0})
    fixable = sum(found.can_auto_fix for found in result.issues)
    rows = "".join(_html_issue_row(result, found) for found in result.issues)
    rule_summary = "".join(
        f"<li>{escape(rule_id)}：{count}</li>" for rule_id, count in sorted(rules.items())
    )
    incomplete = "<div class='incomplete'>扫描未完成</div>" if not result.complete else ""
    comparison = _html_repair_comparison(result)
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>SlideGuard 质检报告</title>
<style>body{{font-family:'Microsoft YaHei',sans-serif;margin:32px;color:#222}}h1{{color:#c00000}}.incomplete{{padding:16px;background:#ffd9d9;color:#8b0000;font-weight:bold}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccc;padding:8px;text-align:left;vertical-align:top}}th{{background:#f2f2f2}}.S1{{color:#a00000;font-weight:bold}}.preview{{width:240px;max-height:140px}}</style></head>
<body><h1>SlideGuard 质检报告</h1>{incomplete}
<dl><dt>文件名</dt><dd>{escape(result.snapshot.file_identity.path.name)}</dd><dt>路径</dt><dd>{escape(str(result.snapshot.file_identity.path))}</dd><dt>大小</dt><dd>{result.snapshot.file_identity.size_bytes} bytes</dd><dt>页数</dt><dd>{len(result.snapshot.slides)}</dd><dt>扫描模式</dt><dd>{escape(result.mode.value)}</dd><dt>完整性</dt><dd>{'完整' if result.complete else '未完成'}</dd><dt>规则集</dt><dd>{escape(result.rule_set_version)}</dd><dt>软件版本</dt><dd>{escape(software_version)}</dd><dt>开始时间</dt><dd>{result.started_at.isoformat()}</dd><dt>结束时间</dt><dd>{result.finished_at.isoformat()}</dd></dl>
<p>S1 {severity['S1']} / S2 {severity['S2']} / S3 {severity['S3']} / S4 {severity['S4']}；涉及页面 {affected_pages}；可自动修复 {fixable}</p>{comparison}<ul>{rule_summary}</ul>
<table><thead><tr><th>级别</th><th>规则</th><th>页码</th><th>实际值</th><th>标准值</th><th>依据</th><th>建议</th><th>预览</th></tr></thead><tbody>{rows}</tbody></table></body></html>"""
    _atomic_text(destination, document)


def export_xlsx(result: ScanResult, destination: Path, *, software_version: str = "0.1.0") -> None:
    _validate_destination(destination, ".xlsx")
    workbook = Workbook()
    summary = workbook.active
    summary.title = "扫描摘要"
    summary.append(("项目", "值"))
    summary["A1"].font = summary["B1"].font = Font(bold=True)
    severity = Counter(found.severity.value for found in result.issues)
    values = (
        ("文件名", result.snapshot.file_identity.path.name),
        ("路径", str(result.snapshot.file_identity.path)),
        ("大小(bytes)", result.snapshot.file_identity.size_bytes),
        ("页数", len(result.snapshot.slides)),
        ("扫描模式", result.mode.value),
        ("完整性", "完整" if result.complete else "扫描未完成"),
        ("规则集版本", result.rule_set_version),
        ("软件版本", software_version),
        ("开始时间", result.started_at.isoformat()),
        ("结束时间", result.finished_at.isoformat()),
        *( (level, severity[level]) for level in ("S1", "S2", "S3", "S4") ),
        *_xlsx_repair_comparison(result),
    )
    for row in values:
        summary.append(row)
    details = workbook.create_sheet("问题清单")
    headers = ("问题ID", "级别", "规则", "页码", "状态", "可自动修复", "实际值", "标准值", "标准来源", "判断依据", "修改建议", "对象ID")
    details.append(headers)
    for cell in details[1]:
        cell.font = Font(bold=True)
    for found in result.issues:
        details.append(tuple(_safe_excel(value) for value in (
            found.issue_id, found.severity.value, found.rule_id, found.slide_index,
            found.status.value, "是" if found.can_auto_fix else "否", found.actual_value,
            found.expected_value, found.standard_source, found.evidence, found.suggestion,
            ", ".join(found.object_keys),
        )))
    for sheet in (summary, details):
        sheet.freeze_panes = "A2"
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = min(60, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        workbook.save(temporary_path)
        temporary_path.rename(destination)
    finally:
        temporary_path.unlink(missing_ok=True)


def default_report_name(result: ScanResult, extension: str) -> str:
    timestamp = result.finished_at.astimezone().strftime("%Y%m%d_%H%M%S")
    return f"{result.snapshot.file_identity.path.stem}_SlideGuard_{timestamp}.{extension.lstrip('.')}"


def _html_repair_comparison(result: ScanResult) -> str:
    comparison = result.repair_comparison
    if comparison is None:
        return ""
    return (
        "<p><strong>修复前后对比：</strong>"
        f"选中 {comparison.selected_count}；已修复 {comparison.fixed_count}；"
        f"未修复 {comparison.unresolved_count}；修复后新增 {comparison.introduced_count}</p>"
    )


def _xlsx_repair_comparison(result: ScanResult) -> tuple[tuple[str, int], ...]:
    comparison = result.repair_comparison
    if comparison is None:
        return ()
    return (
        ("修复选中问题数", comparison.selected_count),
        ("已修复问题数", comparison.fixed_count),
        ("未修复问题数", comparison.unresolved_count),
        ("修复后新增问题数", comparison.introduced_count),
    )


def _html_issue_row(result: ScanResult, found) -> str:  # type: ignore[no-untyped-def]
    return "<tr>" + "".join(
        f"<td>{escape(str(value))}</td>" for value in (
            found.severity.value, found.rule_id, found.slide_index, found.actual_value,
            found.expected_value, found.evidence, found.suggestion,
        )
    ) + f"<td>{_slide_svg(result, found)}</td></tr>"


def _slide_svg(result: ScanResult, found) -> str:  # type: ignore[no-untyped-def]
    if found.slide_index < 1 or found.slide_index > len(result.snapshot.slides):
        return "预览不可用"
    slide = result.snapshot.slides[found.slide_index - 1]
    objects = tuple(_preview_objects(slide.objects))
    return build_svg(
        slide_width_pt=result.snapshot.slide_width_pt,
        slide_height_pt=result.snapshot.slide_height_pt,
        objects=objects,
        highlighted_ids=frozenset(found.object_keys[:1]),
        reference_ids=frozenset(found.object_keys[1:] if found.rule_id == "R007" else ()),
        page_highlight=not found.object_keys,
    ).replace("<svg ", "<svg class='preview' ", 1)


def _preview_objects(objects):  # type: ignore[no-untyped-def]
    for obj in objects:
        yield PreviewObject(
            obj.key,
            obj.bounds_pt.left,
            obj.bounds_pt.top,
            obj.bounds_pt.width,
            obj.bounds_pt.height,
            obj.text_frame.text if obj.text_frame is not None else "",
        )
        yield from _preview_objects(obj.children)


def _safe_excel(value):  # type: ignore[no-untyped-def]
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _validate_destination(destination: Path, suffix: str) -> None:
    if destination.suffix.lower() != suffix:
        raise ValueError(f"报告扩展名必须为 {suffix}")
    if destination.exists():
        raise FileExistsError("目标报告已存在，不允许覆盖")


def _atomic_text(destination: Path, content: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    try:
        temporary_path.rename(destination)
    finally:
        temporary_path.unlink(missing_ok=True)
