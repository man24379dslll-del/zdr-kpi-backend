"""
Сектор №2 — 3 обычные группы супервайзеров (Курилова/Бровкова/Басараб).
В ОТЛИЧИЕ от Сектора 1: ЛК считается ОБЫЧНО (вес 1.5, без исключений,
без форсированного 1-го места) — по прямому запросу заказчика урезание
веса ЛК для Сектора 2 не нужно. Общее с Сектором 1 — только 2 правила:
статус "Новичок" не исключает из официального места, и суженный
диапазон ЛГ (5 тиров, 1.3...1.0, вместо обычных 10, 1.4...0.25).
"""
import io

import pandas as pd

from app.services.excel_parsing import is_na_row, parse_weekly_rating_excel
from app.services.group_naming import SECTOR_2_SUPERVISORS
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
TIME_PC = "Время/контакт без звонка, мин"
ERRORS_PCT = "Ошибок, %"

CATEGORIES = [
    RatingCategory(key="c1", label="1 обращение", source_column="c1_per_contact", weight=3, direction="desc", sort_order=1),
    RatingCategory(key="lk", label="ЛК", source_column="lk_per_contact", weight=1.5, direction="desc", sort_order=2),
    RatingCategory(key="channel", label="Радио+ТВ / Интернет", source_column="ch_per_contact", weight=2.5, direction="desc", sort_order=3),
    RatingCategory(key="time", label="Время/контакт", source_column="time_per_contact", weight=1, direction="asc", sort_order=4),
    RatingCategory(key="errors", label="% ошибок", source_column="errors_pct", weight=1, direction="asc", sort_order=5),
]

KURILOVA = "Супервайзер - Курилова Марина Вадимовна"
assert KURILOVA in SECTOR_2_SUPERVISORS


def _row(fio, c1_pc, lk_pc, ch_pc, time_pc, errors_pct, lk_cards=1, lk_conv=10, c1_sum=1000, status=""):
    return {
        FIO: fio,
        STATUS: status,
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


def _build_excel_bytes(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def test_sector2_lk_counts_normally_not_zeroed():
    # Контроль: в отличие от Сектора 1, ЛК для Сектора 2 считается как у
    # обычных сотрудников — полный вес 1.5, входит в total_score без
    # исключений/форсированного места.
    raw = _build_excel_bytes([
        _group_row(KURILOVA),
        _row("Сотрудник А", 100, 50, 200, 20, 1),
        _row("Сотрудник Б", 60, 90, 120, 45, 8),  # хуже c1, но ЛУЧШЕ ЛК
    ])
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    by_fio = {r.fio: r for r in results}

    a = by_fio["Сотрудник А"]
    b = by_fio["Сотрудник Б"]
    assert "lk" in a.scores and "lk" in b.scores  # не урезано, как у Сектора 1
    assert a.scores["lk"] == a.places["lk"] * 1.5
    assert b.scores["lk"] == b.places["lk"] * 1.5
    # Место по ЛК НЕ форсировано к 1 для обоих одновременно (реальный расчёт)
    assert {a.places["lk"], b.places["lk"]} == {1, 2}


def test_sector2_novice_gets_real_place_and_tier_not_na():
    # Та же схема, что у Сектора 1: статус "Новичок" сам по себе больше не
    # исключает из официального места.
    raw = _build_excel_bytes([
        _group_row(KURILOVA),
        _row("Хороший Новичок", 100, 50, 200, 20, 1, status="Новичок, 1-й уровень"),
        _row("Средний Новичок", 60, 15, 120, 45, 8, status="Новичок, 1-й уровень"),
    ])
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    by_fio = {r.fio: r for r in results}

    good = by_fio["Хороший Новичок"]
    weak = by_fio["Средний Новичок"]
    assert good.is_na is False
    assert good.final_place == 1
    assert good.tier == 1
    assert good.coefficient == 1.3  # верхняя граница узкой шкалы
    assert weak.is_na is False
    assert weak.final_place == 2


def test_sector2_novice_with_zero_activity_is_still_na():
    raw = _build_excel_bytes([
        _group_row(KURILOVA),
        _row("Пустышкин Новичок", 0, 0, 0, 20, 1, c1_sum=0, status="Новичок, 1-й уровень"),
    ])
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    r = results[0]
    assert r.is_na is True
    assert r.final_place is None


def test_sector2_uses_5_tiers_with_narrow_coefficient_range():
    # 10 человек, строго убывающий c1_pc -> final_place 1..10, по 2
    # человека на каждый из 5 тиров.
    rows = [_group_row(KURILOVA)]
    for i in range(10):
        rows.append(_row(f"Сотрудник {i}", 100 - i * 10, 50, 100, 20, 1))
    raw = _build_excel_bytes(rows)
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    by_place = {r.final_place: r for r in results}

    expected_tier_by_place = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3, 7: 4, 8: 4, 9: 5, 10: 5}
    expected_coefficient_by_tier = {1: 1.3, 2: 1.2, 3: 1.1, 4: 1.05, 5: 1.0}
    for place, expected_tier in expected_tier_by_place.items():
        r = by_place[place]
        assert r.tier == expected_tier
        assert r.coefficient == expected_coefficient_by_tier[expected_tier]

    assert all(r.tier <= 5 for r in results)
    assert all(1.0 <= r.coefficient <= 1.3 for r in results)


def test_normal_group_is_unaffected_by_sector2_logic():
    # Контроль: вне Сектора 2 (и Сектора 1) — всё как раньше: новичок
    # по-прежнему Н/О, коэффициенты 1.4...0.25.
    raw = _build_excel_bytes([
        _group_row("Супервайзер - Иванов И.И."),
        _row("Хороший Новичок", 100, 50, 200, 20, 1, status="Новичок, 1-й уровень"),
    ])
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    r = results[0]
    assert r.is_na is True
    assert r.final_place is None
