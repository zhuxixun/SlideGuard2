from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from lxml import etree

from slideguard.pptx.probe import MAX_PPTX_BYTES, REQUIRED_PARTS


class PptxImportError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ImportedPresentation:
    path: Path
    file_name: str
    size_bytes: int
    slide_count: int
    digest: str


def inspect_pptx(path: Path) -> ImportedPresentation:
    path = path.resolve()
    if path.suffix.lower() != ".pptx":
        raise PptxImportError("unsupported_format", "仅支持 .pptx 文件")
    try:
        if not path.is_file():
            raise PptxImportError("file_unavailable", "所选文件不存在或无法读取")
        size = path.stat().st_size
    except OSError as exc:
        raise PptxImportError("file_unavailable", "所选文件不存在或无法读取") from exc
    if size > MAX_PPTX_BYTES:
        raise PptxImportError("file_too_large", "PPTX 文件大小不能超过 200MB")

    try:
        with ZipFile(path) as package:
            names = frozenset(package.namelist())
            missing = REQUIRED_PARTS - names
            if missing:
                raise PptxImportError("invalid_pptx", "文件缺少必要的 PPTX 部件")
            corrupt = package.testzip()
            if corrupt is not None:
                raise PptxImportError("corrupt_pptx", "PPTX 压缩包中存在损坏的部件")
            slide_count = _slide_count(package.read("ppt/presentation.xml"))
    except PptxImportError:
        raise
    except (BadZipFile, etree.XMLSyntaxError, KeyError, OSError) as exc:
        raise PptxImportError("invalid_pptx", "文件不是有效且可解析的 PPTX") from exc

    return ImportedPresentation(
        path=path,
        file_name=path.name,
        size_bytes=size,
        slide_count=slide_count,
        digest=_sha256(path),
    )


def _slide_count(presentation_xml: bytes) -> int:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    root = etree.fromstring(presentation_xml, parser=parser)
    namespace = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
    return len(root.xpath("./p:sldIdLst/p:sldId", namespaces=namespace))


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
