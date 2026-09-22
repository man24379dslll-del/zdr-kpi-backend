"""
Метки "С1 "/"С2 "/"С3 " — заказчик иногда добавляет их прямо в название
группы в исходном файле (пометка для себя, какой группе в какой сектор
идти), из-за чего supervisor в файле перестаёт совпадать с
user_profiles.supervisor_names и SECTOR_2_SUPERVISORS/SECTOR_3_SUPERVISORS
— реальный сбой на проде (период 9-3: 428 строк, ни один supervisor не
совпал ни с одной известной группой). SECTOR_LABEL_PREFIX_RE срезает
такую метку сразу при разборе строки "ГРУППА: ...".
"""
import io

import pandas as pd

from app.services.excel_parsing import parse_weekly_rating_excel

FIO = "ФИО"
STATUS = "Статус (уровень)"
BONUS075 = "0.75% за офор."
BONUS2 = "2% за дост."
C1_SUM = "Первый контакт: сумма"
C1_CHECK = "Первый контакт: ср.чек"
C1_CONV = "Первый контакт: конверсия, %"
C1_PC = "Первый контакт: сумма с контакта"
LK_SUM = "ЛК: сумма"
LK_CHECK = "ЛК: ср.чек"
LK_CONV = "ЛК: конверсия, %"
LK_PC = "ЛК: сумма с контакта"
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


def _row(fio):
    return {
        FIO: fio, STATUS: "", BONUS075: 0, BONUS2: 0,
        C1_SUM: 1000, C1_CHECK: 100, C1_CONV: 20, C1_PC: 100,
        LK_SUM: 500, LK_CHECK: 100, LK_CONV: 10, LK_PC: 50,
        RADIO_SUM: 1000, RADIO_CHECK: 100, RADIO_CONV: 10, RADIO_PC: 200,
        INET_SUM: 0, INET_CHECK: 0, INET_CONV: 0, INET_PC: 0,
        TIME_PC: 20, ERRORS_PCT: 1,
    }


def _group_row(label: str) -> dict:
    return {FIO: f"ГРУППА: {label}"}


def _build_excel_bytes(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def test_sector_label_prefix_is_stripped_from_group_name():
    raw = _build_excel_bytes([
        _group_row("С2 Супервайзер - Болотов Дмитрий Александрович"),
        _row("Сотрудник Первый"),
    ])
    employees = parse_weekly_rating_excel(raw)
    assert employees[0]["supervisor"] == "Супервайзер - Болотов Дмитрий Александрович"


def test_sector_label_prefix_stripped_with_no_space_after_dash():
    # Реальный вариант из файла: "Супервайзер-Иванушко ..." (без пробела
    # перед дефисом) — метка всё равно срезается.
    raw = _build_excel_bytes([
        _group_row("С1 Супервайзер-Иванушко Виталий Александрович"),
        _row("Сотрудник Первый"),
    ])
    employees = parse_weekly_rating_excel(raw)
    assert employees[0]["supervisor"] == "Супервайзер-Иванушко Виталий Александрович"


def test_sector_label_prefix_stripped_with_dot_dash():
    # Реальный вариант: "Супервайзер.- Клюйко ..."
    raw = _build_excel_bytes([
        _group_row("С1 Супервайзер.- Клюйко Анатолий Анатольевич"),
        _row("Сотрудник Первый"),
    ])
    employees = parse_weekly_rating_excel(raw)
    assert employees[0]["supervisor"] == "Супервайзер.- Клюйко Анатолий Анатольевич"


def test_group_name_without_sector_label_is_unaffected():
    raw = _build_excel_bytes([
        _group_row("Супервайзер - Иванов И.И."),
        _row("Сотрудник Первый"),
    ])
    employees = parse_weekly_rating_excel(raw)
    assert employees[0]["supervisor"] == "Супервайзер - Иванов И.И."


def test_sector_label_prefix_stripped_for_region_uk_group():
    raw = _build_excel_bytes([
        _group_row("С1 операторы без супервизора"),
        {FIO: "ЗДР Тестов Т. Т.", STATUS: "", BONUS075: 0, BONUS2: 0,
         C1_SUM: 1000, C1_CHECK: 100, C1_CONV: 20, C1_PC: 100,
         LK_SUM: 500, LK_CHECK: 100, LK_CONV: 10, LK_PC: 50,
         RADIO_SUM: 1000, RADIO_CHECK: 100, RADIO_CONV: 10, RADIO_PC: 200,
         INET_SUM: 0, INET_CHECK: 0, INET_CONV: 0, INET_PC: 0,
         TIME_PC: 20, ERRORS_PCT: 1},
    ])
    employees = parse_weekly_rating_excel(raw)
    assert employees[0]["supervisor"] == "операторы без супервизора"
    assert employees[0]["is_region_uk"] is True


def test_surname_starting_with_c_and_digit_like_pattern_is_not_mistaken():
    # Название группы, не начинающееся с "Супервайзер"/"Супервизор"/
    # "операторы" после цифры — метка не срезается (защита от ложного
    # срабатывания, хотя реальных фамилий вида "С2 ..." не встречалось).
    raw = _build_excel_bytes([
        _group_row("С2 Иванов И.И."),
        _row("Сотрудник Первый"),
    ])
    employees = parse_weekly_rating_excel(raw)
    assert employees[0]["supervisor"] == "С2 Иванов И.И."
