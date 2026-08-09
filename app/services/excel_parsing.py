"""
Разбор недельного Excel-файла — вынесено из routers/ratings.py в отдельный
сервисный модуль, чтобы не тянуть за собой app.auth/app.config (требует
реальные SUPABASE_* переменные окружения) там, где нужен только сам разбор
и расчёт — например, в тестах.

Точные заголовки колонок (сверено с реальными файлами, не предположение):

  A  ФИО
  B  Статус (уровень)
  C  0.75% за офор.                    <- бонус для ЗП
  D  2% за дост.                       <- бонус для ЗП
  E  Первый контакт: кол-во            <- необязательная, см. ниже
  F  Первый контакт: сумма
  G  Первый контакт: ср.чек
  H  Первый контакт: конверсия, %
  I  Первый контакт: сумма с контакта
  J  ЛК: кол-во                        <- необязательная
  K  ЛК: сумма
  L  ЛК: ср.чек
  M  ЛК: конверсия, %
  N  ЛК: сумма с контакта
  O  Радио + ТВ: кол-во                <- необязательная
  P  Радио + ТВ: сумма
  Q  Радио + ТВ: ср.чек
  R  Радио + ТВ: конверсия, %
  S  Радио + ТВ: сумма с контакта
  T  Интернет: кол-во                  <- необязательная (на практике не встречалась)
  U  Интернет: сумма
  V  Интернет: ср.чек
  W  Интернет: конверсия, %
  X  Интернет: сумма с контакта
  Y  Время/контакт, мин
  Z  % Постобработки (ПО)              <- не используется в расчёте, не читаем
  AA % Сервисного времени              <- не используется в расчёте, не читаем
  AB Ошибок                            <- не используется в расчёте (берём AC)
  AC Ошибок, %                         <- это и есть errors_pct

"Кол-во" (карточки) колонки ненадёжны между версиями файла: в старых
файлах их не было вообще ни у одного канала, у "Первый контакт" в части
файлов вместо "Первый контакт: кол-во" встречается "Карточек (Первый
контакт)", а "Интернет: кол-во" не встречалась ни разу. Поэтому эти 4
колонки — необязательные: пробуем известные варианты названия, если не
нашли — оставляем None, парсер не падает.

Один сотрудник работает только с одним из двух каналов (Радио+ТВ ИЛИ
Интернет) — у него реально заполнена сумма только по одному из двух
блоков колонок, другой стоит нулём. _pick_channel() определяет, какой
канал использован, по наибольшей сумме, и кладёт его как ch_*/'channel'
('radio'|'inet') — единая категория "канал" из конструктора рейтинга
работает с этими унифицированными полями, не зная про радио/интернет.

Группы сотрудников: строка вида "ГРУППА: <название>" в колонке A
предшествует сотрудникам этой группы (действует до следующей строки
"ГРУППА:"). Само название группы (после "ГРУППА:") — это то, что
дальше пишется в kpi_ratings.supervisor. Группа "операторы без
супервизора" (регистр не важен) — обычная группа, без особой обработки.
"""
from __future__ import annotations

import io

import pandas as pd
from fastapi import HTTPException, status

FIO_COLUMN = "ФИО"
STATUS_COLUMN = "Статус (уровень)"
BONUS075_COLUMN = "0.75% за офор."
BONUS2_COLUMN = "2% за дост."

C1_COUNT_COLUMN = "Первый контакт: кол-во"
C1_COUNT_FALLBACK_COLUMN = "Карточек (Первый контакт)"
C1_SUM_COLUMN = "Первый контакт: сумма"
C1_CHECK_COLUMN = "Первый контакт: ср.чек"
C1_CONV_COLUMN = "Первый контакт: конверсия, %"
C1_PER_CONTACT_COLUMN = "Первый контакт: сумма с контакта"

LK_COUNT_COLUMN = "ЛК: кол-во"
LK_SUM_COLUMN = "ЛК: сумма"
LK_CHECK_COLUMN = "ЛК: ср.чек"
LK_CONV_COLUMN = "ЛК: конверсия, %"
LK_PER_CONTACT_COLUMN = "ЛК: сумма с контакта"

RADIO_COUNT_COLUMN = "Радио + ТВ: кол-во"
RADIO_SUM_COLUMN = "Радио + ТВ: сумма"
RADIO_CHECK_COLUMN = "Радио + ТВ: ср.чек"
RADIO_CONV_COLUMN = "Радио + ТВ: конверсия, %"
RADIO_PER_CONTACT_COLUMN = "Радио + ТВ: сумма с контакта"

INET_COUNT_COLUMN = "Интернет: кол-во"
INET_SUM_COLUMN = "Интернет: сумма"
INET_CHECK_COLUMN = "Интернет: ср.чек"
INET_CONV_COLUMN = "Интернет: конверсия, %"
INET_PER_CONTACT_COLUMN = "Интернет: сумма с контакта"

TIME_PER_CONTACT_COLUMN = "Время/контакт, мин"
ERRORS_PCT_COLUMN = "Ошибок, %"

GROUP_ROW_PREFIX = "группа:"

