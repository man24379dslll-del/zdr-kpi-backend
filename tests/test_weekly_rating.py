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
TIME_PC = "Время/контакт без звонка, мин"  # категория "время" считается БЕЗ звонка, не "Время/контакт, мин"
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


def test_bonus_columns_matched_by_suffix_when_percentage_differs():
    # Регрессия на реальный баг (найден на реальном файле заказчика):
    # bonus075/bonus2 искались по ТОЧНОМУ совпадению текста колонки и были
    # ОБЯЗАТЕЛЬНЫМИ — файл с "3.5% за дост." вместо жёстко зашитого
    # "2% за дост." (процент варьируется от файла к файлу) заставлял весь
    # парсер падать с HTTPException 400 "не хватает колонок", хотя нужная
    # колонка физически была, просто с другим числом в начале названия.
    row = _employee_row("Тестов Т.", "", 100, 50, 100, 30, 2, 1, 5, 1000, "radio")
    del row[BONUS2]
    row["3.5% за дост."] = 777
    raw = _build_excel_bytes([_group_row("Тестовая группа"), row])
    employees = parse_weekly_rating_excel(raw)
    assert employees[0]["bonus2"] == 777
    assert employees[0]["bonus075"] == 100  # соседняя колонка не пострадала


def test_bonus_columns_missing_do_not_crash_parsing():
    # Обе бонусные колонки отсутствуют вовсе — раньше это было невозможно
    # проверить, т.к. они считались обязательными и парсер падал раньше,
    # чем доходил до этой строки. Теперь — просто None, как у остальных
    # необязательных полей (карточки, errors_count).
    row = _employee_row("Тестов Т.", "", 100, 50, 100, 30, 2, 1, 5, 1000, "radio")
    del row[BONUS075]
    del row[BONUS2]
    raw = _build_excel_bytes([_group_row("Тестовая группа"), row])
    employees = parse_weekly_rating_excel(raw)
    assert employees[0]["bonus075"] is None
    assert employees[0]["bonus2"] is None


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


def test_time_category_reads_from_without_call_column_not_the_decoy():
    # Регрессия: категория "время" должна читаться из "Время/контакт без
    # звонка, мин" (Z), а НЕ из "Время/контакт, мин" (Y) — в файле есть
    # ОБЕ колонки, а раньше по ошибке читалась Y. "decoy"-значение в Y
    # намеренно другое, чтобы тест упал, если код снова начнёт читать не
    # ту колонку.
    row = _employee_row("Тестов Т.", "", 100, 50, 100, 30, 2, 1, 5, 1000, "radio")
    row["Время/контакт, мин"] = 999  # decoy — этой колонки в расчёте быть не должно
    raw = _build_excel_bytes([_group_row("Тестовая группа"), row])
    employees = parse_weekly_rating_excel(raw)
    assert employees[0]["time_per_contact"] == 30  # значение из TIME_PC ("без звонка"), не decoy 999


def test_work_hours_parsed_when_column_present():
    # "Рабочее время, ч" — необязательная колонка при разборе (парсер не
    # падает без неё), но обязательна для честного расчёта ЗП, см.
    # services/salary.py.
    row = _employee_row("Тестов Т.", "", 100, 50, 100, 30, 2, 1, 5, 1000, "radio")
    row["Рабочее время, ч"] = 38.5
    raw = _build_excel_bytes([_group_row("Тестовая группа"), row])
    employees = parse_weekly_rating_excel(raw)
    assert employees[0]["work_hours"] == 38.5


def test_work_hours_is_none_when_column_missing():
    row = _employee_row("Тестов Т.", "", 100, 50, 100, 30, 2, 1, 5, 1000, "radio")
    raw = _build_excel_bytes([_group_row("Тестовая группа"), row])
    employees = parse_weekly_rating_excel(raw)
    assert employees[0]["work_hours"] is None


