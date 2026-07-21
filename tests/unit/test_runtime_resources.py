from pathlib import Path

from slideguard.runtime import application_root, frontend_root, validate_runtime


def test_development_runtime_resources_are_present() -> None:
    assert application_root() == Path.cwd().resolve()
    assert (frontend_root() / "index.html").is_file()
    assert (frontend_root() / "app.js").is_file()
    validate_runtime()

