"""Сбор решений из «Банка судебных актов» portal-sot.kz.

    python -m sud_parser.collect --keywords "объединение собственников имущества" --year 2025 --limit 50

Как работает:
1. Открывается отдельное окно Chrome (свой профиль, ваш обычный Chrome не трогается).
2. Вы сами входите на портал по ЭЦП. Программа ключ и пароль не видит и не вводит.
3. Программа заполняет форму поиска, как человек, нажимает «Найти» и по очереди открывает дела:
   у каждого дела скачивает документы-решения, потом переходит к следующему делу и странице.
4. Между делами пауза; если портал перегружен (не открывает дело), программа ждёт дольше и повторяет.

Портал ищет по словам, а не по смыслу: в выдачу попадают и дела, где ОСИ лишь упоминается.
Такие дела отсеивает уже анализатор («ОСИ не сторона спора»).

Файлы называются по номеру дела, без ФИО. В папке появляется журнал _manifest.csv:
при повторном запуске уже скачанные дела пропускаются, можно продолжать с места остановки.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PORTAL = "https://portal-sot.kz/"
PROFILE_DIR = Path("data/browser-profile")
MANIFEST = "_manifest.csv"
MANIFEST_FIELDS = ["case_number", "result", "category", "page", "status", "files", "time"]

CASE_TYPES = {"гражданские": "CIVIL", "уголовные": "CRIMINAL", "административные правонарушения": "ADMINISTRATIVE",
              "административные": "APPK"}
DECISION_RE = re.compile(r"решени", re.IGNORECASE)


# --- то, что не зависит от браузера (проверяется тестами) --------------------------------------

def safe_name(case_number: str) -> str:
    """7517-24-00-2/45552 -> 7517-24-00-2_45552 (без символов, запрещённых в именах файлов)."""
    return re.sub(r"[^0-9A-Za-zА-Яа-яЁё.-]+", "_", case_number).strip("_") or "дело"


def file_name(case_number: str, index: int, suggested: str) -> str:
    """Имя файла без ФИО: портал называет файлы по фамилиям сторон."""
    suffix = Path(suggested).suffix.lower() or ".docx"
    return f"{safe_name(case_number)}_{index}{suffix}"


def case_number_of(cell_text: str) -> str:
    return cell_text.strip().split("\n")[0].strip()


@dataclass
class Row:
    case_number: str
    result: str
    category: str


class Manifest:
    """Журнал скачанного: позволяет продолжить после остановки и не качать дело дважды."""

    def __init__(self, folder: Path):
        self.path = folder / MANIFEST
        self.done: set[str] = set()
        self.saved = 0  # дел, по которым скачано хотя бы одно решение
        if self.path.exists():
            with self.path.open(encoding="utf-8-sig", newline="") as f:
                for rec in csv.DictReader(f):
                    if rec["status"] in ("ok", "нет решений"):
                        self.done.add(rec["case_number"])
                    if rec["status"] == "ok":
                        self.saved += 1

    def add(self, row: Row, page: int, status: str, files: list[str]) -> None:
        new = not self.path.exists()
        with self.path.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
            if new:
                w.writeheader()
            w.writerow({"case_number": row.case_number, "result": row.result, "category": row.category,
                        "page": page, "status": status, "files": "; ".join(files),
                        "time": f"{datetime.now():%Y-%m-%d %H:%M:%S}"})
        if status in ("ok", "нет решений"):
            self.done.add(row.case_number)
        if status == "ok":
            self.saved += 1


def search_body(args) -> dict:
    """Запрос в том виде, как его задаёт форма портала: сохраняется рядом с файлами, чтобы выборку можно было повторить."""
    return {"тип": args.case_type, "год": args.year, "инстанция": "первая", "слова": args.keywords,
            "область": args.region or "все", "результат": args.result or "все", "лимит": args.limit}


# --- работа со страницей портала -------------------------------------------------------------

SET_SELECT_JS = """([label, value]) => {
  const sels = [...document.querySelectorAll('form select')];
  const s = sels.find(s => { let el = s;
    for (let i = 0; i < 5 && el; i++) { el = el.parentElement;
      if (el && el.innerText && el.innerText.trim().startsWith(label)) return true; }
    return false; });
  if (!s) return 'поле не найдено: ' + label;
  const v = value.toLowerCase();
  const opt = [...s.options].find(o => o.value.toLowerCase() === v || o.text.trim().toLowerCase() === v)
           || [...s.options].find(o => o.text.trim().toLowerCase().includes(v));
  if (!opt) return 'нет варианта «' + value + '» в поле ' + label;
  s.value = opt.value; s.dispatchEvent(new Event('change', {bubbles: true})); return 'ok';
}"""

ROWS_JS = """() => [...document.querySelectorAll('tbody tr')].map(tr =>
  [...tr.children].map(td => td.innerText.trim()))"""


class Portal:
    def __init__(self, page, pause: float, log, page_wait: float = 15):
        self.page = page
        self.pause = pause
        self.log = log
        self.page_wait = page_wait  # сколько ждать смены страницы после «вперёд»

    def button(self, text: str):
        return self.page.get_by_role("button", name=text, exact=True)

    def wait_login(self, timeout_min: int) -> None:
        self.page.goto(PORTAL)
        self.log("Войдите на портал по ЭЦП в открывшемся окне Chrome. Программа ждёт…")
        deadline = time.time() + timeout_min * 60
        while time.time() < deadline:
            # после входа в меню появляется кнопка выхода/кабинета и ссылка на банк актов
            if self.page.locator("a[href='/court-acts']").count() and self.page.locator("a[href='/cabinet']").count():
                self.log("Вход выполнен.")
                return
            time.sleep(2)
        raise TimeoutError(f"Вход не выполнен за {timeout_min} мин.")

    def open_bank(self) -> None:
        self.page.locator("a[href='/court-acts']").first.click()
        self.page.locator("input[name=searchText]").wait_for(timeout=30_000)

    def set_select(self, label: str, value: str) -> None:
        res = self.page.evaluate(SET_SELECT_JS, [label, value])
        if res != "ok":
            raise ValueError(res)
        time.sleep(0.8)  # следующие поля (категория, суд) подгружаются после выбора

    def search(self, args) -> None:
        self.set_select("Тип производства", args.case_type)
        self.set_select("Учетный год", str(args.year))
        first = self.page.get_by_role("checkbox", name="Первая инстанция")
        if first.get_attribute("aria-checked") != "true":
            first.click()
        self.page.locator("input[name=searchText]").fill(args.keywords)
        if args.region or args.result:
            self.button("Расширенный поиск").click()
            time.sleep(1)
            if args.region:
                self.set_select("Область", args.region)
            if args.result:
                self.set_select("Результат рассмотрения", args.result)
        self.button("Найти").click()
        self.wait_rows()

    def wait_rows(self, timeout: float = 30) -> list[list[str]]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.page.get_by_text("Найдено дел").count() and self.page.locator("tbody tr").count():
                return self.page.evaluate(ROWS_JS)
            time.sleep(0.5)
        raise TimeoutError("Список дел не загрузился")

    def rows(self) -> list[Row]:
        return [Row(case_number_of(c[0]), c[3] if len(c) > 3 else "", c[4] if len(c) > 4 else "")
                for c in self.wait_rows()]

    def total(self) -> str:
        m = re.search(r"Найдено дел:\s*([\d\s]+)", self.page.inner_text("body"))
        return m.group(1).strip() if m else "?"

    def back_to_list(self) -> None:
        for text in ("Вернуться к делу", "Вернуться к списку найденных дел"):
            b = self.button(text)
            if b.count():
                b.first.click()
                time.sleep(1.5)
        self.wait_rows()

    def open_case(self, index: int) -> list[tuple[str, str]] | None:
        """Открыть дело из списка; вернуть документы (вид, название файла) или None, если не открылось."""
        cell = self.page.locator("tbody tr").nth(index).locator("td").first
        (cell.locator("div, span").first if cell.locator("div, span").count() else cell).click()
        deadline = time.time() + 15
        while time.time() < deadline:
            if self.page.get_by_text("Дело №").count():
                docs = [(c[1], c[2]) for c in self.page.evaluate(ROWS_JS) if len(c) >= 3]
                if docs:
                    return docs
            time.sleep(0.5)
        return None

    def download(self, doc_name: str, target: Path) -> None:
        self.page.locator("tbody tr td button", has_text=doc_name).first.click()
        save = self.button("Скачать")
        save.wait_for(timeout=15_000)
        time.sleep(1)
        with self.page.expect_download(timeout=60_000) as info:
            save.click()
        dl = info.value
        if dl.failure():
            raise RuntimeError(dl.failure())
        dl.save_as(target)
        self.button("Вернуться к делу").click()
        time.sleep(1.5)

    def next_page(self, previous_first: str) -> bool:
        """Нажать «вперёд». Портал иногда показывает ту же страницу ещё раз: тогда ждём и нажимаем снова."""
        nav = self.page.locator("nav[aria-label=pagination] li button")
        if not nav.count():
            return False
        for _ in range(3):
            nav.last.click()
            deadline = time.time() + self.page_wait
            while time.time() < deadline:
                rows = self.rows()
                if rows and rows[0].case_number != previous_first:
                    return True
                time.sleep(1)
        return False


def say(message: str) -> None:
    print(message, flush=True)  # сразу, а не в конце: прогон идёт долго


def collect(args, log=say) -> int:
    from playwright.sync_api import sync_playwright

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "_query.json").write_text(json.dumps(search_body(args), ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = Manifest(out)
    if manifest.done:
        log(f"Уже скачано раньше: {manifest.saved} дел, они будут пропущены.")

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR), channel="chrome", headless=False, accept_downloads=True,
            viewport={"width": 1400, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        portal = Portal(page, args.pause, log)
        try:
            portal.wait_login(args.login_wait)
            portal.open_bank()
            portal.search(args)
            log(f"Портал нашёл дел: {portal.total()}")
            walk_results(portal, manifest, out, args)
        except KeyboardInterrupt:
            log("Остановлено. Повторный запуск продолжит с этого места.")
        except (RuntimeError, TimeoutError, ValueError) as exc:
            log(f"Остановлено: {exc}. Повторный запуск продолжит с этого места.")
        finally:
            ctx.close()
    log(f"Готово: дел с решениями {manifest.saved}. Папка: {out.resolve()}")
    log(f"Анализ: python -m sud_parser.practice --dir \"{out.resolve()}\"")
    return 0


def walk_results(portal: Portal, manifest: Manifest, out: Path, args) -> None:
    """Пройти по страницам выдачи и скачать решения, пока не наберётся args.limit дел."""
    page_no = 1
    while manifest.saved < args.limit and page_no <= args.max_pages:
        rows = portal.rows()
        portal.log(f"Страница {page_no}: {len(rows)} дел")
        for i, row in enumerate(rows):
            if manifest.saved >= args.limit:
                break
            if row.case_number in manifest.done:
                continue
            status, files = fetch_case(portal, i, row, out, args)
            manifest.add(row, page_no, status, files)
            portal.log(f"  {row.case_number}: {status}" + (f" ({len(files)} файл.)" if files else ""))
            portal.back_to_list()
            time.sleep(args.pause)
        if manifest.saved >= args.limit or not portal.next_page(rows[0].case_number if rows else ""):
            break
        page_no += 1


def fetch_case(portal: Portal, index: int, row: Row, out: Path, args) -> tuple[str, list[str]]:
    current = portal.rows()
    if index >= len(current) or current[index].case_number != row.case_number:
        # после возврата портал показал другую страницу: не открываем чужое дело
        raise RuntimeError(f"после возврата к списку на месте {row.case_number} другое дело")
    docs = None
    for attempt in range(3):
        docs = portal.open_case(index)
        if docs is not None:
            break
        wait = args.pause * 10 * (attempt + 1)  # портал перегружен (503): ждём всё дольше
        portal.log(f"  {row.case_number}: дело не открылось, жду {wait:.0f} с")
        portal.back_to_list()
        time.sleep(wait)
    if docs is None:
        return "не открылось", []
    decisions = [name for kind, name in docs if DECISION_RE.search(kind)]
    if not decisions:
        return "нет решений", []
    files, errors = [], []
    for n, name in enumerate(decisions, 1):
        target = out / file_name(row.case_number, n, name)
        try:
            portal.download(name, target)
            files.append(target.name)
        except Exception as exc:  # например, .rtf портал не отдаёт (401)
            errors.append(f"{Path(name).suffix}: {str(exc)[:80]}")
            for text in ("Вернуться к делу",):
                if portal.button(text).count():
                    portal.button(text).first.click()
        time.sleep(args.pause / 2)
    if files:
        return "ok", files
    return "ошибка скачивания: " + "; ".join(errors), []


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="sud_parser.collect", description="Скачать решения из Банка судебных актов")
    p.add_argument("--keywords", required=True, help="слова для поиска, как в поле «Поиск по ключевому слову»")
    p.add_argument("--year", type=int, default=datetime.now().year, help="учетный год")
    p.add_argument("--case-type", default="CIVIL", help="CIVIL (гражданские), APPK (административные) и т. п.")
    p.add_argument("--region", default="", help="область как на портале, например «город Астана»")
    p.add_argument("--result", default="", help="результат рассмотрения как на портале")
    p.add_argument("--limit", type=int, default=50, help="сколько дел с решениями скачать")
    p.add_argument("--max-pages", type=int, default=200)
    p.add_argument("--pause", type=float, default=4.0, help="пауза между делами, секунд")
    p.add_argument("--login-wait", type=int, default=10, help="сколько минут ждать входа по ЭЦП")
    p.add_argument("--out", default="", help="папка для решений (по умолчанию data/collected/<дата>)")
    args = p.parse_args(argv)
    args.case_type = CASE_TYPES.get(args.case_type.lower(), args.case_type)
    if not args.out:
        args.out = str(Path("data/collected") / f"{datetime.now():%Y-%m-%d_%H-%M}")
    return collect(args)


if __name__ == "__main__":
    sys.exit(main())
