"""
Сектор №1 — 4 обычные группы супервайзеров (Болотов/Владыкин/Гулуа/
Потапова). Два правила поверх обычного расчёта:
  1. Место по ЛК (lk_place) ВСЕГДА 1-е, для ВСЕХ сотрудников этих групп
     (переопределяет обычный тир ЛК) — по запросу заказчика.
  2. В total_score категория "ЛК" при этом входит только у 3 конкретных
     сотрудников-исключений (точное ФИО, см.
     group_naming.SECTOR_1_LK_WEIGHT_EXCEPTIONS_FIO) — у остальных вес 0,
     как и раньше. Раз место у всех теперь 1-е, эти трое получают МАКСИМАЛЬНЫЙ
     балл по ЛК независимо от реальных продаж.
В отличие от Региона УК/ПП/Увеличители (test_region_uk.py) решение о весе
принимается по каждому сотруднику отдельно, а не по всей группе целиком.
"""
import io

import pandas as pd

from app.services.excel_parsing import is_na_row, parse_weekly_rating_excel
from app.services.group_naming import SECTOR_1_LK_WEIGHT_EXCEPTIONS_FIO, SECTOR_1_SUPERVISORS
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

BOLOTOV = "Супервайзер - Болотов Дмитрий Александрович"
assert BOLOTOV in SECTOR_1_SUPERVISORS
EXCEPTION_FIO = next(iter(SECTOR_1_LK_WEIGHT_EXCEPTIONS_FIO))


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


