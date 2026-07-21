from pathlib import Path

import pytest

from slideguard.lexicon import LexiconError, LexiconStore, normalize_terms


def test_normalize_terms_trims_ignores_empty_and_deduplicates() -> None:
    assert normalize_terms([" 项目A ", "", "项目A", "Project X"]) == (
        "项目A",
        "Project X",
    )


def test_store_round_trip_and_atomic_update(tmp_path: Path) -> None:
    path = tmp_path / "sensitive-terms.txt"
    path.write_text("旧项目\n", encoding="utf-8")
    store = LexiconStore(path)

    before = store.load()
    after = store.save([" 内部代号 ", "内部代号", "禁用产品"], expected_digest=before.digest)

    assert after.terms == ("内部代号", "禁用产品")
    assert store.load() == after
    assert path.read_text(encoding="utf-8") == "内部代号\n禁用产品\n"


def test_store_rejects_stale_digest(tmp_path: Path) -> None:
    path = tmp_path / "sensitive-terms.txt"
    path.write_text("词条一\n", encoding="utf-8")
    store = LexiconStore(path)
    stale = store.load()
    path.write_text("词条二\n", encoding="utf-8")

    with pytest.raises(LexiconError, match="已被其他操作修改"):
        store.save(["词条三"], expected_digest=stale.digest)


def test_store_rejects_invalid_utf8(tmp_path: Path) -> None:
    path = tmp_path / "sensitive-terms.txt"
    path.write_bytes(b"\xff\xfe")

    with pytest.raises(LexiconError, match="无法读取"):
        LexiconStore(path).load()

