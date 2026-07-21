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
    assert "http://" not in html + javascript
    assert "https://" not in html + javascript
