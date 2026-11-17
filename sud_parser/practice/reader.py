"""Чтение файлов судебных решений: .docx, .rtf, .txt (и .doc, который на деле .docx или .rtf)."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

SUPPORTED = {".docx", ".doc", ".rtf", ".txt"}


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
    if suffix in (".docx", ".doc", ".rtf"):
        # Портал часто отдаёт .docx или .rtf с расширением .doc: смотрим на содержимое, а не на имя.
        if zipfile.is_zipfile(path):
            return _read_docx(path)
        with path.open("rb") as f:
            head = f.read(5)
        if head == b"{\\rtf":
            return rtf_to_text(path.read_bytes())
        raise ValueError("старый формат Word (.doc): откройте файл в Word и сохраните как .docx")
    raise ValueError(f"формат {suffix or 'без расширения'} не поддерживается (нужен .docx, .rtf или .txt)")


# --- RTF ------------------------------------------------------------------------------------------
# Свой разбор без внешних библиотек: решения в RTF — обычный текст с управляющими словами.

# Группы, в которых нет текста документа: таблицы шрифтов и цветов, стили, свойства, картинки.
_RTF_SKIP = {
    "fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "header", "footer", "headerl",
    "headerr", "headerf", "footerl", "footerr", "footerf", "listtable", "listoverridetable",
    "rsidtbl", "xmlnstbl", "generator", "themedata", "colorschememapping", "latentstyles",
    "datastore", "fldinst", "pgdsctbl", "revtbl", "filetbl", "mmathPr", "wgrffmtfilter",
}
_RTF_TOKEN = re.compile(
    rb"\\'([0-9a-fA-F]{2})|\\([a-zA-Z]+)(-?\d+)? ?|\\([^a-zA-Z])|([{}])|[\r\n]+|([^\\{}\r\n]+)"
)
# Кодовые страницы шрифтов: \fcharset204 — кириллица.
_CHARSETS = {0: "cp1252", 204: "cp1251", 238: "cp1250", 161: "cp1253", 162: "cp1254", 186: "cp1257"}


def rtf_to_text(data: bytes) -> str:
    """Текст из RTF: абзацы — строки, ячейки таблиц — через « | »."""
    codepage = "cp1251"
    m = re.search(rb"\\ansicpg(\d+)", data[:2000])
    if m:
        codepage = f"cp{int(m.group(1))}"
    font_cp: dict[int, str] = {}
    for fm in re.finditer(rb"\\f(\d+)[^{};]*?\\fcharset(\d+)", data):
        font_cp[int(fm.group(1))] = _CHARSETS.get(int(fm.group(2)), codepage)

    out: list[str] = []
    pending = bytearray()  # байты \'xx текущей кодировки, декодируем пачкой
    stack: list[tuple[bool, int, str]] = []
    skip, uc, cur_cp, to_skip = False, 1, codepage, 0

    def flush() -> None:
        if pending:
            out.append(pending.decode(cur_cp, errors="replace"))
            pending.clear()

    for t in _RTF_TOKEN.finditer(data):
        hexbyte, word, arg, sym, brace, text = t.groups()
        if brace == b"{":
            flush()
            stack.append((skip, uc, cur_cp))
            continue
        if brace == b"}":
            flush()
            if stack:
                skip, uc, cur_cp = stack.pop()
            continue
        if to_skip and (hexbyte or text):  # замена после \uN, её пропускаем
            if hexbyte:
                to_skip -= 1
                continue
            n = min(to_skip, len(text))
            text, to_skip = text[n:], to_skip - n
            if not text:
                continue
        if hexbyte:
            if not skip:
                pending.append(int(hexbyte, 16))
            continue
        flush()
        if text is not None:
            if not skip:
                out.append(text.decode(cur_cp, errors="replace"))
            continue
        if sym is not None:
            if sym == b"*":
                skip = True  # {\*\неизвестная_группа …}
            elif not skip and sym in (b"\\", b"{", b"}"):
                out.append(sym.decode())
            elif not skip and sym == b"~":
                out.append("\u00a0")
            elif not skip and sym in (b"-", b"_"):
                out.append("-" if sym == b"_" else "")
            continue
        if word is None:
            continue
        w = word.decode()
        if w in _RTF_SKIP:
            skip = True
        elif skip:
            continue
        elif w in ("par", "line", "sect", "page"):
            out.append("\n")
        elif w == "cell":
            out.append(" | ")
        elif w == "row":
            out.append("\n")
        elif w == "tab":
            out.append("\t")
        elif w == "uc":
            uc = int(arg or 1)
        elif w == "u":
            code = int(arg or 0)
            out.append(chr(code + 65536 if code < 0 else code))
            to_skip = uc
        elif w == "f" and arg is not None:
            cur_cp = font_cp.get(int(arg), codepage)
        elif w in ("emdash", "endash"):
            out.append("—" if w == "emdash" else "–")
        elif w in ("lquote", "rquote"):
            out.append("'")
        elif w in ("ldblquote", "rdblquote"):
            out.append("\"")
    flush()
    text = "".join(out)
    text = re.sub(r"(?: \| )+\n", "\n", text)  # хвост строки таблицы
    return "\n".join(line.rstrip() for line in text.split("\n"))


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
