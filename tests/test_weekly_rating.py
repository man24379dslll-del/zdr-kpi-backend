"""
Тест на реальном примере: собираем xlsx-файл в памяти (как будто его
загрузил админ через /ratings/compute) с настоящими заголовками колонок
и группами супервайзеров, прогоняем через реальный парсер
(parse_weekly_rating_excel) и реальный расчёт (compute_weekly_rating) —
категории → тир ЛК → итоговое место → ЛГ — и проверяем результат.

Заголовки колонок ниже — литералы, НЕ импортированы из excel_parsing.py:
если там опечатаются в названии колонки, этот тест должен упасть, а не
молча совпасть с той же (неверной) константой.

Сеть/Supabase не задействованы: категории передаются как в
rating_categories (стартовый набор из app/db/schema.sql), а не
загружаются через API — это тестирует именно расчёт, а не HTTP-слой.
Запись в БД (ratings_repository.save_weekly_rating) не тестируется тут —
для неё нужен реальный Supabase; тестируется только чистая функция
маппинга build_kpi_rating_row.
"""
import io

import pandas as pd
import pytest

from app.services.excel_parsing import is_na_row, parse_weekly_rating_excel
from app.services.ladder_groups import TIER_COEFFICIENTS
from app.services.rating_engine import RatingCategory
from app.services.ratings_repository import build_kpi_rating_row
from app.services.weekly_rating import compute_weekly_rating

FIO = "ФИО"
STATUS = "Статус (уровень)"
BONUS075 = "0.75% за офор."
BONUS2 = "2% за дост."
C1_COUNT = "Первый контакт: кол-во"
C1_COUNT_FALLBACK = "Карточек (Первый контакт)"
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
TIME_PC = "Время/контакт, мин"
ERRORS_PCT = "Ошибок, %"

CATEGORIES = [
    RatingCategory(key="c1", label="1 обращение", source_column="c1_per_contact", weight=3, direction="desc", sort_order=1),
    RatingCategory(key="lk", label="ЛК", source_column="lk_per_contact", weight=1.5, direction="desc", sort_order=2),
    RatingCategory(key="channel", label="Радио+ТВ / Интернет", source_column="ch_per_contact", weight=2.5, direction="desc", sort_order=3),
    RatingCategory(key="time", label="Время/контакт", source_column="time_per_contact", weight=1, direction="asc", sort_order=4),
    RatingCategory(key="errors", label="% ошибок", source_column="errors_pct", weight=1, direction="asc", sort_order=5),
]


def _employee_row(
    fio, status, c1_pc, lk_pc, ch_pc, time_pc, errors_pct, lk_cards, lk_conv, c1_sum, channel
):
    """channel: 'radio' или 'inet' — определяет, в какой блок колонок пишем сумму
    (второй канал в это же время стоит нулём, как в реальном файле)."""
    radio_sum = 1000.0 if channel == "radio" else 0.0
    inet_sum = 1000.0 if channel == "inet" else 0.0
    return {
        FIO: fio,
        STATUS: status,
        BONUS075: 100,
        BONUS2: 50,
        C1_COUNT: 20,
        C1_SUM: c1_sum,
        C1_CHECK: 500,
        C1_CONV: 30,
        C1_PC: c1_pc,
        LK_COUNT: lk_cards,
        LK_SUM: 1000,
        LK_CHECK: 200,
        LK_CONV: lk_conv,
        LK_PC: lk_pc,
        RADIO_COUNT: 5,
        RADIO_SUM: radio_sum,
        RADIO_CHECK: 300,
        RADIO_CONV: 20,
        RADIO_PC: ch_pc if channel == "radio" else 0,
        INET_SUM: inet_sum,
        INET_CHECK: 300,
        INET_CONV: 20,
        INET_PC: ch_pc if channel == "inet" else 0,
        TIME_PC: time_pc,
        ERRORS_PCT: errors_pct,
    }


def _group_row(label: str) -> dict:
    return {FIO: f"ГРУППА: {label}"}


