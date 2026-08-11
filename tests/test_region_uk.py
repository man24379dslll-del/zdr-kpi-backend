"""
"Регион УК" / "Выходы на Пики" — разбиение группы "операторы без
супервизора" по префиксу ФИО ("ЗДР" -> Регион УК, остальное -> Пики) и
урезанный набор категорий (c1/lk/time) для "Регион УК" в total_score.
Тест собирает небольшой реалистичный xlsx и проверяет и парсинг, и расчёт.
"""
import io

import pandas as pd

from app.services.excel_parsing import is_na_row, parse_weekly_rating_excel
from app.services.rating_engine import RatingCategory
from app.services.weekly_rating import compute_weekly_rating

FIO = "ФИО"
STATUS = "Статус (уровень)"
BONUS075 = "0.75% за офор."
BONUS2 = "2% за дост."
C1_COUNT = "Первый контакт: кол-во"
C1_SUM = "Первый контакт: сумма"
C1_CHECK = "Первый контакт: ср.чек"
C1_CONV = "Первый контакт: конверсия, %"
C1_PC = "Первый контакт: сумма с контакта"
LK_COUNT = "ЛК: кол-во"
LK_SUM = "ЛК: сумма"
LK_CHECK = "ЛК: ср.чек"
LK_CONV = "ЛК: конверсия, %"
LK_PC = "ЛК: сумма с контакта"
RADIO_COUNT = "Радио + ТВ: кол-во"
RADIO_SUM = "Радио + ТВ: сумма"
RADIO_CHECK = "Радио + ТВ: ср.чек"
RADIO_CONV = "Радио + ТВ: конверсия, %"
RADIO_PC = "Радио + ТВ: сумма с контакта"
INET_SUM = "Интернет: сумма"
INET_CHECK = "Интернет: ср.чек"
INET_CONV = "Интернет: конверсия, %"
INET_PC = "Интернет: сумма с контакта"
TIME_PC = "Время/контакт без звонка, мин"  # категория "время" считается БЕЗ звонка, не "Время/контакт, мин"
ERRORS_PCT = "Ошибок, %"

CATEGORIES = [
    RatingCategory(key="c1", label="1 обращение", source_column="c1_per_contact", weight=3, direction="desc", sort_order=1),
    RatingCategory(key="lk", label="ЛК", source_column="lk_per_contact", weight=1.5, direction="desc", sort_order=2),
    RatingCategory(key="channel", label="Радио+ТВ / Интернет", source_column="ch_per_contact", weight=2.5, direction="desc", sort_order=3),
    RatingCategory(key="time", label="Время/контакт", source_column="time_per_contact", weight=1, direction="asc", sort_order=4),
    RatingCategory(key="errors", label="% ошибок", source_column="errors_pct", weight=1, direction="asc", sort_order=5),
]


def _row(fio, c1_pc, lk_pc, ch_pc, time_pc, errors_pct, lk_cards=1, lk_conv=10, c1_sum=1000):
    return {
        FIO: fio,
        STATUS: "",
        BONUS075: 0,
        BONUS2: 0,
        C1_COUNT: 10,
        C1_SUM: c1_sum,
        C1_CHECK: 100,
        C1_CONV: 20,
        C1_PC: c1_pc,
        LK_COUNT: lk_cards,
        LK_SUM: 500,
        LK_CHECK: 100,
        LK_CONV: lk_conv,
        LK_PC: lk_pc,
        RADIO_COUNT: 3,
        RADIO_SUM: 1000,
        RADIO_CHECK: 100,
        RADIO_CONV: 10,
        RADIO_PC: ch_pc,
        INET_SUM: 0,
        INET_CHECK: 0,
        INET_CONV: 0,
        INET_PC: 0,
        TIME_PC: time_pc,
        ERRORS_PCT: errors_pct,
    }


def _group_row(label: str) -> dict:
    return {FIO: f"ГРУППА: {label}"}


ROWS = [
    _group_row("операторы без супервизора"),
    _row("ЗДР Федотова М. Д.", 100, 50, 200, 20, 1),   # Регион УК
    _row("ЗДР Шпинь В. В.", 90, 40, 180, 25, 2),        # Регион УК
    _row("ПП Козлов А. А.", 80, 30, 160, 30, 3),        # Пики
    _row("Увеличители Орлов О. О.", 70, 20, 140, 35, 4),  # Пики
]


def _build_excel_bytes(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def test_region_uk_prefix_splits_into_two_virtual_groups():
    raw = _build_excel_bytes(ROWS)
    employees = parse_weekly_rating_excel(raw)
    by_fio = {e["fio"]: e for e in employees}

    assert by_fio["ЗДР Федотова М. Д."]["supervisor"] == "операторы без супервизора"
    assert by_fio["ЗДР Федотова М. Д."]["is_region_uk"] is True
    assert by_fio["ЗДР Шпинь В. В."]["supervisor"] == "операторы без супервизора"
    assert by_fio["ЗДР Шпинь В. В."]["is_region_uk"] is True

    assert by_fio["ПП Козлов А. А."]["supervisor"] == "операторы без супервизора [Пики]"
    assert by_fio["ПП Козлов А. А."]["is_region_uk"] is False
    assert by_fio["Увеличители Орлов О. О."]["supervisor"] == "операторы без супервизора [Пики]"
    assert by_fio["Увеличители Орлов О. О."]["is_region_uk"] is False


def test_normal_groups_are_unaffected_by_region_uk_logic():
    raw = _build_excel_bytes([_group_row("Супервайзер - Иванов И.И."), _row("Петров П.П.", 50, 50, 50, 50, 5)])
    employees = parse_weekly_rating_excel(raw)
    assert employees[0]["supervisor"] == "Супервайзер - Иванов И.И."
    assert employees[0]["is_region_uk"] is False


def test_region_uk_total_score_excludes_channel_and_errors():
    raw = _build_excel_bytes(ROWS)
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    by_fio = {r.fio: r for r in results}

    fedotova = by_fio["ЗДР Федотова М. Д."]
    # Места по каналу/ошибкам всё равно посчитаны (нужны тиру ЛК) ...
    assert "channel" in fedotova.places
    assert "errors" in fedotova.places
    # ... но НЕ идут в total_score
    assert set(fedotova.scores.keys()) == {"c1", "lk", "time"}
    assert fedotova.total_score == fedotova.scores["c1"] + fedotova.scores["lk"] + fedotova.scores["time"]

    kozlov = by_fio["ПП Козлов А. А."]  # Пики -> полный набор категорий
    assert set(kozlov.scores.keys()) == {"c1", "lk", "channel", "time", "errors"}


def test_region_uk_and_peaks_get_separate_ladder_groups():
    raw = _build_excel_bytes(ROWS)
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    by_fio = {r.fio: r for r in results}

    # Обе виртуальные группы участвуют в ЛГ как обычные супервайзерские группы
    for fio in ("ЗДР Федотова М. Д.", "ЗДР Шпинь В. В.", "ПП Козлов А. А.", "Увеличители Орлов О. О."):
        assert by_fio[fio].tier is not None
        assert by_fio[fio].coefficient is not None
