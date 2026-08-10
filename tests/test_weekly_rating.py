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
from app.services.group_naming import clean_supervisor_name, display_group_name
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


def test_category_places_are_scoped_to_supervisor_group_not_company_wide():
    """Регрессия на баг, при котором места по категориям (и итоговое место)
    считались по ВСЕЙ компании разом, а не внутри своей группы супервайзера,
    как в оригинальной JS-логике (computeMainRating вызывает scoreSlice по
    одному разу НА КАЖДУЮ группу, а не один раз на весь файл — сотрудник
    соревнуется со своей командой, а не со всей компанией).

    Сотрудники двух РАЗНЫХ групп подобраны так, чтобы их значения
    ПЕРЕСЕКАЛИСЬ: "средний" сотрудник группы Б (75) лежит МЕЖДУ двумя
    сотрудниками группы А (100 и 50). Если бы места считались по всей
    компании (баг), пул был бы 100>75>50>10 -> A1=1, B1=2, A2=3, B2=4.
    Правильно (внутри своей группы из 2 человек): A1=1,A2=2 в группе А;
    B1=1,B2=2 в группе Б — т.е. оба "лучших" получают место 1, а не 1 и 2.
    """
    def emp(fio, supervisor, value):
        # time/errors — asc (меньше = лучше), поэтому инвертируем value,
        # чтобы "лучше" по всем 5 категориям было единообразно у каждого
        # сотрудника (упрощает арифметику итогового места).
        return {
            "fio": fio, "supervisor": supervisor, "is_region_uk": False,
            "c1_per_contact": value, "lk_per_contact": value, "lk_cards": 1, "lk_conv": 10,
            "ch_per_contact": value, "ch_cards": 15,
            "time_per_contact": 1000 - value, "errors_pct": 1000 - value,
        }

    employees = [
        emp("A1", "Группа А", 100),
        emp("A2", "Группа А", 50),
        emp("B1", "Группа Б", 75),  # между A1 и A2 — ключевой случай
        emp("B2", "Группа Б", 10),
    ]
    results = compute_weekly_rating(employees, CATEGORIES)
    by_fio = {r.fio: r for r in results}

    assert by_fio["A1"].places["c1"] == 1
    assert by_fio["B1"].places["c1"] == 1  # НЕ 2 — не сравнивается с A1 из чужой группы
    assert by_fio["A2"].places["c1"] == 2
    assert by_fio["B2"].places["c1"] == 2  # НЕ 4

    assert by_fio["A1"].final_place == 1
    assert by_fio["B1"].final_place == 1  # НЕ 2
    assert by_fio["A2"].final_place == 2
    assert by_fio["B2"].final_place == 2  # НЕ 4


KURBANOVA_ROWS = [
    _group_row("Супервайзер - Курбанова Зарина Рахимджановна"),
    _employee_row("Сотрудник 1", "", 100, 50, 100, 30, 2, 1, 5, 1000, "inet"),
    _employee_row("Сотрудник 2", "", 90, 40, 90, 32, 2.2, 1, 5, 900, "inet"),
    _employee_row("Сотрудник 3", "", 80, 30, 80, 34, 2.4, 1, 5, 800, "inet"),
    _employee_row("Сотрудник 4", "", 70, 20, 70, 36, 2.6, 1, 5, 700, "inet"),
]


def test_kurbanova_group_splits_into_two_subgroups_alternating_by_file_order():
    raw = _build_excel_bytes(KURBANOVA_ROWS)
    employees = parse_weekly_rating_excel(raw)
    by_fio = {e["fio"]: e for e in employees}

    assert by_fio["Сотрудник 1"]["supervisor"] == "Супервайзер - Курбанова Зарина Рахимджановна — 1"
    assert by_fio["Сотрудник 2"]["supervisor"] == "Супервайзер - Курбанова Зарина Рахимджановна — 2"
    assert by_fio["Сотрудник 3"]["supervisor"] == "Супервайзер - Курбанова Зарина Рахимджановна — 1"
    assert by_fio["Сотрудник 4"]["supervisor"] == "Супервайзер - Курбанова Зарина Рахимджановна — 2"
    for e in employees:
        assert e["is_region_uk"] is False  # не Регион УК — полноценная группа супервайзера


