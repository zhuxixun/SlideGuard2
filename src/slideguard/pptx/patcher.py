from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from zipfile import BadZipFile, ZipFile

from lxml import etree

from slideguard.pptx.probe import PptxProbeError, REQUIRED_PARTS


@dataclass(frozen=True, slots=True)
class XmlAttributePatch:
    part_uri: str
    xpath: str
    attributes: tuple[tuple[str, str], ...]


def patch_pptx(
    source: Path,
    output: Path,
    operations: tuple[XmlAttributePatch, ...],
) -> None:
    if output.exists():
        raise PptxProbeError("输出文件已存在，不允许覆盖")
    if source.resolve() == output.resolve():
        raise PptxProbeError("输出路径必须与原文件不同")

    grouped: dict[str, list[XmlAttributePatch]] = {}
    for operation in operations:
        grouped.setdefault(operation.part_uri, []).append(operation)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{output.stem}.",
            suffix=".tmp.pptx",
            dir=output.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        with ZipFile(source, "r") as source_zip, ZipFile(temporary_path, "w") as output_zip:
            names = frozenset(source_zip.namelist())
            missing_parts = set(grouped) - names
            if missing_parts:
                raise PptxProbeError(
                    f"修复目标部件不存在：{', '.join(sorted(missing_parts))}"
                )
            for info in source_zip.infolist():
                data = source_zip.read(info.filename)
                if info.filename in grouped:
                    data = _patch_xml(data, grouped[info.filename])
                output_zip.writestr(info, data)
        _validate_output(temporary_path)
        os.replace(temporary_path, output)
    except (OSError, BadZipFile) as exc:
        raise PptxProbeError(f"无法生成修复文件：{exc}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _patch_xml(data: bytes, operations: list[XmlAttributePatch]) -> bytes:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        recover=False,
        huge_tree=False,
        remove_blank_text=False,
    )
    root = etree.fromstring(data, parser=parser)
    namespaces = {prefix: uri for prefix, uri in root.nsmap.items() if prefix}
    for operation in operations:
        matches = root.xpath(operation.xpath, namespaces=namespaces)
        if len(matches) != 1 or not isinstance(matches[0], etree._Element):
            raise PptxProbeError(
                f"修复目标必须唯一匹配：{operation.part_uri} {operation.xpath}"
            )
        target = matches[0]
        for name, value in operation.attributes:
            target.set(name, value)
    return etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        standalone=None,
    )


def _validate_output(path: Path) -> None:
    with ZipFile(path, "r") as package:
        corrupt = package.testzip()
        if corrupt is not None:
            raise PptxProbeError(f"修复文件ZIP校验失败：{corrupt}")
        missing = REQUIRED_PARTS - frozenset(package.namelist())
        if missing:
            raise PptxProbeError(
                f"修复文件缺少必要部件：{', '.join(sorted(missing))}"
            )