def test_work_hours_is_none_for_specific_employee_when_cell_empty():
    # Колонка ЕСТЬ в файле, но у конкретного человека ячейка пустая — это
    # тоже "неизвестно" (None), а НЕ 0 часов (иначе ЗП формула тихо дала
    # бы заниженную, но ненулевую ЗП вместо явного "не посчитано").
    row_with = _employee_row("С часами", "", 100, 50, 100, 30, 2, 1, 5, 1000, "radio")
    row_with["Рабочее время, ч"] = 38.5
    row_without = _employee_row("Без часов", "", 100, 50, 100, 30, 2, 1, 5, 1000, "radio")
    raw = _build_excel_bytes([_group_row("Тестовая группа"), row_with, row_without])
    employees = parse_weekly_rating_excel(raw)
    by_fio = {e["fio"]: e for e in employees}
    assert by_fio["С часами"]["work_hours"] == 38.5
    assert by_fio["Без часов"]["work_hours"] is None


def test_shift_count_parsed_when_column_present():
    # "Кол-во смен" — чисто информационная колонка (в отличие от
    # work_hours НЕ участвует в формуле ЗП), только для отображения рядом.
    row = _employee_row("Тестов Т.", "", 100, 50, 100, 30, 2, 1, 5, 1000, "radio")
    row["Кол-во смен"] = 5
    raw = _build_excel_bytes([_group_row("Тестовая группа"), row])
    employees = parse_weekly_rating_excel(raw)
    assert employees[0]["shift_count"] == 5


def test_shift_count_is_none_when_column_missing():
    row = _employee_row("Тестов Т.", "", 100, 50, 100, 30, 2, 1, 5, 1000, "radio")
    raw = _build_excel_bytes([_group_row("Тестовая группа"), row])
    employees = parse_weekly_rating_excel(raw)
    assert employees[0]["shift_count"] is None


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
    # Зайцева (Отпуск) и Морозова (c1_sum==0, статус пустой) — Н/О, но НЕ
    # новички: ladder_groups.assign_novice_coefficients их не трогает,
    # тир/коэффициент остаются None (только assign_tier_coefficients мог бы
    # их выставить, а он тоже пропускает is_na=True).
    for fio in ("Зайцева З.", "Морозова М."):
        assert by_fio[fio].tier is None
        assert by_fio[fio].coefficient is None
    # Новиков Н. ("Новичок 2 неделя") — новичок: получает "теоретический"
    # коэффициент ЛГ (см. test_novice_coefficient.py-стиль тесты в
    # test_ladder_groups.py), но final_place/is_na не меняются (проверено выше).
    assert by_fio["Новиков Н."].coefficient is not None


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
    # Тиры Б/В у этих сотрудников хуже тира A — НЕ потому что гарантировано
    # алгоритмом (формула тира Б/В больше не сдвинута на размер тира A,
    # по прямому запросу заказчика — тир A может обгоняться), а просто
    # потому что у них в этой фикстуре и остальные категории тоже слабее.
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


def test_novice_theoretical_coefficient_end_to_end_does_not_change_evaluated():
    """Новиков Н. ("Новичок 2 неделя", группа Иванова) — самые слабые
    показатели в файле (см. ROWS), но группа Иванова маленькая: 4 оценённых
    + 1 новичок = 5 -> tier_sizes(5) = [1,1,1,1,1,0,0,0,0,0] -> даже
    последнее (5-е) теоретическое место попадает в тир 5 (коэффициент 1.05
    по умолчанию, TIER_COEFFICIENTS[4]) — граничный случай "коэффициент
    ровно 1.05 остаётся как есть, не 1.0". Полный пайплайн (реальный Excel
    -> compute_weekly_rating), не изолированный юнит-тест.
    """
    by_fio = _compute()
    novice = by_fio["Новиков Н."]
    assert novice.final_place is None
    assert novice.is_na is True
    assert novice.tier == 5
    assert novice.coefficient == TIER_COEFFICIENTS[4] == 1.05

    # Присутствие новичка не изменило тиры/коэффициенты оценённых сотрудников
    # его же группы (сравниваем с уже проверенными значениями выше).
    assert by_fio["Комаров К."].tier == 1
    assert by_fio["Комаров К."].coefficient == TIER_COEFFICIENTS[0]
    for supervisor_fios in (
        ("Комаров К.", "Петров П.", "Сидоров С.", "Кузнецова К."),
        ("Волков В.", "Смирнов С.", "Орлова О."),
    ):
        evaluated = sorted((by_fio[fio] for fio in supervisor_fios), key=lambda r: r.final_place)
        assert [r.tier for r in evaluated] == sorted(r.tier for r in evaluated)


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