def test_kurbanova_subgroups_display_name_appends_number_to_cleaned_name():
    raw = _build_excel_bytes(KURBANOVA_ROWS)
    employees = parse_weekly_rating_excel(raw)
    supervisor_1 = employees[0]["supervisor"]
    supervisor_2 = employees[1]["supervisor"]
    assert clean_supervisor_name(supervisor_1) == "Курбанова Зарина Рахимджановна — 1"
    assert display_group_name(supervisor_1) == "Курбанова Зарина Рахимджановна — 1"
    assert display_group_name(supervisor_2) == "Курбанова Зарина Рахимджановна — 2"


def test_kurbanova_subgroups_keep_full_category_set_unlike_region_uk():
    raw = _build_excel_bytes(KURBANOVA_ROWS)
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    by_fio = {r.fio: r for r in results}
    # В отличие от Региона УК, total_score НЕ урезается — все 5 категорий в scores
    for fio in by_fio:
        assert set(by_fio[fio].scores.keys()) == {"c1", "lk", "channel", "time", "errors"}


def test_kurbanova_subgroups_have_independent_ladder_groups():
    # "Места считаются ВНУТРИ подгруппы" = отдельная ЛГ на каждую подгруппу
    # (как у любых двух разных супервайзеров), а не общий пул категорий —
    # тот как раз общий (см. тест выше), только ЛГ разная.
    raw = _build_excel_bytes(KURBANOVA_ROWS)
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    by_fio = {r.fio: r for r in results}

    assert by_fio["Сотрудник 1"].tier == 1
    assert by_fio["Сотрудник 3"].tier == 2  # худший ВНУТРИ подгруппы 1 (двое всего)
    assert by_fio["Сотрудник 2"].tier == 1
    assert by_fio["Сотрудник 4"].tier == 2  # худший ВНУТРИ подгруппы 2 (двое всего)


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


def test_errors_count_parsed_when_column_present():
    # "Ошибок" (сырое число) — необязательная колонка, только для
    # информации; не путать с обязательной "Ошибок, %" (errors_pct),
    # которая участвует в расчёте категории "% ошибок".
    row = _employee_row("Тестов Т.", "", 100, 50, 100, 30, 2, 1, 5, 1000, "radio")
    row["Ошибок"] = 7
    raw = _build_excel_bytes([_group_row("Тестовая группа"), row])
    employees = parse_weekly_rating_excel(raw)
    assert employees[0]["errors_count"] == 7


def test_errors_count_is_none_when_column_missing():
    row = _employee_row("Тестов Т.", "", 100, 50, 100, 30, 2, 1, 5, 1000, "radio")
    raw = _build_excel_bytes([_group_row("Тестовая группа"), row])
    employees = parse_weekly_rating_excel(raw)
    assert employees[0]["errors_count"] is None


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
    # Места считаются ВНУТРИ своей группы супервайзера (см. докстринг
    # weekly_rating.py) — Комаров/Петров (группа Иванова) и Волков (группа
    # Петровой) НЕ делят один пул, поэтому Волков лучший и единственный в
    # тире A своей группы, а не "между" Комаровым и Петровым.
    by_fio = _compute()
    # Тир A внутри группы Иванова (карточки>0 и конверсия>0): Комаров(100) > Петров(80)
    assert by_fio["Комаров К."].places["lk"] == 1
    assert by_fio["Петров П."].places["lk"] == 2
    # Тир A внутри группы Петровой: Волков — единственный (и потому лучший) в своём тире A
    assert by_fio["Волков В."].places["lk"] == 1
    # Тиры Б/В гарантированно хуже размера тира A СВОЕЙ группы (2 у Иванова, 1 у Петровой)
    for fio in ("Сидоров С.", "Кузнецова К."):
        assert by_fio[fio].places["lk"] > 2
    for fio in ("Смирнов С.", "Орлова О."):
        assert by_fio[fio].places["lk"] > 1


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


