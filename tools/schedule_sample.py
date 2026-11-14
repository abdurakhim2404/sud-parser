"""Исследование: кто выступает истцом в графике заседаний portal-sot.kz.

Шаг 1 (сбор):   python tools/schedule_sample.py collect
    Скачивает графики выбранных судов за последние N рабочих дней, по одному запросу на суд и день,
    и сохраняет сырые ответы в data/schedule_sample.json (папка data/ не попадает в git).

Шаг 2 (подсчёт): python tools/schedule_sample.py report
    Считает по сохранённому файлу, к сайту не обращается — результат можно пересчитать и перепроверить.

Важно: портал отдаёт не больше 50 дел на один запрос (суд + день), поэтому это ВЫБОРКА, а не все дела.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sud_parser.http_client import PoliteClient  # noqa: E402
from sud_parser.sources.portal_sot_kz import API, _api_data  # noqa: E402

OUT = Path("data/schedule_sample.json")
COURTS = {
    "197142": "Межрайонный суд по гражданским делам г. Астаны",
    "197119": "СМЭС г. Астаны (экономический)",
}
WORKING_DAYS = 20

# Строгие признаки: организация, которая управляет многоквартирным домом
HOUSING = re.compile(
    r"\bОСИ\b|ОБЪЕДИНЕНИ[ЕЯ] СОБСТВЕННИКОВ ИМУЩЕСТВА|\bМИБ\b|М[ҮУ]Л[ІI]К ИЕЛЕР[ІI]Н[ІI][ҢН] Б[ІI]РЛЕСТ[ІI]Г"
    r"|\bП?КСК\b|\bКСП\b|\bПКС[КП]?\b|КООПЕРАТИВ\w* СОБСТВЕННИКОВ|П[ӘА]ТЕР ИЕЛЕР"
    r"|\bПТ\b|ПРОСТОЕ ТОВАРИЩЕСТВО|ЖАЙ СЕР[ІI]КТЕСТ[ІI]К"
)
# Широкие признаки: возможно, связано с домом — эти названия нужно просмотреть глазами
MAYBE = re.compile(r"УПРАВЛЯЮЩ|СЕРВИС|ЖИЛ|КОНДОМИНИУМ|\bДОМ|[ҮУ]Й\b|\bЖК\b|КОММУНАЛ|ЭКСПЛУАТАЦ|ТҰРҒЫН|ТУРГЫН")
# Признаки юридического лица (чтобы не печатать имена людей)
ORG = re.compile(r"[\"«“]|\b(ТОО|АО|ЖШС|АҚ|ГУ|РГУ|КГУ|ГКП|РГП|КГП|ОО|ОФ|ОЮЛ|НАО|ПК|ОСИ|МИБ|КСК|ПКСК|КСП|ПТ|ММ|КММ|РММ)\b")


def norm(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().upper().replace("Ё", "Е")


def last_working_days(n: int, today: date) -> list[date]:
    days, d = [], today
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return sorted(days)


def collect() -> None:
    client = PoliteClient(min_interval=2.0)
    days = last_working_days(WORKING_DAYS, date.today())
    rows = []
    try:
        for court in COURTS:
            for day in days:
                url = f"{API}/schedule/find/{court}/FIRSTINSTANCE/CIVIL/{day.isoformat()}"
                data = _api_data(client.get(url))
                rows.append({"court": court, "date": day.isoformat(), "items": data})
                print(f"{court} {day}: записей {len(data)}, дел {len({x.get('caseNumber') for x in data})}")
    finally:
        client.close()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print("сохранено:", OUT)


def report() -> None:
    rows = json.loads(OUT.read_text(encoding="utf-8"))
    print(f"запросов: {len(rows)}, период: {rows[0]['date']} … {max(r['date'] for r in rows)}")
    per_request = Counter(len({x.get("caseNumber") for x in r["items"]}) for r in rows)
    print("сколько дел вернул один запрос -> сколько таких запросов:", sorted(per_request.items()))

    for court, court_name in COURTS.items():
        cases: dict[str, dict] = {}  # номер дела -> запись (одно дело считаем один раз)
        for r in rows:
            if r["court"] == court:
                for x in r["items"]:
                    if x.get("caseNumber"):
                        cases[x["caseNumber"]] = x
        strict_pl, strict_def, maybe_names, org_pl = [], [], Counter(), Counter()
        for x in cases.values():
            pl = [norm(p.get("name") or "") for p in x.get("applicants") or []]
            df = [norm(p.get("name") or "") for p in x.get("defendants") or []]
            if any(HOUSING.search(n) for n in pl):
                strict_pl.append(x)
            if any(HOUSING.search(n) for n in df):
                strict_def.append(x)
            for n in pl:
                if ORG.search(n):
                    org_pl[n] += 1
                    if MAYBE.search(n) and not HOUSING.search(n):
                        maybe_names[n] += 1
        total = len(cases)
        print(f"\n=== {court_name} ({court}) ===")
        print(f"уникальных дел в выборке: {total}")
        print(f"истец — ОСИ/КСК/ПТ (строгие признаки): {len(strict_pl)} ({len(strict_pl) / total:.1%})")
        print(f"ответчик — ОСИ/КСК/ПТ: {len(strict_def)} ({len(strict_def) / total:.1%})")
        print("названия истцов со строгими признаками:")
        for n, k in Counter(norm(p["name"]) for x in strict_pl for p in x["applicants"] if HOUSING.search(norm(p["name"]))).most_common():
            print(f"   {k} × {n}")
        print("названия ответчиков со строгими признаками:")
        for n, k in Counter(norm(p["name"]) for x in strict_def for p in x["defendants"] if HOUSING.search(norm(p["name"]))).most_common():
            print(f"   {k} × {n}")
        print("истцы-организации с широкими признаками (просмотреть глазами):")
        for n, k in maybe_names.most_common():
            print(f"   {k} × {n}")
        print("топ-15 истцов-организаций:")
        for n, k in org_pl.most_common(15):
            print(f"   {k} × {n}")


if __name__ == "__main__":
    {"collect": collect, "report": report}[sys.argv[1] if len(sys.argv) > 1 else "report"]()