# Иванов работает через Радио+ТВ, Петрова — через Интернет (проверяем оба канала)
ROWS = [
    _group_row("Супервайзер - Иванов Иван Иванович"),
    _employee_row("Комаров К.", "", 200, 100, 250, 20, 0.5, 8, 25, 8000, "radio"),   # тир A, лучший везде
    _employee_row("Петров П.", "", 120, 80, 200, 30, 2, 5, 10, 5000, "radio"),        # тир A
    _employee_row("Сидоров С.", "", 100, 60, 150, 40, 3, 0, 0, 4000, "radio"),        # тир Б (карточек 0)
    _employee_row("Кузнецова К.", "", 90, 70, 180, 35, 1, 12, 0, 3500, "radio"),      # тир В (10+ карточек, конв 0)
    _employee_row("Новиков Н.", "Новичок 2 неделя", 10, 5, 20, 60, 10, 1, 0, 500, "radio"),  # Н/О по статусу
    _group_row("Супервайзер - Петрова Мария Сергеевна"),
    _employee_row("Волков В.", "", 150, 90, 220, 25, 1, 3, 15, 6000, "inet"),         # тир A
    _employee_row("Смирнов С.", "", 80, 40, 100, 50, 5, 7, 0, 2000, "inet"),          # тир Б (1..9 карточек, конв 0)
    _employee_row("Орлова О.", "", 70, 30, 90, 55, 6, 20, 0, 1500, "inet"),           # тир В
    _employee_row("Зайцева З.", "Отпуск", 5, 2, 10, 70, 15, 0, 0, 200, "inet"),       # Н/О по статусу
    _employee_row("Морозова М.", "", 60, 25, 80, 45, 4, 2, 10, 0, "inet"),            # Н/О: c1_sum == 0
]