def test_channel_tier_ranks_by_per_contact_when_deal_exists():
    # Карточек>=1 И конверсия>0 -> обычный спортивный ранг по ch_per_contact
    # среди тех, у кого тоже есть сделка (проверяем отдельно от "нет сделки" ниже).
    a = _employee_row("Тир-А1", "", 100, 100, 500, 20, 1, 5, 20, 5000, "radio")
    b = _employee_row("Тир-А2", "", 90, 90, 400, 22, 1.2, 6, 15, 4000, "radio")
    raw = _build_excel_bytes([_group_row("Супервайзер - Тестов Тест Тестович"), a, b])
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    by_fio = {r.fio: r for r in results}

    assert by_fio["Тир-А1"].places["channel"] == 1  # ch_pc=500, лучший
    assert by_fio["Тир-А2"].places["channel"] == 2  # ch_pc=400


def test_channel_tier_is_self_contained_and_lk_uses_its_final_place():
    # Тир канала считается ПЕРВЫМ и НЕ зависит от мест других категорий —
    # только от собственных карточек/конверсии/суммы с контакта (см.
    # docstring tier_channel.py). Тир ЛК считается ПОСЛЕ и использует уже
    # ГОТОВОЕ (финальное, не промежуточное) место по каналу в своём
    # среднем для тиров Б/В.
    a = _employee_row("А", "", 100, 50, 0, 20, 1, 5, 20, 5000, "radio")  # ЛК тир A; канал: 0 карточек -> тир Б
    a[RADIO_COUNT] = 0
    a[RADIO_CONV] = 0
    b = _employee_row("Б", "", 90, 40, 999, 22, 1.2, 6, 15, 4000, "radio")  # ЛК тир A; канал тир A, лучший ch_pc
    b[RADIO_COUNT] = 3
    b[RADIO_CONV] = 10
    # У X — САМЫЙ БОЛЬШОЙ сырой ch_pc (9999) во всей группе, но
    # конверсия по каналу 0% -> это тир В (карточки впустую), а НЕ тир A,
    # несмотря на формально лучшую "сумму с контакта". Также ЛК тир Б
    # (карточек ЛК нет вовсе).
    x = _employee_row("X", "", 80, 999, 9999, 25, 1.5, 0, 0, 3000, "radio")
    x[RADIO_COUNT] = 50
    x[RADIO_CONV] = 0

    raw = _build_excel_bytes([_group_row("Супервайзер - Тестов Тест Тестович"), a, b, x])
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    by_fio = {r.fio: r for r in results}

    # Канал: Б тир A (единственный, cards>0 и conv>0) -> место 1;
    # А тир Б (0 карточек) -> место |A|+1 = 2;
    # X тир В (карточки есть, конверсия 0%, ЕДИНСТВЕННЫЙ в тире В) -> место |A|+|Б|+1 = 3
    assert by_fio["Б"].places["channel"] == 1.0
    assert by_fio["А"].places["channel"] == 2.0
    assert by_fio["X"].places["channel"] == 3.0
    # НЕ 1 — то место, что дал бы сырой ранг по ch_pc=9999 (был бы лучшим во всей группе)
    assert by_fio["X"].places["channel"] != 1.0

    xr = by_fio["X"]
    # ЛК тир Б (карточек ЛК нет): среднее МЕСТО по c1/каналу(ФИНАЛЬНОЕ!)/
    # времени/ошибкам, БЕЗ сдвига на размер тира A (по прямому запросу
    # заказчика) = (3+3+3+3)/4 = 3
    assert xr.places["lk"] == pytest.approx(3.0)
    # Если бы вместо финального (тированного) места канала использовался
    # сырой ранг по ch_pc (у X он был бы =1, лучший во всей группе),
    # получилось бы (3+1+3+3)/4 = 2.5 — другое число.
    assert xr.places["lk"] != pytest.approx(2.5)


