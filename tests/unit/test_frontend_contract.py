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
    assert "修改 ${modified} 条" in javascript
    assert "R010 将标记为执行失败；其他规则仍可正常检查" in javascript
    assert "原词库未改变" in javascript
    assert "打开 PPT 文件" in html
    assert "将 .pptx 文件拖到此处" in html
    assert "pptx-drop-zone" in html
    assert "离线运行" in html
    assert 'class="logo"' in html
    assert 'role="button"' in html
    assert "文件详情" in html
    assert "file-path" in html
    assert "/api/dialog/open-pptx" in javascript
    assert "/api/files/drop" in javascript
    assert 'addEventListener("drop"' in javascript
    assert 'event.key === "Enter"' in javascript
    assert 'event.key === " "' in javascript
    assert 'type="file"' not in html
    assert "FormData" not in javascript
    assert "快速检查" in html
    assert "标准检查" in html
    assert "自定义检查" in html
    assert "全不选" in html
    assert "恢复默认" in html
    assert "module-rule" in html
    assert html.count("data-rule type=\"checkbox\"") == 9
    assert "/api/scans" in javascript
    assert "/api/scans/current/cancel" in javascript
    assert "renderScanState" in javascript
    assert "completed_rule_ids" in javascript
    assert "severity_counts" in javascript
    assert "正在处理第" in javascript
    assert "master.indeterminate" in javascript
    assert "updateScanAvailability" in javascript
    assert "问题列表" in html
    assert "issue-search" in html
    assert "page-filter" in html
    assert "severity-filter" in html
    assert "fixable-filter" in html
    assert "status-filter" in html
    assert "showIssue" in javascript
    assert "previewRequestId" in javascript
    assert "预览不可用；请查看技术信息和判断依据" in javascript
    assert "/preview?issue_id=" in javascript
    assert "导出 HTML 报告" in html
    assert "导出 Excel 报告" in html
    assert "/api/reports/export" in javascript
    assert "修复选中项" in html
    assert "修复此问题" in html
    assert "原始文件始终保留" in html
    assert "/api/repairs/prepare" in javascript
    assert "/api/repairs/execute" in javascript
    assert "repairAllowed" in javascript
    assert "prepareRepair([filteredIssues[activeIssueIndex].issue_id])" in javascript
    assert "operation_indexes" in javascript
    assert "updateRepairConfirmation" in javascript
    assert "未发现符合当前规则的问题" in javascript
    assert "实际执行规则" in javascript
    assert "失败规则 ${failure.rule_id}" in javascript
    assert "扫描已取消" in javascript
    assert "rule_set_version" in javascript
    assert "这些范围不得视为检查通过" in javascript
    assert "http://" not in html + javascript
    assert "https://" not in html + javascript