def _build_excel_bytes(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def _compute():
    raw = _build_excel_bytes(ROWS)
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    return {r.fio: r for r in results}


def test_group_rows_split_supervisors_and_are_not_employees():
    raw = _build_excel_bytes(ROWS)
    employees = parse_weekly_rating_excel(raw)
    assert len(employees) == 10  # 2 строки "ГРУППА:" не попали в сотрудников
    by_fio = {e["fio"] for e in employees}
    assert "ГРУППА: Супервайзер - Иванов Иван Иванович" not in by_fio

    ivanov_people = [e for e in employees if e["supervisor"] == "Супервайзер - Иванов Иван Иванович"]
    petrova_people = [e for e in employees if e["supervisor"] == "Супервайзер - Петрова Мария Сергеевна"]
    assert len(ivanov_people) == 5
    assert len(petrova_people) == 5


def test_channel_falls_back_to_heuristic_and_flags_guess_when_supervisor_unknown():
    # Без записи в supervisor_channels — угадываем по большей сумме и
    # явно помечаем channel_is_guessed=True (фронтенд должен подсветить).
    raw = _build_excel_bytes(ROWS)
    employees = parse_weekly_rating_excel(raw)
    by_fio = {e["fio"]: e for e in employees}

    komarov = by_fio["Комаров К."]  # группа Иванов -> Радио+ТВ (сумма больше)
    assert komarov["channel"] == "radio"
    assert komarov["channel_is_guessed"] is True
    assert komarov["ch_per_contact"] == 250

    volkov = by_fio["Волков В."]  # группа Петрова -> Интернет (сумма больше)
    assert volkov["channel"] == "inet"
    assert volkov["channel_is_guessed"] is True
    assert volkov["ch_per_contact"] == 220


def test_supervisor_channel_config_overrides_heuristic():
    # Реальный случай (проверено на данных): у Лиштвы в интернете физически
    # больше денег, но настоящий канал — радио. Настройка должна победить
    # эвристику "больше сумма", а не наоборот.
    row = _employee_row("Лиштва О.", "", 100, 50, 999, 30, 2, 1, 5, 1000, "inet")
    row[RADIO_SUM] = 93_410
    row[INET_SUM] = 204_600
    row[RADIO_PC] = 111
    row[INET_PC] = 999
    raw = _build_excel_bytes([_group_row("Супервайзер - Лиштва Ольга Васильевна"), row])

    supervisor_channels = {"Супервайзер - Лиштва Ольга Васильевна": "radio"}
    employees = parse_weekly_rating_excel(raw, supervisor_channels)

    assert employees[0]["channel"] == "radio"
    assert employees[0]["channel_is_guessed"] is False
    assert employees[0]["ch_sum"] == 93_410
    assert employees[0]["ch_per_contact"] == 111


def test_supervisor_matching_tolerates_punctuation_drift_by_surname():
    # Название группы в файле отличается по пунктуации/формату от того, что
    # в supervisor_channels — должны найти по вхождению фамилии.
    row = _employee_row("Тестов Т.", "", 100, 50, 100, 30, 2, 1, 5, 1000, "radio")
    raw = _build_excel_bytes([_group_row("Супервайзер: Курбанова З.Р."), row])
    supervisor_channels = {"Супервайзер - Курбанова Зарина Рахимджановна": "inet"}

    employees = parse_weekly_rating_excel(raw, supervisor_channels)

    assert employees[0]["channel"] == "inet"
    assert employees[0]["channel_is_guessed"] is False


def test_missing_optional_card_columns_do_not_crash():
    # Колонки "Интернет: кол-во" в файле нет вообще (её никогда не бывает
    # в реальных файлах) — не должно падать, просто None для тех, кто
    # работает через интернет-канал.
    raw = _build_excel_bytes(ROWS)
    employees = parse_weekly_rating_excel(raw)
    volkov = next(e for e in employees if e["fio"] == "Волков В.")
    assert volkov["channel"] == "inet"
    assert volkov["ch_cards"] is None

    komarov = next(e for e in employees if e["fio"] == "Комаров К.")
    assert komarov["channel"] == "radio"
    assert komarov["ch_cards"] == 5  # "Радио + ТВ: кол-во" в файле есть


def test_c1_cards_fallback_column_name_is_used_when_present():
    row = _employee_row("Тестов Т.", "", 100, 50, 100, 30, 2, 1, 5, 1000, "radio")
    del row[C1_COUNT]
    row[C1_COUNT_FALLBACK] = 42
    raw = _build_excel_bytes([_group_row("Тестовая группа"), row])
    employees = parse_weekly_rating_excel(raw)
    assert employees[0]["c1_cards"] == 42


def test_missing_mandatory_column_raises_400():
    row = _employee_row("Тестов Т.", "", 100, 50, 100, 30, 2, 1, 5, 1000, "radio")
    del row[C1_SUM]
    raw = _build_excel_bytes([row])
    with pytest.raises(Exception) as exc_info:
        parse_weekly_rating_excel(raw)
    assert "не хватает колонок" in str(exc_info.value.detail)


def test_na_employees_excluded_from_final_place_and_ladder():
    by_fio = _compute()
    for fio in ("Новиков Н.", "Зайцева З.", "Морозова М."):
        assert by_fio[fio].is_na is True
        assert by_fio[fio].final_place is None
        assert by_fio[fio].tier is None
        assert by_fio[fio].coefficient is None


def test_tier_lk_ranks_tier_a_by_lk_pc_desc():
    by_fio = _compute()
    # Тир A (карточки>0 и конверсия>0): Комаров(100) > Волков(90) > Петров(80)
    assert by_fio["Комаров К."].places["lk"] == 1
    assert by_fio["Волков В."].places["lk"] == 2
    assert by_fio["Петров П."].places["lk"] == 3
    # Тиры Б/В гарантированно хуже места 3 (размера тира A)
    for fio in ("Сидоров С.", "Кузнецова К.", "Смирнов С.", "Орлова О."):
        assert by_fio[fio].places["lk"] > 3


def test_tier_c_worse_than_tier_b_within_same_supervisor():
    by_fio = _compute()
    assert by_fio["Кузнецова К."].places["lk"] > by_fio["Сидоров С."].places["lk"]
    assert by_fio["Орлова О."].places["lk"] > by_fio["Смирнов С."].places["lk"]


def test_best_overall_performer_gets_final_place_one():
    by_fio = _compute()
    komarov = by_fio["Комаров К."]
    assert all(place == 1 for place in komarov.places.values())
    assert komarov.total_score == 3 + 1.5 + 2.5 + 1 + 1
    assert komarov.final_place == 1


def test_ladder_groups_assigned_per_supervisor_and_monotonic_with_final_place():
    by_fio = _compute()
    for supervisor_fios in (
        ("Комаров К.", "Петров П.", "Сидоров С.", "Кузнецова К."),
        ("Волков В.", "Смирнов С.", "Орлова О."),
    ):
        evaluated = sorted((by_fio[fio] for fio in supervisor_fios), key=lambda r: r.final_place)
        tiers = [r.tier for r in evaluated]
        coefficients = [r.coefficient for r in evaluated]
        assert tiers == sorted(tiers)
        assert coefficients == sorted(coefficients, reverse=True)
        assert all(c in TIER_COEFFICIENTS for c in coefficients)

    assert by_fio["Комаров К."].tier == 1
    assert by_fio["Комаров К."].coefficient == TIER_COEFFICIENTS[0]


def test_build_kpi_rating_row_maps_computed_fields_for_supabase():
    by_fio = _compute()
    komarov = by_fio["Комаров К."]
    row = build_kpi_rating_row("upload-123", komarov)

    assert row["upload_id"] == "upload-123"
    assert row["fio"] == "Комаров К."
    assert row["supervisor"] == "Супервайзер - Иванов Иван Иванович"
    assert row["channel"] == "radio"
    assert row["c1_place"] == 1
    assert row["lk_place"] == 1
    assert row["ch_place"] == 1
    assert row["final_place"] == 1
    assert row["is_na"] is False
    assert row["tier"] == 1
    assert row["coefficient"] == TIER_COEFFICIENTS[0]
    assert row["bonus075"] == 100
    assert row["bonus2"] == 50
    assert row["salary"] is None  # формула ЗП ещё не перенесена

    novikov = by_fio["Новиков Н."]
    novikov_row = build_kpi_rating_row("upload-123", novikov)
    assert novikov_row["is_na"] is True
    assert novikov_row["final_place"] is None
    assert novikov_row["tier"] is None