def test_lk_average_reconciles_exactly_with_places_visible_in_the_table():
    # Явная регрессия на путаницу, из-за которой раньше "среднее по
    # категориям" у тира ЛК не совпадало с тем, что реально видно в
    # таблице "По группам" (пример Астаховой/Кожеуровой/Полякова) — тир
    # канала считался ПОСЛЕ тира ЛК на ещё "плоском" месте, отличном от
    # итогового. Теперь канал считается первым и самостоятельно, а тир Б
    # ЛК — это просто среднее БЕЗ сдвига на размер тира A, поэтому
    # "место ЛК = среднее из чисел, видимых в таблице" должно сходиться
    # буквально, без исключений и без нужды знать размер тира A.
    a = _employee_row("А", "", 100, 50, 0, 20, 1, 5, 20, 5000, "radio")
    a[RADIO_COUNT] = 0
    a[RADIO_CONV] = 0
    b = _employee_row("Б", "", 90, 40, 999, 22, 1.2, 6, 15, 4000, "radio")
    b[RADIO_COUNT] = 3
    b[RADIO_CONV] = 10
    x = _employee_row("X", "", 80, 999, 9999, 25, 1.5, 0, 0, 3000, "radio")
    x[RADIO_COUNT] = 50
    x[RADIO_CONV] = 0

    raw = _build_excel_bytes([_group_row("Супервайзер - Тестов Тест Тестович"), a, b, x])
    employees = parse_weekly_rating_excel(raw)
    results = compute_weekly_rating(employees, CATEGORIES, na_predicate=is_na_row)
    by_fio = {r.fio: r for r in results}
    xr = by_fio["X"]

    manual_avg = (xr.places["c1"] + xr.places["channel"] + xr.places["time"] + xr.places["errors"]) / 4
    assert xr.places["lk"] == pytest.approx(manual_avg)


def test_lk_tier_missing_channel_category_raises_value_error():
    # Убираем 'channel' (а не 'lk') — тир ЛК явно требует эту категорию
    # для своего среднего (LK_TIER_PLACE_FIELDS), а сам тир канала больше
    # ни от чего не зависит и без 'lk' прекрасно работает.
    categories = [c for c in CATEGORIES if c.key != "channel"]
    raw = _build_excel_bytes(ROWS)
    employees = parse_weekly_rating_excel(raw)
    with pytest.raises(ValueError, match="Тир ЛК требует категории"):
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
    assert row["salary"] is None  # assign_salary тут не вызывается (это работа routers/ratings.py, не compute_weekly_rating)
    assert row["work_hours"] is None  # "Рабочее время, ч" не задана в тестовых строках
    assert row["shift_count"] is None  # "Кол-во смен" не задана в тестовых строках

    novikov = by_fio["Новиков Н."]
    novikov_row = build_kpi_rating_row("upload-123", novikov)
    assert novikov_row["is_na"] is True
    assert novikov_row["final_place"] is None
    # Новичок ("Новичок 2 неделя") теперь получает "теоретический" тир/
    # коэффициент ЛГ (см. test_novice_theoretical_coefficient_end_to_end_*
    # выше) — не None, хотя final_place остаётся null.
    assert novikov_row["tier"] == 5
    assert novikov_row["coefficient"] == TIER_COEFFICIENTS[4] == 1.05
