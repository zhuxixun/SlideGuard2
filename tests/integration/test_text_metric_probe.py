from pathlib import Path

from pptx import Presentation

from slideguard.probes.text_metrics import CASES, generate_text_metric_probe


def test_text_metric_probe_generates_reopenable_pptx_and_manifest(
    tmp_path: Path,
) -> None:
    pptx_path, csv_path = generate_text_metric_probe(tmp_path)

    presentation = Presentation(pptx_path)
    assert len(presentation.slides) == len(CASES)
    manifest = csv_path.read_text(encoding="utf-8-sig")
    assert "powerpoint_visible_width_pt" in manifest
    assert "absolute_error_pt" in manifest
    assert all(case.case_id in manifest for case in CASES)

