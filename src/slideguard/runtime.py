from __future__ import annotations

from pathlib import Path
import sys
import tkinter

from jinja2 import Environment
from lxml import etree
from openpyxl import Workbook
from pptx import Presentation
import websockets

from slideguard.preview.text_layout import (
    MICROSOFT_YAHEI_BOLD,
    MICROSOFT_YAHEI_REGULAR,
)


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()


def frontend_root() -> Path:
    return Path(__file__).resolve().parent / "frontend"


def validate_runtime() -> None:
    required = (
        frontend_root() / "index.html",
        frontend_root() / "app.js",
        frontend_root() / "app.css",
        application_root() / "data" / "config" / "sensitive-terms.txt",
        MICROSOFT_YAHEI_REGULAR,
        MICROSOFT_YAHEI_BOLD,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"SlideGuard运行资源缺失：{', '.join(missing)}")
    etree.fromstring(b"<runtime-check/>")
    Presentation()
    Workbook()
    Environment(autoescape=True).from_string("{{ value }}").render(value="ok")
    tkinter.Tcl().eval("info patchlevel")
    if not websockets.__version__:
        raise RuntimeError("WebSocket运行依赖不可用")
