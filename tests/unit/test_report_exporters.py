from pathlib import Path

import pytest
from openpyxl import load_workbook
from pptx import Presentation

from slideguard.pptx.importer import inspect_pptx
from slideguard.reporting.exporters import default_report_name, export_html, export_xlsx
from slideguard.rules.factory import issue
from slideguard.rules.models import Severity
from slideguard.scan.models import ScanMode, ScanRequest
from slideguard.scan.orchestrator import run_scan


def _result(tmp_path: Path, *, complete: bool = True):  # type: ignore[no-untyped-def]
    path = tmp_path / "客户 & 项目.pptx"
    document = Presentation()
    document.slides.add_slide(document.slide_layouts[6])
    document.save(path)
    found = issue(
        fact_key="report-test",
        rule_id="R002",
        slide_index=1,
        object_keys=(),
        severity=Severity.S1,
        actual_value="=SUM(A1:A2)<script>",
        expected_value="expected",
        evidence="evidence",
        suggestion="suggestion",
    )
    unavailable = {"R003": "failed"} if not complete else None
    rules = {"R002": lambda *_: (found,), "R003": lambda *_: ()}
    selected = ("R002", "R003") if not complete else ("R002",)
    return run_scan(
        inspect_pptx(path),
        ScanRequest(ScanMode.CUSTOM, selected_rules=selected),
        rules=rules,
        unavailable_rules=unavailable,
    )


def test_html_report_is_single_file_escaped_and_marks_incomplete(tmp_path: Path) -> None:
    result = _result(tmp_path, complete=False)
    destination = tmp_path / "report.html"
    export_html(result, destination)
    content = destination.read_text(encoding="utf-8")
    assert "扫描未完成" in content
    assert "客户 &amp; 项目.pptx" in content
    assert "&lt;script&gt;" in content
    assert "<script>" not in content
    assert "data-page-highlight" in content
    assert 'src="http' not in content
    assert 'href="http' not in content


def test_xlsx_report_has_summary_details_and_formula_protection(tmp_path: Path) -> None:
    destination = tmp_path / "report.xlsx"
    export_xlsx(_result(tmp_path), destination)
    workbook = load_workbook(destination, data_only=False)
    assert workbook.sheetnames == ["扫描摘要", "问题清单"]
    details = workbook["问题清单"]
    assert details.cell(2, 7).value == "'=SUM(A1:A2)<script>"
    assert workbook["扫描摘要"].cell(2, 2).value == "客户 & 项目.pptx"


def test_report_export_never_overwrites_existing_file(tmp_path: Path) -> None:
    destination = tmp_path / "existing.html"
    destination.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        export_html(_result(tmp_path), destination)
    assert destination.read_text(encoding="utf-8") == "keep"


def test_default_report_name_contains_source_and_timestamp(tmp_path: Path) -> None:
    name = default_report_name(_result(tmp_path), "xlsx")
    assert name.startswith("客户 & 项目_SlideGuard_")
    assert name.endswith(".xlsx")
