"""Окно анализа судебной практики в браузере.

    python -m streamlit run sud_parser/practice/app.py      (или двойной щелчок по interface.bat)

Локально всё работает на этом компьютере: файлы решений никуда не отправляются.
На хостинге (Streamlit Community Cloud) по умолчанию показываются обезличенные демо-данные (demo/decisions.json).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # streamlit запускает файл как скрипт, без пакета
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from sud_parser.practice.demo import DEMO_FILE, load as _load_demo  # noqa: E402
from sud_parser.practice.analyze import (  # noqa: E402
    MAIN_OUTCOMES, PracticeResult, analyze_folder, analyze_folders, article_table, court_key, court_names,
    money_stats, osi_pays_stats, osi_result, outcome_table, side_group,
)
from sud_parser.practice.extract import UNKNOWN, display_party  # noqa: E402
from sud_parser.practice.reader import SUPPORTED  # noqa: E402
from sud_parser.practice.report import RULE_NOTE, SMALL_SAMPLE, write_practice_report  # noqa: E402

st.set_page_config(page_title="Судебная практика ОСИ", page_icon="⚖️", layout="wide")


# --- загрузка ---------------------------------------------------------------------------------

DEMO_SOURCE = "демо-данные (обезличено)"


@st.cache_resource
def load_demo():
    return _load_demo(DEMO_FILE)


def analyze_uploads(files) -> PracticeResult:
    with tempfile.TemporaryDirectory() as tmp:
        used: set[str] = set()
        for f in files:
            name = Path(f.name).name
            stem, suffix = Path(name).stem, Path(name).suffix
            n = 1
            while name.lower() in used:  # одинаковые имена из разных папок
                n += 1
                name = f"{stem} ({n}){suffix}"
            used.add(name.lower())
            (Path(tmp) / name).write_bytes(f.getvalue())
        return analyze_folder(Path(tmp))


def known_folders() -> dict[str, Path]:
    """Папки с решениями на этом компьютере: результаты сборщика (data/collected/…) и папка sud-decisions
    рядом с проектом. Подпись — имя папки и число файлов."""
    roots = [ROOT / "data" / "collected", ROOT.parent / "sud-decisions"]
    candidates = []
    for root in roots:
        if root.is_dir():
            candidates += [root, *sorted(p for p in root.iterdir() if p.is_dir())]
    found = {}
    for folder in candidates:
        count = sum(1 for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED
                    and not p.name.startswith(("~$", "_")))
        if count:
            found[f"{folder.parent.name}/{folder.name} — {count} файлов"] = folder
    return found


def excel_bytes(result: PracticeResult, source: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        return write_practice_report(result, tmp, source=source).read_bytes()


# --- таблицы ----------------------------------------------------------------------------------

def outcome_df(decisions, key, title: str) -> pd.DataFrame:
    rows = []
    for r in outcome_table(decisions, key):
        rows.append({
            title: r.label,
            **{o: r.counts[o] for o in MAIN_OUTCOMES},
            "Прочее": r.total - sum(r.counts[o] for o in MAIN_OUTCOMES),
            "Всего": r.total,
            "ОСИ выиграло / частично / проиграло": f"{r.won} / {r.partly} / {r.lost}" if r.known else "—",
            "Доля полных побед ОСИ": round(100 * r.win_share) if r.known else None,
        })
    return pd.DataFrame(rows)


def show_outcomes(df: pd.DataFrame) -> None:
    st.dataframe(df, hide_index=True, width="stretch", column_config={
        "Доля полных побед ОСИ": st.column_config.ProgressColumn(format="%d%%", min_value=0, max_value=100),
    })


def won_label(d) -> str:
    return osi_result(d) or "—"


def decisions_df(decisions) -> pd.DataFrame:
    return pd.DataFrame([{
        "Номер дела": d.case_number,
        "Дата": d.date,
        "Суд": d.court,
        "Роль ОСИ": d.osi_role,
        "Против кого": d.opponent or "—",
        "Предмет спора": d.topic or "—",
        "Исход": d.outcome,
        "Встречный иск": d.counter_outcome or "—",
        "Для ОСИ": won_label(d),
        "В пользу ОСИ, ₸": d.amounts.total,
        "С ОСИ, ₸": d.osi_pays.total,
        "Предупреждения": "; ".join(d.warnings),
        "Файл": d.file,
    } for d in decisions])


def money(value: float) -> str:
    return f"{value:,.0f} ₸".replace(",", " ")


# --- страница ---------------------------------------------------------------------------------

st.title("Анализ судебной практики по спорам ОСИ")
st.caption("Программа читает решения судов РК (.docx, .rtf, .txt; на русском или казахском) и по каждому "
           "определяет стороны, предмет спора, исход, взысканные суммы и статьи законов, а потом считает, "
           "в каких спорах и как часто выигрывает ОСИ.")
with st.expander("Как пользоваться"):
    st.markdown(
        "1. **Демо-данные** открываются сразу: 204 решения из Банка судебных актов portal-sot.kz, уже разобранные "
        "программой. ФИО физлиц заменены инициалами, самих текстов решений здесь нет.\n"
        "2. Вкладка **«Сводка»** — кто с кем судится и чем закончилось, по предмету спора, по судам, деньги.\n"
        "3. **«Решения»** — таблица с фильтрами; ниже можно выбрать одно дело и посмотреть, что программа из него "
        "извлекла. Номер дела можно найти на портале и сверить.\n"
        "4. **«Нормы права»** — какие статьи применяют суды; **«Проверить вручную»** — где программа не уверена.\n"
        "5. Кнопка **«Скачать отчёт Excel»** — то же самое в виде таблицы.\n"
        "6. **«Загрузить файлы»** — можно перетащить свои решения (.docx), они будут разобраны так же. "
        "На сайте файлы обрабатываются на сервере Streamlit (США), а не на вашем компьютере: "
        "для проверки подойдёт одно-два решения, массово решения с персональными данными сюда не загружайте.\n\n"
        "Ограничения: 147 решений собраны подряд по порядку выдачи портала (не случайно, почти половина — Астана); "
        "темы споров и правило «ОСИ выиграло» составлены разработчиком и юристом не проверены.")

modes = []
if DEMO_FILE.exists():
    modes.append("Демо-данные")
modes.append("Загрузить файлы")
# На хостинге (переменная SUD_PARSER_HOSTED в настройках приложения) папок компьютера нет.
if not os.environ.get("SUD_PARSER_HOSTED"):
    if known_folders():
        modes.append("Готовые папки")
    modes.append("Папка на компьютере")
source_mode = st.radio("Откуда взять решения", modes, horizontal=True)
if source_mode == "Демо-данные":
    if st.session_state.get("source") != DEMO_SOURCE:
        st.session_state.result, demo_note = load_demo()
        st.session_state.source = DEMO_SOURCE
    st.caption(load_demo()[1])
elif source_mode == "Готовые папки":
    known = known_folders()
    if not known:
        st.info("Готовых папок нет. Соберите решения сборщиком (python -m sud_parser.collect) "
                "или выберите другой способ.")
    labels = list(known)
    chosen = st.multiselect("Папки с решениями (можно несколько: одно дело из разных папок считается один раз)",
                            labels, default=labels)
    if st.button("Разобрать", type="primary", disabled=not chosen):
        with st.spinner("Разбираю решения…"):
            st.session_state.result = analyze_folders([known[c] for c in chosen])
            st.session_state.source = "; ".join(str(known[c]) for c in chosen)
elif source_mode == "Загрузить файлы":
    if os.environ.get("SUD_PARSER_HOSTED"):
        st.warning(
            "**Персональные данные.** В решениях есть ФИО, адреса и ИИН людей. На этом сайте загруженные файлы "
            "обрабатываются на сервере Streamlit (США), а не на вашем компьютере. Сами файлы не сохраняются, "
            "а в таблицах ФИО заменяются инициалами, но файлы всё равно передаются на сервер. Чтобы проверить, "
            "как программа разбирает решение, загрузите одно-два. Для работы с большим количеством решений "
            "запускайте программу на своём компьютере (interface.bat).")
    uploads = st.file_uploader("Перетащите файлы решений сюда", accept_multiple_files=True,
                               type=[s.lstrip(".") for s in SUPPORTED])
    if st.button("Разобрать", type="primary", disabled=not uploads):
        with st.spinner(f"Разбираю {len(uploads)} файлов…"):
            st.session_state.result = analyze_uploads(uploads)
            st.session_state.source = f"загружено файлов: {len(uploads)}"
else:
    folder = st.text_input("Путь к папке", placeholder=r"C:\Users\...\sud-decisions")
    if st.button("Разобрать", type="primary", disabled=not folder):
        path = Path(folder.strip().strip('"'))
        if not path.is_dir():
            st.error(f"Папка не найдена: {path}")
        else:
            with st.spinner("Разбираю решения…"):
                st.session_state.result = analyze_folder(path)
                st.session_state.source = str(path)

result: PracticeResult | None = st.session_state.get("result")
if result is None:
    st.stop()

decisions = result.decisions
n = len(decisions)
flagged = [d for d in decisions if d.warnings or d.outcome == UNKNOWN]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Файлов", result.files_total)
c2.metric("Решений в анализе", n)
c3.metric("Исключено и не прочитано", len(result.excluded) + len(result.errors))
c4.metric("Проверить вручную", len(flagged))

st.download_button("Скачать отчёт Excel", excel_bytes(result, st.session_state.source),
                   file_name="practice_report.xlsx", type="primary",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

if n == 0:
    st.warning("Среди файлов нет решений по существу.")
    st.stop()
if n < SMALL_SAMPLE:
    st.info(f"Решений меньше {SMALL_SAMPLE}: проценты описывают только эту выборку, а не всю практику судов.")

tab_sum, tab_list, tab_laws, tab_check, tab_excl = st.tabs(
    ["Сводка", "Решения", "Нормы права", f"Проверить вручную ({len(flagged)})", "Исключено"])

with tab_sum:
    st.subheader("Кто с кем судится и чем закончилось")
    show_outcomes(outcome_df(decisions, side_group, "Стороны спора"))
    counter = sum(1 for d in decisions if d.counter_outcome)
    if counter:
        st.caption(f"Встречный иск был в {counter} решениях. Здесь везде исход основного иска.")
    st.caption(RULE_NOTE)

    st.subheader("По предмету спора")
    show_outcomes(outcome_df(decisions, lambda d: d.topic or "—", "Предмет спора"))

    names = court_names(decisions)
    with st.expander("По судам"):
        show_outcomes(outcome_df(decisions, lambda d: names.get(court_key(d), d.court or "—"), "Суд"))
    with st.expander("По порядку рассмотрения"):
        show_outcomes(outcome_df(decisions, lambda d: d.procedure or "не определён", "Порядок"))

    left, right = st.columns(2)
    with left:
        st.subheader("Взыскано в пользу ОСИ")
        m = money_stats(decisions)
        if m:
            st.write(f"Решений со взысканием долга: **{m.decisions}**")
            st.write(f"Долг: всего **{money(m.principal_total)}**, медиана {money(m.principal_median)}, "
                     f"от {money(m.principal_min)} до {money(m.principal_max)}")
            st.write(f"Неустойка: {money(m.penalty_total)} · госпошлина: {money(m.state_fee_total)} · "
                     f"представитель: {money(m.lawyer_total)} · прочее: {money(m.other_total)}")
        else:
            st.write("Нет решений со взысканием долга в пользу ОСИ.")
    with right:
        st.subheader("Взыскано с самого ОСИ")
        p = osi_pays_stats(decisions)
        if p:
            st.write(f"Решений: **{p.decisions}**, всего **{money(p.total)}**")
            st.write(f"Из них представитель: {money(p.lawyer_total)} · госпошлина: {money(p.state_fee_total)}")
        else:
            st.write("Нет решений, где деньги взысканы с ОСИ.")

with tab_list:
    df = decisions_df(decisions)
    f1, f2, f3 = st.columns(3)
    roles = f1.multiselect("Роль ОСИ", sorted(df["Роль ОСИ"].unique()))
    topics = f2.multiselect("Предмет спора", sorted(df["Предмет спора"].unique()))
    outcomes = f3.multiselect("Исход", sorted(df["Исход"].unique()))
    shown = df
    if roles:
        shown = shown[shown["Роль ОСИ"].isin(roles)]
    if topics:
        shown = shown[shown["Предмет спора"].isin(topics)]
    if outcomes:
        shown = shown[shown["Исход"].isin(outcomes)]
    st.caption(f"Показано {len(shown)} из {len(df)}")
    st.dataframe(shown, hide_index=True, width="stretch", column_config={
        "Дата": st.column_config.DateColumn(format="DD.MM.YYYY"),
        "В пользу ОСИ, ₸": st.column_config.NumberColumn(format="%.0f"),
        "С ОСИ, ₸": st.column_config.NumberColumn(format="%.0f"),
    })

    st.subheader("Одно решение подробно")
    by_label = {f"{d.case_number or '—'} · {d.file}": d for d in decisions}
    d = by_label[st.selectbox("Решение", list(by_label))]
    a, b = st.columns(2)
    with a:
        day = f"{d.date:%d.%m.%Y}" if d.date else "—"
        st.write(f"**Суд:** {d.court or '—'}  \n**Судья:** {d.judge or '—'}  \n**Дата:** {day}")
        st.write("**Истцы:** " + ("; ".join(display_party(x) for x in d.plaintiffs) or "—"))
        st.write("**Ответчики:** " + ("; ".join(display_party(x) for x in d.defendants) or "—"))
        st.write(f"**Предмет спора:** {d.topic or '—'}")
        st.write(f"**Требования:** {d.masked(d.claim[:600]) or '—'}")
    with b:
        st.write(f"**Исход:** {d.outcome}" + (f"  \n**Встречный иск:** {d.counter_outcome}" if d.counter_outcome else ""))
        st.write(f"**Резолютивная часть:** {d.masked(d.outcome_text[:600]) or '—'}")
        st.write(f"**В пользу ОСИ:** {money(d.amounts.total)} · **с ОСИ:** {money(d.osi_pays.total)}")
        laws = [f"{c.law} ст. {c.article}" for c in d.citations if not c.procedural]
        st.write("**Нормы права:** " + ("; ".join(laws) or "—"))
        for w in d.warnings:
            st.warning(w)

with tab_laws:
    procedural = st.toggle("Показать процессуальные статьи (ГПК)")
    st.dataframe(pd.DataFrame([{
        "Закон": r.citation.law, "Статья": r.citation.article, "Решений": r.decisions,
        **{o: r.outcomes[o] for o in MAIN_OUTCOMES},
    } for r in article_table(decisions, procedural=procedural)]), hide_index=True, width="stretch")
    unresolved = [(d.case_number, d.masked(frag)) for d in decisions for frag in d.unresolved_citations]
    if unresolved:
        with st.expander(f"Ссылки, где закон не назван ({len(unresolved)})"):
            st.dataframe(pd.DataFrame(unresolved, columns=["Номер дела", "Фрагмент текста"]),
                         hide_index=True, width="stretch")

with tab_check:
    if flagged:
        st.caption("Здесь программа не уверена. Откройте эти решения и проверьте глазами.")
        st.dataframe(pd.DataFrame([{
            "Номер дела": d.case_number, "Исход": d.outcome,
            "Что не так": "; ".join(d.warnings) or "исход не определён", "Файл": d.file,
        } for d in flagged]), hide_index=True, width="stretch")
    else:
        st.success("Все решения разобраны без предупреждений.")

with tab_excl:
    rows = [{"Файл": e.file, "Номер дела": e.case_number, "Причина": e.reason} for e in result.excluded]
    rows += [{"Файл": name, "Номер дела": "", "Причина": f"не прочитан: {err}"} for name, err in result.errors]
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.write("Ничего не исключено.")