def _build_excel_bytes(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def test_sector1_regular_employee_has_lk_excluded_from_total_score():
    raw = _build_excel_bytes([
        _group_row(BOLOTOV),
        _row("Обычный Сотрудник И. И.", 100, 50, 200, 20, 1),
    ])
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    r = results[0]

    # Место по ЛК всё равно считается и хранится (для отображения) ...
    assert "lk" in r.places
    # ... но НЕ входит в total_score
    assert "lk" not in r.scores
    assert set(r.scores.keys()) == {"c1", "channel", "time", "errors"}
    assert r.total_score == r.scores["c1"] + r.scores["channel"] + r.scores["time"] + r.scores["errors"]


def test_sector1_exception_employee_keeps_normal_lk_weight():
    raw = _build_excel_bytes([
        _group_row(BOLOTOV),
        _row(EXCEPTION_FIO, 100, 50, 200, 20, 1),
    ])
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    r = results[0]

    assert "lk" in r.scores
    assert set(r.scores.keys()) == {"c1", "lk", "channel", "time", "errors"}
    assert r.total_score == sum(r.scores.values())
    assert r.scores["lk"] == r.places["lk"] * 1.5  # обычный вес ЛК, как у всех остальных сотрудников


def test_sector1_exception_and_regular_employee_in_same_group():
    # Обе развилки внутри ОДНОЙ группы одновременно — проверяет, что
    # решение действительно поэлементное, а не на всю группу целиком
    # (как у Региона УК/ПП/Увеличители).
    raw = _build_excel_bytes([
        _group_row(BOLOTOV),
        _row(EXCEPTION_FIO, 100, 50, 200, 20, 1),
        _row("Обычный Сотрудник И. И.", 90, 40, 180, 25, 2),
    ])
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    by_fio = {r.fio: r for r in results}

    assert "lk" in by_fio[EXCEPTION_FIO].scores
    assert "lk" not in by_fio["Обычный Сотрудник И. И."].scores


def test_normal_group_is_unaffected_by_sector1_logic():
    # Контроль: обычная группа (не Сектор 1) — ЛК как всегда, независимо
    # от того, что ФИО сотрудника совпадает с одним из 3 исключений
    # (исключение действует ТОЛЬКО внутри 4 групп Сектора 1).
    raw = _build_excel_bytes([
        _group_row("Супервайзер - Иванов И.И."),
        _row(EXCEPTION_FIO, 100, 50, 200, 20, 1),
    ])
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    r = results[0]
    assert "lk" in r.scores


def test_sector1_places_and_tiers_are_still_assigned():
    # Урезание total_score не должно мешать финальному месту/ЛГ.
    raw = _build_excel_bytes([
        _group_row(BOLOTOV),
        _row("Первый И. И.", 100, 50, 200, 20, 1),
        _row("Второй И. И.", 60, 15, 120, 45, 8),
    ])
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    for r in results:
        assert r.is_na is False
        assert r.final_place is not None
        assert r.tier is not None
        assert r.coefficient is not None


def test_sector1_regular_employee_always_gets_lk_place_1_even_when_worse():
    # "Второй" реально хуже по ЛК (lk_pc=15 против 50), но в Секторе 1 у
    # ВСЕХ место по ЛК всегда 1-е — по прямому запросу заказчика.
    raw = _build_excel_bytes([
        _group_row(BOLOTOV),
        _row("Первый И. И.", 100, 50, 200, 20, 1),
        _row("Второй И. И.", 60, 15, 120, 45, 8),
    ])
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    for r in results:
        assert r.places["lk"] == 1


def test_sector1_exception_gets_maximum_lk_score_regardless_of_real_sales():
    # Исключение — с ХУДШИМ ЛК, чем у обычного сотрудника той же группы —
    # всё равно получает МАКСИМАЛЬНЫЙ балл по ЛК (1-е место × вес 1.5),
    # т.к. место у всех в Секторе 1 всегда 1-е, а у исключений вес обычный.
    raw = _build_excel_bytes([
        _group_row(BOLOTOV),
        _row(EXCEPTION_FIO, 10, 1, 20, 45, 8),  # заведомо худшие показатели
        _row("Обычный Сотрудник И. И.", 100, 50, 200, 20, 1),  # заведомо лучшие
    ])
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    by_fio = {r.fio: r for r in results}

    exception = by_fio[EXCEPTION_FIO]
    assert exception.places["lk"] == 1
    assert exception.scores["lk"] == 1.5  # 1 место × вес 1.5, максимум
    assert "lk" in exception.scores  # входит в total_score (обычный вес)


def test_normal_group_lk_place_is_computed_normally_not_forced():
    # Контроль: вне Сектора 1 место по ЛК считается как обычно (не всегда 1).
    raw = _build_excel_bytes([
        _group_row("Супервайзер - Иванов И.И."),
        _row("Первый И. И.", 100, 50, 200, 20, 1),
        _row("Второй И. И.", 60, 15, 120, 45, 8),
    ])
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    by_fio = {r.fio: r for r in results}
    assert by_fio["Первый И. И."].places["lk"] == 1
    assert by_fio["Второй И. И."].places["lk"] != 1


def test_sector1_uses_5_tiers_with_narrow_coefficient_range():
    # По прямому запросу заказчика: Сектор 1 использует 5 тиров (1.3...1.0),
    # НЕ обычные 10 (1.4...0.25) — ни выше 1.3, ни ниже 1.0.
    # 10 человек, строго убывающий c1_pc (остальные категории одинаковые,
    # чтобы порядок total_score определялся только c1) -> final_place 1..10
    # по 2 человека на каждый из 5 тиров (tier_sizes(10, 5) = [2,2,2,2,2]).
    rows = [_group_row(BOLOTOV)]
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
        assert r.tier == expected_tier, f"место {place}: ожидался тир {expected_tier}, получили {r.tier}"
        assert r.coefficient == expected_coefficient_by_tier[expected_tier]

    # Ни у кого нет тира выше 5 и коэффициента вне диапазона [1.0, 1.3]
    assert all(r.tier <= 5 for r in results)
    assert all(1.0 <= r.coefficient <= 1.3 for r in results)


def test_normal_group_still_uses_10_tiers():
    # Контроль: вне Сектора 1 диапазон коэффициентов прежний (1.4...0.25),
    # не урезан до 1.3...1.0.
    rows = [_group_row("Супервайзер - Иванов И.И.")]
    for i in range(10):
        rows.append(_row(f"Сотрудник {i}", 100 - i * 10, 50, 100, 20, 1))
    raw = _build_excel_bytes(rows)
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    by_place = {r.final_place: r for r in results}

    assert by_place[1].tier == 1
    assert by_place[1].coefficient == 1.4  # выше верхней границы Сектора 1 (1.3)
    assert by_place[10].tier == 10
    assert by_place[10].coefficient == 0.25  # ниже нижней границы Сектора 1 (1.0)