def test_compute_weekly_rating_passes_through_custom_tier_coefficients():
    # Кастомный набор вместо TIER_COEFFICIENTS по умолчанию — должен
    # реально применяться до конца пайплайна, а не только внутри
    # ladder_groups.assign_tier_coefficients (уже проверено отдельно там).
    custom = [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
    raw = _build_excel_bytes(ROWS)
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(
        employees, CATEGORIES, na_predicate=is_na_row, tier_coefficients=custom
    )
    by_fio = {r.fio: r for r in results}

    komarov = by_fio["Комаров К."]  # лучший в компании -> тир 1
    assert komarov.tier == 1
    assert komarov.coefficient == 9
    assert komarov.coefficient != TIER_COEFFICIENTS[0]


def test_channel_tier_ranks_by_per_contact_when_enough_cards():
    # ch_cards>=10 -> обычный спортивный ранг по ch_per_contact среди тех,
    # у кого тоже >=10 (проверяем отдельно от "мало карточек" ниже).
    a = _employee_row("Тир-А1", "", 100, 100, 500, 20, 1, 5, 20, 5000, "radio")
    a[RADIO_COUNT] = 15
    b = _employee_row("Тир-А2", "", 90, 90, 400, 22, 1.2, 6, 15, 4000, "radio")
    b[RADIO_COUNT] = 12
    raw = _build_excel_bytes([_group_row("Супервайзер - Тестов Тест Тестович"), a, b])
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    by_fio = {r.fio: r for r in results}

    assert by_fio["Тир-А1"].places["channel"] == 1  # ch_pc=500, лучший
    assert by_fio["Тир-А2"].places["channel"] == 2  # ch_pc=400


def test_channel_tier_uses_already_tiered_lk_place_not_raw_rank():
    # Тир канала считается ПОСЛЕ тира ЛК и должен использовать уже
    # тированное место по ЛК (не сырой ранг по lk_pc) — иначе тир ЛК и
    # тир канала зависели бы друг от друга циклически (см. docstring
    # tier_channel.py и weekly_rating.CHANNEL_TIER_PLACE_FIELDS).
    a = _employee_row("Тир-А1", "", 100, 100, 500, 20, 1, 5, 20, 5000, "radio")  # тир ЛК A, лучший lk_pc
    a[RADIO_COUNT] = 15  # >=10 -> "достаточно" карточек канала
    b = _employee_row("Тир-А2", "", 90, 90, 400, 22, 1.2, 6, 15, 4000, "radio")  # тир ЛК A, хуже lk_pc
    b[RADIO_COUNT] = 12
    # У "Мало-карт" самый большой СЫРОЙ lk_pc (999), но lk_cards=0 ->
    # тир ЛК Б (карточек нет вовсе) -> реальное (тированное) место хуже,
    # чем у А1/А2, несмотря на формально лучший lk_pc.
    c = _employee_row("Мало-карт", "", 80, 999, 10, 25, 1.5, 0, 0, 3000, "radio")
    c[RADIO_COUNT] = 3  # <10 -> "мало карточек" канала

    raw = _build_excel_bytes([_group_row("Супервайзер - Тестов Тест Тестович"), a, b, c])
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    by_fio = {r.fio: r for r in results}

    malo = by_fio["Мало-карт"]
    # Тир Б (карточек 0): 2 (размер тира A) + среднее место по c1/канал(плоский на тот момент)/время/ошибки = 2 + 3 = 5
    assert malo.places["lk"] == 5.0
    assert malo.places["lk"] > 1  # НЕ то место, что дал бы сырой ранг по lk_pc=999 (было бы 1)

    # Тир канала: 2 + среднее МЕСТО по c1/ЛК(уже тированное!)/время/ошибки = 2 + (3+5+3+3)/4 = 5.5
    assert malo.places["channel"] == pytest.approx(5.5)
    # Если бы вместо тированного lk_place использовался сырой ранг по lk_pc
    # (у "Мало-карт" он был бы =1, лучший), получилось бы 2 + (3+1+3+3)/4 = 4.5
    assert malo.places["channel"] != pytest.approx(4.5)


def test_channel_tier_missing_required_category_raises_value_error():
    # Убираем именно 'lk' (а не, скажем, 'time'), чтобы сработала ТОЛЬКО
    # проверка тира канала, а не тира ЛК: тир ЛК просто выключается, если
    # категории 'lk' нет вовсе, а тир канала явно требует её как одну из
    # своих 4 (CHANNEL_TIER_PLACE_FIELDS).
    categories = [c for c in CATEGORIES if c.key != "lk"]
    raw = _build_excel_bytes(ROWS)
    employees = parse_weekly_rating_excel(raw)
    with pytest.raises(ValueError, match="Тир канала требует категории"):
        compute_weekly_rating(employees, categories, na_predicate=is_na_row)


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
    assert row["errors_count"] is None  # "Ошибок" не задана в тестовых строках — не роняет, просто null
    assert row["salary"] is None  # формула ЗП ещё не перенесена

    novikov = by_fio["Новиков Н."]
    novikov_row = build_kpi_rating_row("upload-123", novikov)
    assert novikov_row["is_na"] is True
    assert novikov_row["final_place"] is None
    assert novikov_row["tier"] is None
