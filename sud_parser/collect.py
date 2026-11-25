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
            "область": args.region or "все", "результат": args.result or "все",
            "категория": getattr(args, "category", "") or "все",
            "только список": getattr(args, "list_only", False), "лимит": args.limit}


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

OPTIONS_JS = """(label) => {
  const sels = [...document.querySelectorAll('form select')];
  const s = sels.find(s => { let el = s;
    for (let i = 0; i < 5 && el; i++) { el = el.parentElement;
      if (el && el.innerText && el.innerText.trim().startsWith(label)) return true; }
    return false; });
  return s ? [...s.options].map(o => o.text.trim()).filter(t => t && t !== 'Выберите') : [];
}"""

ROWS_JS = """() => [...document.querySelectorAll('tbody tr')].map(tr =>
  [...tr.children].map(td => td.innerText.trim()))"""


class PortalStuck(RuntimeError):
    """Портал показал ошибку вместо списка: нужно искать заново."""


class Portal:
    def __init__(self, page, pause: float, log, page_wait: float = 15):
        self.page = page
        self.pause = pause
        self.log = log
        self.page_wait = page_wait  # сколько ждать смены страницы после «вперёд»
        self.category_text = ""     # полное название выбранной категории, как на портале

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

    def debug_snapshot(self, name: str) -> None:
        """Снимок экрана и текст страницы при сбое — чтобы понять, что показал портал (в data/, не в git)."""
        folder = Path("data/collected/_debug")
        folder.mkdir(parents=True, exist_ok=True)
        stamp = f"{datetime.now():%H-%M-%S}_{name}"
        try:
            self.page.screenshot(path=str(folder / f"{stamp}.png"), full_page=True)
            (folder / f"{stamp}.html").write_text(self.page.content(), encoding="utf-8")
        except Exception:
            pass

    def open_bank_again(self) -> None:
        """Начать поиск заново без перезагрузки страницы: перезагрузка сбрасывает вход по ЭЦП."""
        self.page.locator("a[href='/cabinet']").first.click()
        time.sleep(2)
        self.open_bank()

    def set_select(self, label: str, value: str, timeout: float = 20) -> None:
        # варианты списков портал подгружает отдельно: пока их нет, ждём
        deadline = time.time() + timeout
        while True:
            res = self.page.evaluate(SET_SELECT_JS, [label, value])
            if res == "ok":
                break
            if self.field_button(label).count() and (res.startswith("поле не найдено") or self.empty_select(label)):
                self.popup_select(label, value)  # поле — всплывающее окно, а не обычный список
                return
            if time.time() > deadline:
                raise ValueError(res)
            time.sleep(0.5)
        time.sleep(0.8)  # следующие поля (категория, суд) подгружаются после выбора

    # Часть полей формы — не <select>, а кнопка со всплывающим списком (как «Категория дела»).
    # «Результат рассмотрения» — Radix Select: скрытый <select> пустой, варианты ([role=listbox] [role=option])
    # появляются только после нажатия на кнопку поля.
    POPUP_ITEMS = ("[data-radix-popper-content-wrapper] [cmdk-item], [data-radix-popper-content-wrapper] [role=option], "
                   "[role=listbox] [role=option]")

    def empty_select(self, label: str) -> bool:
        """Скрытый <select> поля без вариантов — значит, варианты только во всплывающем списке."""
        return not self.page.evaluate(OPTIONS_JS, label)

    def field_button(self, label: str):
        return self.page.locator("form label", has_text=label).locator("xpath=..").locator("button").first

    def popup_options(self, label: str) -> list[str]:
        if not self.field_button(label).count():
            return []
        self.field_button(label).click()
        items = self.page.locator(self.POPUP_ITEMS)
        texts: list[str] = []
        for _ in range(20):
            time.sleep(0.5)
            texts = [" ".join(t.split()) for t in items.all_inner_texts()]
            if texts:
                break
        self.page.keyboard.press("Escape")
        time.sleep(0.5)
        return [t for t in texts if t and t != "Выберите"]

    def popup_select(self, label: str, value: str) -> None:
        self.field_button(label).click()
        items = self.page.locator(self.POPUP_ITEMS)
        want = " ".join(value.split()).lower()
        for _ in range(20):
            time.sleep(0.5)
            texts = [" ".join(t.split()).lower() for t in items.all_inner_texts()]
            index = next((i for i, t in enumerate(texts) if t == want), None)
            if index is None:
                index = next((i for i, t in enumerate(texts) if want in t), None)
            if index is not None:
                items.nth(index).click()
                time.sleep(0.8)
                if self.page.locator("[data-radix-popper-content-wrapper]").count():
                    self.page.keyboard.press("Escape")
                return
        self.page.keyboard.press("Escape")
        raise ValueError(f"нет варианта «{value}» в поле {label}")

    def logged_in(self) -> bool:
        return bool(self.page.locator("a[href='/cabinet']").count())

    def relogin(self, timeout_min: int = 30) -> None:
        """Портал завершил сессию (401): ждём, пока человек снова войдёт по ЭЦП, и открываем банк актов."""
        self.log("!!! Портал завершил сессию. Войдите по ЭЦП заново в окне сборщика — сбор продолжится сам.")
        self.wait_login(timeout_min)
        self.open_bank()

    def select_category(self, category: str) -> None:
        """«Категория дела» — всплывающее окно с поиском среди ~300 категорий, а не обычный список.
        Берём вариант, совпадающий целиком, иначе первый, где встречается текст."""
        self.page.locator("form label", has_text="Категория дела").locator("xpath=..").locator("button").first.click()
        search = self.page.locator("[data-radix-popper-content-wrapper] input[placeholder='Поиск']")
        search.wait_for(timeout=10_000)
        search.fill(category)
        options = self.page.locator("[data-radix-popper-content-wrapper] [cmdk-item]")
        want = " ".join(category.split()).lower()
        index, texts = None, []
        deadline = time.time() + 20  # список категорий портал подгружает не сразу
        while index is None and time.time() < deadline:
            time.sleep(1)
            texts = [t.strip() for t in options.all_inner_texts()]
            index = next((i for i, t in enumerate(texts) if " ".join(t.split()).lower() == want), None)
            if index is None:
                index = next((i for i, t in enumerate(texts) if want in t.lower()), None)
        if index is None:
            self.debug_snapshot("no-category")
            raise ValueError(f"нет категории «{category}» на портале (вариантов в списке: {len(texts)})")
        options.nth(index).click()
        time.sleep(0.8)
        if self.page.locator("[data-radix-popper-content-wrapper]").count():
            self.page.keyboard.press("Escape")  # если окно позволяет выбрать несколько, закрываем его
        if texts[index] != self.category_text:
            self.log(f"Категория: {texts[index]}")
        self.category_text = texts[index]  # так же она записана в колонке «Категория» выдачи

    def all_categories(self) -> list[str]:
        """Все категории из всплывающего окна (для сверки с categories.py)."""
        self.advanced_open()
        self.page.locator("form label", has_text="Категория дела").locator("xpath=..").locator("button").first.click()
        options = self.page.locator("[data-radix-popper-content-wrapper] [cmdk-item]")
        texts: list[str] = []
        for _ in range(20):  # список подгружается не сразу
            time.sleep(1)
            texts = [" ".join(t.split()) for t in options.all_inner_texts()]
            if len(texts) > 50:
                break
        self.page.keyboard.press("Escape")
        return texts

    def advanced_open(self) -> None:
        """Раскрыть «Расширенный поиск», если он свёрнут (кнопка работает как переключатель)."""
        if not self.page.locator("form label", has_text="Область").first.is_visible():
            self.button("Расширенный поиск").click()
            time.sleep(1)

    def search(self, args, region: str | None = None, court: str = "", result: str | None = None) -> int:
        """Заполнить форму и нажать «Найти». Вернуть число найденных дел (0 — если ничего)."""
        region = args.region if region is None else region
        result = args.result if result is None else result
        self.set_select("Тип производства", args.case_type)
        self.set_select("Учетный год", str(args.year))
        first = self.page.get_by_role("checkbox", name="Первая инстанция")
        if first.get_attribute("aria-checked") != "true":
            first.click()
        self.page.locator("input[name=searchText]").fill(args.keywords)
        category = getattr(args, "category", "")
        if region or result or category or court:
            self.advanced_open()
            if category:
                self.select_category(category)
            if region:
                self.set_select("Область", region)
            if court:
                self.set_select("Судебный орган", court)  # список судов появляется после выбора области
            if result:
                self.set_select("Результат рассмотрения", result)
        # Ждём ответа портала именно на этот поиск: на экране ещё видна прошлая выдача
        # (или надпись «не найдено»), и по ней число дел прочиталось бы неверно.
        with self.page.expect_response(lambda r: "/bank/find" in r.url, timeout=90_000) as response:
            self.button("Найти").click()
        if not response.value.ok:
            raise TimeoutError(f"портал ответил {response.value.status}")
        time.sleep(1.5)
        return self.wait_total()

    def wait_total(self, timeout: float = 40) -> int:
        """Дождаться выдачи: число «Найдено дел» и строки списка; если ничего не нашлось — 0."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            body = self.page.inner_text("body")
            m = re.search(r"Найдено дел:\s*([\d\s]+)", body)
            if m:
                total = int(re.sub(r"\D", "", m.group(1)) or 0)
                if total == 0 or self.page.locator("tbody tr").count():
                    return total
            elif "дело не найдено" in body:  # «По заданным реквизитам дело не найдено»
                return 0
            time.sleep(0.5)
        raise TimeoutError("Список дел не загрузился")

    def options(self, label: str) -> list[str]:
        """Варианты поля формы (суды, результаты), без пустого «Выберите»: обычный список или всплывающий."""
        return self.page.evaluate(OPTIONS_JS, label) or self.popup_options(label)

    def reset(self) -> None:
        self.button("Сбросить").click()
        time.sleep(1.5)

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
        for attempt in range(5):
            try:
                nav.last.click(timeout=15_000)
            except Exception as exc:  # листалка пропала: портал показал ошибку вместо списка
                self.debug_snapshot("no-pager")
                raise PortalStuck(str(exc).splitlines()[0][:120]) from exc
            deadline = time.time() + self.page_wait
            while time.time() < deadline:
                try:
                    rows = self.rows()
                except TimeoutError:  # портал перегружен и не отдал список
                    break
                if rows and rows[0].case_number != previous_first:
                    return True
                time.sleep(1)
            if attempt >= 2:
                wait = self.pause * 10 * (attempt - 1)
                self.log(f"  страница не открылась, жду {wait:.0f} с")
                time.sleep(wait)
        return False


def say(message: str) -> None:
    print(message, flush=True)  # сразу, а не в конце: прогон идёт долго


def jobs(args) -> list[tuple[argparse.Namespace, str]]:
    """Что собирать: одна выборка или категории реестра × годы — каждая в свою папку."""
    if not getattr(args, "categories", ""):
        return [(args, "")]
    from .categories import CATEGORIES, DEFAULT_ORDER
    out = []
    ids = DEFAULT_ORDER if args.categories == "all" else [c.strip() for c in args.categories.split(",") if c.strip()]
    for cid in ids:
        if cid not in CATEGORIES:
            raise SystemExit(f"Нет категории с ID {cid} в sud_parser/categories.py")
        cat = CATEGORIES[cid]
        for year in args.years:
            job = argparse.Namespace(**vars(args))
            job.category, job.case_type, job.year = cat.portal, cat.case_type, year
            job.out = str(Path(args.out) / f"{cid}_{year}")
            out.append((job, f"[{cid} · {year}] {cat.name}"))
    return out


def collect(args, log=say) -> int:
    from playwright.sync_api import sync_playwright

    todo = jobs(args)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR), channel="chrome", headless=False, accept_downloads=True,
            viewport={"width": 1400, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        portal = Portal(page, args.pause, log)
        try:
            portal.wait_login(args.login_wait)  # один вход по ЭЦП на все категории
            portal.open_bank()
            if getattr(args, "show_categories", False):
                texts = portal.all_categories()
                path = Path("data/collected/portal_categories.txt")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(texts), encoding="utf-8")
                log(f"Категорий на портале: {len(texts)} -> {path}")
                if not getattr(args, "categories", ""):
                    todo = []
            for n, (job, title) in enumerate(todo, 1):
                if title:
                    log(f"=== {n}/{len(todo)} {title}")
                out = Path(job.out)
                out.mkdir(parents=True, exist_ok=True)
                (out / "_query.json").write_text(json.dumps(search_body(job), ensure_ascii=False, indent=2),
                                                 encoding="utf-8")
                for attempt in range(3):  # при обрыве сессии — вход заново и та же выборка (журнал пропустит скачанное)
                    manifest = Manifest(out)
                    if manifest.done:
                        log(f"Уже скачано раньше: {manifest.saved} дел, они будут пропущены.")
                    try:
                        if getattr(job, "list_only", False):
                            list_results(portal, out, job)
                        elif job.category:  # с категорией портал листает только 5 страниц — делим поиск
                            download_by_pieces(portal, manifest, out, job)
                        else:
                            log(f"Портал нашёл дел: {portal.search(job)}")
                            walk_results(portal, manifest, out, job)
                        break
                    except KeyboardInterrupt:
                        raise
                    except Exception as exc:  # noqa: BLE001 — сбой портала не должен ронять весь сбор
                        log(f"Остановлено: {str(exc).splitlines()[0][:160]}")
                        portal.debug_snapshot("stopped")
                        try:
                            if not portal.logged_in():
                                portal.relogin()
                            else:
                                portal.open_bank_again()
                        except Exception as exc2:  # noqa: BLE001
                            log(f"Не удалось вернуться к поиску: {str(exc2).splitlines()[0][:160]}")
                            raise
                log(f"Готово: дел с решениями {manifest.saved}. Папка: {out.resolve()}")
        except KeyboardInterrupt:
            log("Остановлено. Повторный запуск продолжит с этого места.")
        except (RuntimeError, TimeoutError, ValueError) as exc:
            log(f"Остановлено: {exc}. Повторный запуск продолжит с этого места.")
        finally:
            ctx.close()
    return 0


LIST_FILE = "_list.csv"
LIST_FIELDS = ["case_number", "date", "court", "result", "category", "page"]
DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}")


def list_row(cells: list[str], page: int) -> dict:
    """Строка выдачи без сторон процесса (там ФИО): номер, дата, суд, результат, категория."""
    first = cells[0] if cells else ""
    date = DATE_RE.search(first)
    return {"case_number": case_number_of(first), "date": date.group(0) if date else "",
            "court": cells[2].strip() if len(cells) > 2 else "",
            "result": cells[3].strip() if len(cells) > 3 else "",
            "category": " ".join(cells[4].split()) if len(cells) > 4 else "", "page": page}


# Когда выбрана категория дела, портал листает выдачу только до 5-й страницы (50 дел): на 6-й он
# сбрасывает результаты. Поэтому большой запрос делим на части: область -> суд -> результат.
PIECE_LIMIT = 50
PIECES_FILE = "_pieces.csv"
UNFILTERED_MAX = 400  # больше — листать без категории слишком долго (40+ страниц), берём первые 50


# Суды, где гражданских дел первой инстанции не бывает: их не перебираем (каждый поиск — запрос к порталу).
_NOT_CIVIL_COURT_RE = re.compile(
    r"Верховный|Кассационн|Упразднённ|Упраздненн|административным\s+правонарушениям|следственн|"
    r"административный\s+суд|^(?!.*Гражданск).*Уголовн|^(?!.*1\s+инстанци).*Апелляционн", re.I)


def court_fits(court: str, case_type: str) -> bool:
    """Нужно ли искать в этом суде: для гражданских дел пропускаем уголовные, административные и вышестоящие суды."""
    return case_type != "CIVIL" or not _NOT_CIVIL_COURT_RE.search(court)


def save_pieces(out: Path, pieces: list[dict]) -> None:
    with (out / PIECES_FILE).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["piece", "found", "listed", "note"])
        w.writeheader()
        w.writerows(pieces)


def split_search(portal: Portal, args, handle, pieces: list[dict], on_change=lambda: None, unfiltered=None) -> None:
    """Искать по частям до 50 дел (область -> суд -> результат) и для каждой части вызвать
    handle(label, found) -> сколько дел из неё взято. Части записываются в pieces.
    unfiltered(label, region, court) — если часть больше 50 и делить нечем (см. ниже)."""

    def piece(region: str, court: str, result: str) -> None:
        label = " / ".join(x for x in (region, court, result) if x) or "весь запрос"
        found = None
        for attempt in range(3):
            try:
                portal.reset()
                found = portal.search(args, region=region, court=court, result=result)
                time.sleep(args.pause)  # портал отвечает 429 на частые поиски
                break
            except Exception as exc:  # в т.ч. таймауты Playwright: у них свой класс ошибки
                if "401" in str(exc) or not portal.logged_in():
                    portal.relogin()
                    continue
                wait = 30 * (attempt + 1)
                portal.log(f"  {label}: поиск не загрузился ({str(exc).splitlines()[0][:120]}); жду {wait} с")
                time.sleep(wait)
                try:
                    portal.open_bank_again()
                except Exception:
                    if not portal.logged_in():
                        portal.relogin()
        if found is None:
            pieces.append({"piece": label, "found": "", "listed": 0, "note": "поиск не загрузился"})
            on_change()
            return
        if found <= PIECE_LIMIT:
            got = handle(label, found) if found else 0
            pieces.append({"piece": label, "found": found, "listed": got, "note": ""})
            portal.log(f"  {label}: найдено {found}, взято {got}")
            on_change()
            return
        # Больше 50: делим на следующем уровне.
        if not region:
            sub = [(r, "", result) for r in portal.options("Область")]
        elif not court and portal.options("Судебный орган"):
            sub = [(region, c, result) for c in portal.options("Судебный орган") if court_fits(c, args.case_type)]
        elif not result:
            sub = [(region, court, r) for r in portal.options("Результат рассмотрения")]
        else:
            sub = []
        if not sub and unfiltered is not None and getattr(args, "category", ""):
            # «Результат рассмотрения» на портале пустой, делить нечем. Но 5 страниц — ограничение только
            # для поиска с категорией: ищем без неё и берём дела нужной категории по колонке выдачи.
            got = unfiltered(label, region, court)
            pieces.append({"piece": label, "found": found, "listed": got, "note": "больше 50: без категории, отбор по колонке"})
            portal.log(f"  {label}: найдено {found}, поиск без категории — взято {got}")
            on_change()
            return
        if not sub:  # делить больше не на что: берём первые 50
            portal.debug_snapshot("no-split")  # чтобы разобраться, почему не разделилось
            got = handle(label, PIECE_LIMIT)
            pieces.append({"piece": label, "found": found, "listed": got, "note": "больше 50, взяты первые 50"})
            portal.log(f"  {label}: найдено {found}, делить дальше нечем — взяты первые {got}")
            on_change()
            return
        portal.log(f"  {label}: найдено {found} — делю на {len(sub)} частей")
        for r, c, res in sub:
            piece(r, c, res)

    piece(args.region, "", args.result)


def list_results(portal: Portal, out: Path, args) -> list[dict]:
    """Только список дел выдачи (без открытия дел и скачивания), с делением запроса на части по 50 дел."""
    rows: dict[str, dict] = {}
    pieces: list[dict] = []

    def save() -> None:  # после каждой страницы: если портал оборвёт, собранное не пропадёт
        with (out / LIST_FILE).open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=LIST_FIELDS + ["piece"])
            w.writeheader()
            w.writerows(rows.values())
        save_pieces(out, pieces)

    def take_pages(label: str, found: int = PIECE_LIMIT) -> int:
        before = len(rows)
        page_no = 1
        while True:
            cells = portal.wait_rows(timeout=60)
            for c in cells:
                r = list_row(c, page_no)
                r["piece"] = label
                rows.setdefault(r["case_number"], r)
            save()
            if page_no * 10 >= PIECE_LIMIT:
                break
            try:
                if not portal.next_page(case_number_of(cells[0][0]) if cells else ""):
                    break
            except PortalStuck as exc:
                portal.log(f"  {label}: страница {page_no + 1} не открылась ({exc})")
                break
            page_no += 1
            time.sleep(args.pause / 2)
        return len(rows) - before

    split_search(portal, args, take_pages, pieces, save)
    found_sum = sum(int(p["found"] or 0) for p in pieces if not p["note"] or p["note"].startswith("больше"))
    portal.log(f"Список: {len(rows)} дел (по частям найдено {found_sum}) -> {out / LIST_FILE}")
    return list(rows.values())


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


def download_by_pieces(portal: Portal, manifest: Manifest, out: Path, args) -> None:
    """Скачать решения всей выдачи, деля поиск на части до 50 дел (обход сброса портала на 6-й странице)."""
    pieces: list[dict] = []

    def take(label: str, found: int) -> int:
        taken, page_no = 0, 1
        while True:
            rows = portal.rows()
            for i, row in enumerate(rows):
                if manifest.saved >= args.limit:
                    return taken
                if row.case_number in manifest.done:
                    continue
                try:
                    status, files = fetch_case(portal, i, row, out, args)
                except RuntimeError as exc:  # портал вернул не ту страницу: эту часть доберём при повторном запуске
                    portal.log(f"  {label}: {exc}; часть прервана")
                    return taken
                manifest.add(row, page_no, status, files)
                portal.log(f"  {row.case_number}: {status}" + (f" ({len(files)} файл.)" if files else ""))
                taken += status == "ok"
                portal.back_to_list()
                time.sleep(args.pause)
            if page_no * 10 >= min(found, PIECE_LIMIT):
                return taken
            try:
                if not portal.next_page(rows[0].case_number if rows else ""):
                    return taken
            except PortalStuck as exc:
                portal.log(f"  {label}: страница {page_no + 1} не открылась ({exc})")
                return taken
            page_no += 1

    def take_without_category(label: str, region: str, court: str) -> int:
        """Суд с >50 делами категории: ищем без категории (так портал листает все страницы) и скачиваем
        только строки, где в колонке «Категория» стоит выбранная категория."""
        want = " ".join(portal.category_text.split()).lower()
        job = argparse.Namespace(**vars(args))
        job.category = ""
        portal.reset()
        total = portal.search(job, region=region, court=court, result="")
        time.sleep(args.pause)
        if total > UNFILTERED_MAX:  # без категории поиск по словам почти ничего не отсеивает (потолок портала 10000)
            portal.log(f"  {label}: без категории найдено {total} — слишком много; беру первые 50 с категорией")
            portal.reset()
            portal.search(args, region=region, court=court, result="")
            time.sleep(args.pause)
            return take(label, PIECE_LIMIT)
        portal.log(f"  {label}: без категории найдено {total}, отбираю «{portal.category_text[:60]}…»")
        taken, page_no = 0, 1
        while True:
            rows = portal.rows()
            for i, row in enumerate(rows):
                if manifest.saved >= args.limit:
                    return taken
                if " ".join(row.category.split()).lower() != want or row.case_number in manifest.done:
                    continue
                try:
                    status, files = fetch_case(portal, i, row, out, args)
                except RuntimeError as exc:
                    portal.log(f"  {label}: {exc}; часть прервана")
                    return taken
                manifest.add(row, page_no, status, files)
                portal.log(f"  {row.case_number}: {status}" + (f" ({len(files)} файл.)" if files else ""))
                taken += status == "ok"
                portal.back_to_list()
                time.sleep(args.pause)
            if page_no * 10 >= total:
                return taken
            try:
                if not portal.next_page(rows[0].case_number if rows else ""):
                    portal.log(f"  {label}: страница {page_no + 1} не открылась")
                    return taken
            except PortalStuck as exc:
                portal.log(f"  {label}: страница {page_no + 1} не открылась ({exc})")
                return taken
            page_no += 1
            time.sleep(args.pause / 2)

    split_search(portal, args, take, pieces, lambda: save_pieces(out, pieces), take_without_category)
    found_sum = sum(int(p["found"] or 0) for p in pieces if not p["note"] or p["note"].startswith("больше"))
    portal.log(f"Найдено по частям: {found_sum}; дел с решениями в папке: {manifest.saved}")


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
    p.add_argument("--keywords", default="объединение собственников имущества",
                   help="слова для поиска, как в поле «Поиск по ключевому слову»")
    p.add_argument("--year", type=int, default=datetime.now().year, help="учетный год")
    p.add_argument("--case-type", default="CIVIL", help="CIVIL (гражданские), APPK (административные) и т. п.")
    p.add_argument("--region", default="", help="область как на портале, например «город Астана»")
    p.add_argument("--result", default="", help="результат рассмотрения как на портале")
    p.add_argument("--category", default="", help="категория дела как на портале (можно часть названия)")
    p.add_argument("--categories", default="",
                   help="ID категорий реестра через запятую (sud_parser/categories.py), например 47,2272")
    p.add_argument("--years", default="", help="годы для --categories, например 2025,2026")
    p.add_argument("--show-categories", action="store_true",
                   help="только выписать все категории портала в data/collected/portal_categories.txt")
    p.add_argument("--list-only", action="store_true",
                   help="только список дел выдачи (_list.csv), без скачивания решений")
    p.add_argument("--limit", type=int, default=None,
                   help="сколько дел с решениями скачать (по умолчанию 50; с --categories — все)")
    p.add_argument("--max-pages", type=int, default=200)
    p.add_argument("--pause", type=float, default=4.0, help="пауза между делами, секунд")
    p.add_argument("--login-wait", type=int, default=10, help="сколько минут ждать входа по ЭЦП")
    p.add_argument("--out", default="", help="папка для решений (по умолчанию data/collected/<дата>)")
    args = p.parse_args(argv)
    args.case_type = CASE_TYPES.get(args.case_type.lower(), args.case_type)
    args.years = [int(y) for y in args.years.split(",") if y.strip()] or [args.year]
    if args.limit is None:  # по категориям — всё, что найдётся; иначе первые 50 дел
        args.limit = 10**9 if args.categories else 50
    if not args.out:
        args.out = str(Path("data/collected") / ("categories" if args.categories else f"{datetime.now():%Y-%m-%d_%H-%M}"))
    return collect(args)


if __name__ == "__main__":
    sys.exit(main())
