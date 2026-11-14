"""Чтение файлов судебных решений: .docx (и .doc, который на деле .docx), .txt."""
from __future__ import annotations

import zipfile
from pathlib import Path

SUPPORTED = {".docx", ".doc", ".txt"}


def read_text(path: Path) -> str:
    """Текст документа: абзацы и таблицы в том порядке, в каком они идут в файле."""
    suffix = path.suffix.lower()
    if suffix == ".txt":
        raw = path.read_bytes()
        for enc in ("utf-8-sig", "cp1251"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        raise ValueError("не удалось определить кодировку текстового файла")
    if suffix in (".docx", ".doc"):
        # Портал часто отдаёт .docx с расширением .doc. Настоящий .docx — это zip-архив.
        if not zipfile.is_zipfile(path):
            raise ValueError("старый формат Word (.doc): откройте файл в Word и сохраните как .docx")
        return _read_docx(path)
    raise ValueError(f"формат {suffix or 'без расширения'} не поддерживается (нужен .docx или .txt)")


def _read_docx(path: Path) -> str:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(str(path))
    parts: list[str] = []
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            parts.append(Paragraph(child, document).text)
        elif tag == "tbl":
            for row in Table(child, document).rows:
                cells: list[str] = []
                for cell in row.cells:
                    text = cell.text.strip()
                    if text and (not cells or cells[-1] != text):  # объединённые ячейки повторяются
                        cells.append(text)
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def list_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith("~$"))