# Всё, кроме 4 "кол-во"-колонок (E/J/O/T) — они необязательные, см. докстринг.
_MANDATORY_COLUMNS = {
    FIO_COLUMN, STATUS_COLUMN, BONUS075_COLUMN, BONUS2_COLUMN,
    C1_SUM_COLUMN, C1_CHECK_COLUMN, C1_CONV_COLUMN, C1_PER_CONTACT_COLUMN,
    LK_SUM_COLUMN, LK_CHECK_COLUMN, LK_CONV_COLUMN, LK_PER_CONTACT_COLUMN,
    RADIO_SUM_COLUMN, RADIO_CHECK_COLUMN, RADIO_CONV_COLUMN, RADIO_PER_CONTACT_COLUMN,
    INET_SUM_COLUMN, INET_CHECK_COLUMN, INET_CONV_COLUMN, INET_PER_CONTACT_COLUMN,
    TIME_PER_CONTACT_COLUMN, ERRORS_PCT_COLUMN,
}

# Н/О: статус новичка/тренера/руководителя/отпуска/больничного, либо
# нулевые продажи по 1 обращению — как в старой JS-версии. Не влияет на
# попадание в тир ЛК (A/Б/В), только на итоговое место рейтинга и ЛГ.
NA_STATUSES = {"тренер", "руководитель", "отпуск", "больничный"}


def is_na_row(row: dict) -> bool:
    status_value = str(row.get("status") or "").strip().lower()
    if status_value.startswith("новичок") or status_value in NA_STATUSES:
        return True
    return (row.get("c1_sum") or 0) == 0


def _text(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _num(value, default: float = 0.0) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_value(row: pd.Series, *column_names: str):
    for name in column_names:
        value = row.get(name)
        if value is not None and not (isinstance(value, float) and pd.isna(value)):
            return value
    return None


def _optional_num(row: pd.Series, *column_names: str) -> float | None:
    value = _first_value(row, *column_names)
    return None if value is None else _num(value)


def _pick_channel(row: pd.Series) -> tuple[str, dict]:
    """Определяет, каким каналом реально пользовался сотрудник (у него
    заполнена сумма только по одному из двух блоков колонок); при обоих
    нулях (Н/О, нет данных) по умолчанию считаем 'radio' — на итоговый
    счёт это не влияет, т.к. все значения нулевые."""
    radio_sum = _num(row.get(RADIO_SUM_COLUMN))
    inet_sum = _num(row.get(INET_SUM_COLUMN))
    if inet_sum > radio_sum:
        return "inet", {
            "ch_sum": inet_sum,
            "ch_check": _num(row.get(INET_CHECK_COLUMN)),
            "ch_conv": _num(row.get(INET_CONV_COLUMN)),
            "ch_per_contact": _num(row.get(INET_PER_CONTACT_COLUMN)),
            "ch_cards": _optional_num(row, INET_COUNT_COLUMN),
        }
    return "radio", {
        "ch_sum": radio_sum,
        "ch_check": _num(row.get(RADIO_CHECK_COLUMN)),
        "ch_conv": _num(row.get(RADIO_CONV_COLUMN)),
        "ch_per_contact": _num(row.get(RADIO_PER_CONTACT_COLUMN)),
        "ch_cards": _optional_num(row, RADIO_COUNT_COLUMN),
    }


def parse_weekly_rating_excel(raw: bytes) -> list[dict]:
    """Разбирает загруженный xlsx в список сырых строк по сотрудникам,
    разбитым на группы супервайзеров по строкам "ГРУППА: ...".
    Поднимает HTTPException(400), если не хватает обязательных колонок."""
    df = pd.read_excel(io.BytesIO(raw))

    missing = _MANDATORY_COLUMNS - set(df.columns)
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"В файле не хватает колонок: {', '.join(sorted(missing))}. "
            f"Есть: {', '.join(df.columns.astype(str))}",
        )

    employees = []
    current_supervisor: str | None = None

    for _, row in df.iterrows():
        fio = _text(row.get(FIO_COLUMN))
        if not fio:
            continue
        if fio.lower().startswith(GROUP_ROW_PREFIX):
            current_supervisor = fio[len(GROUP_ROW_PREFIX):].strip()
            continue

        status_text = _text(row.get(STATUS_COLUMN))
        channel, channel_values = _pick_channel(row)

        employees.append({
            "fio": fio,
            "supervisor": current_supervisor,
            "status": status_text,
            "is_novice": status_text.lower().startswith("новичок"),
            "bonus075": _num(row.get(BONUS075_COLUMN)),
            "bonus2": _num(row.get(BONUS2_COLUMN)),

            "c1_sum": _num(row.get(C1_SUM_COLUMN)),
            "c1_check": _num(row.get(C1_CHECK_COLUMN)),
            "c1_conv": _num(row.get(C1_CONV_COLUMN)),
            "c1_per_contact": _num(row.get(C1_PER_CONTACT_COLUMN)),
            "c1_cards": _optional_num(row, C1_COUNT_COLUMN, C1_COUNT_FALLBACK_COLUMN),

            "lk_sum": _num(row.get(LK_SUM_COLUMN)),
            "lk_check": _num(row.get(LK_CHECK_COLUMN)),
            "lk_conv": _num(row.get(LK_CONV_COLUMN)),
            "lk_per_contact": _num(row.get(LK_PER_CONTACT_COLUMN)),
            "lk_cards": _optional_num(row, LK_COUNT_COLUMN),

            "channel": channel,
            **channel_values,

            "time_per_contact": _num(row.get(TIME_PER_CONTACT_COLUMN)),
            "errors_pct": _num(row.get(ERRORS_PCT_COLUMN)),
        })

    return employees
