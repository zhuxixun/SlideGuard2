from pathlib import Path


FRONTEND = Path("src/slideguard/frontend")


def test_frontend_implements_in_app_lexicon_management_without_remote_assets() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    javascript = (FRONTEND / "app.js").read_text(encoding="utf-8")

    assert "管理敏感词库" in html
    assert "批量粘贴" in html
    assert "/api/lexicon" in javascript
    assert 'method: "PUT"' in javascript
    assert "expected_digest" in javascript
    assert "window.confirm" in javascript
    assert "打开 PPT 文件" in html
    assert "/api/dialog/open-pptx" in javascript
    assert 'type="file"' not in html
    assert "FormData" not in javascript
    assert "快速检查" in html
    assert "标准检查" in html
    assert "自定义检查" in html
    assert "/api/scans" in javascript
    assert "/api/scans/current/cancel" in javascript
    assert "renderScanState" in javascript
    assert "问题列表" in html
    assert "issue-search" in html
    assert "severity-filter" in html
    assert "fixable-filter" in html
    assert "status-filter" in html
    assert "showIssue" in javascript
    assert "/preview?issue_id=" in javascript
    assert "导出 HTML 报告" in html
    assert "导出 Excel 报告" in html
    assert "/api/reports/export" in javascript
    assert "http://" not in html + javascript
    assert "https://" not in html + javascript
