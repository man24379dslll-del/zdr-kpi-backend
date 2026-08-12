"""
Разбор недельного Excel-файла — вынесено из routers/ratings.py в отдельный
сервисный модуль, чтобы не тянуть за собой app.auth/app.config (требует
реальные SUPABASE_* переменные окружения) там, где нужен только сам разбор
и расчёт — например, в тестах.

Точные заголовки колонок (сверено с реальными файлами, не предположение):

  A  ФИО
  B  Статус (уровень)
  C  0.75% за офор.                    <- бонус для ЗП; число в начале названия
  D  2% за дост.                       <- бонус для ЗП; меняется от файла к файлу
                                           (напр. "3.5% за дост."), поэтому эти 2
                                           колонки ищутся по ОКОНЧАНИЮ названия, не
                                           по точному совпадению — см. _find_col_by_suffix
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
  Y  Время/контакт, мин                <- НЕ используется в расчёте (см. Z ниже)
  Z  Время/контакт без звонка, мин     <- это и есть TIME_PER_CONTACT_COLUMN, вот
                                           она участвует в категории "время"
                                           (по прямому запросу заказчика: считаем
                                           по времени без звонка, не по Y)
  AA % Постобработки (ПО)              <- не используется в расчёте, не читаем
  AB % Сервисного времени              <- не используется в расчёте, не читаем
  AC Ошибок                            <- сырое число, errors_count — только для
                                           информации, НЕ участвует в местах/расчёте
                                           (необязательная колонка)
  AD Ошибок, %                         <- это и есть errors_pct, вот она участвует в расчёте
  AE Производительность                <- не используется в расчёте, не читаем
  AF Рабочее время, ч                  <- участвует в формуле ЗП, см. WORK_HOURS_COLUMN
  AG Норма за месяц, ч                 <- не используется (ставка/норма настраиваются
                                           отдельно через интерфейс, см. services/salary.py)
  AH Кол-во смен                       <- чисто информационная, см. SHIFT_COUNT_COLUMN
  AI Урезания по часам, ч              <- не используется в расчёте, не читаем

"Кол-во" (карточки) колонки ненадёжны между версиями файла: в старых
файлах их не было вообще ни у одного канала, у "Первый контакт" в части
файлов вместо "Первый контакт: кол-во" встречается "Карточек (Первый
контакт)", а "Интернет: кол-во" не встречалась ни разу. Поэтому эти 4
колонки — необязательные: пробуем известные варианты названия, если не
нашли — оставляем None, парсер не падает.

Один сотрудник работает только с одним из двух каналов (Радио+ТВ ИЛИ
Интернет), но КАКОЙ именно — нельзя надёжно определить по суммам в
файле: проверено на реальных данных, эвристика "больше сумма" ошибается
примерно в 40% случаев (у части супервайзеров исторически больше денег
идёт по чужому каналу — например промо по радио, но много случайных
заходов с интернет-рекламы не их зоны ответственности). Поэтому канал —
это НАСТРОЙКА (таблица supervisor_channels, админ вводит вручную через
/supervisor-channels), а не вычисляемое поле.

_pick_channel() сначала ищет супервайзера в supervisor_channels
(сначала точное совпадение после нормализации, затем — по вхождению
фамилии, т.к. пунктуация в названии группы может отличаться между
периодами); если совпадения нет — использует эвристику "больше сумма"
как временную заглушку и помечает 'channel_is_guessed': True в строке
сотрудника, чтобы фронтенд мог это подсветить и предложить подтвердить
(так же было в старой JS-версии).

Группы сотрудников: строка вида "ГРУППА: <название>" в колонке A
предшествует сотрудникам этой группы (действует до следующей строки
"ГРУППА:"). Само название группы (после "ГРУППА:") — это то, что
дальше пишется в kpi_ratings.supervisor.

Особый случай — группа "операторы без супервизора" (сборная солянка
разных ролей, ФИО-префиксы ЗДР/ПП/Увеличители вперемешку): делится на
две ВИРТУАЛЬНЫЕ группы по префиксу ФИО "ЗДР" — см. app/services/group_naming.py.
Сотрудники с префиксом "ЗДР" остаются в группе "операторы без
супервизора" (employee['is_region_uk'] = True — их total_score считает
только по c1/lk/time, см. weekly_rating.py), остальные уходят в группу
"операторы без супервизора [Пики]" (is_region_uk=False — полный набор
категорий, как у обычных групп).
"""
from __future__ import annotations

import io
import re

import pandas as pd
from fastapi import HTTPException, status

from app.services.group_naming import PEAKS_SUFFIX, REGION_UK_GROUP_RE

FIO_COLUMN = "ФИО"
STATUS_COLUMN = "Статус (уровень)"
# Число в начале названия этих 2 колонок меняется от файла к файлу
# ("0.75% за офор.", "2%"/"3.5% за дост.") — ищем по ОКОНЧАНИЮ названия
# (см. _find_col_by_suffix), не по точному совпадению целиком. Раньше
# были захардкожены как точные строки и как обязательные — падало 400
# на любом файле, где процент отличался от "2%"; это исправлено.
BONUS075_SUFFIX = "за офор."
BONUS2_SUFFIX = "за дост."

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

# "Время/контакт БЕЗ ЗВОНКА" (не путать с "Время/контакт, мин" — та
# колонка тоже есть в файле, но в расчёт НЕ идёт), по прямому запросу
# заказчика: категория "время" в рейтинге считается по времени без звонка.
TIME_PER_CONTACT_COLUMN = "Время/контакт без звонка, мин"
ERRORS_PCT_COLUMN = "Ошибок, %"
ERRORS_COUNT_COLUMN = "Ошибок"  # сырое число, необязательная, только для информации

# Рабочее время за период (часы) — участвует в формуле ЗП (см.
# services/salary.py: база_недели = ставка_за_час × work_hours).
# Необязательная колонка: без неё ЗП для этого периода честно посчитать
# нельзя (не 0 часов, а НЕИЗВЕСТНО), поэтому salary остаётся None, а не
# падает разбор целиком — вызывающая сторона (routers/ratings.py) обязана
# предупредить об этом в логе, аналогично salaryMissing для бонусов.
WORK_HOURS_COLUMN = "Рабочее время, ч"

# Кол-во смен — чисто информационная колонка (в формулу ЗП НЕ входит,
# в отличие от work_hours выше), выводится в таблице рядом для справки.
SHIFT_COUNT_COLUMN = "Кол-во смен"

GROUP_ROW_PREFIX = "группа:"

# Всё, кроме 4 "кол-во"-колонок (E/J/O/T) и 2 бонусных (ищутся по
# суффиксу, см. BONUS075_SUFFIX/BONUS2_SUFFIX) — они необязательные, см. докстринг.
_MANDATORY_COLUMNS = {
    FIO_COLUMN, STATUS_COLUMN,
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


def _find_col_by_suffix(columns, suffix: str) -> str | None:
    """Аналог JS findColBySuffix — ищет колонку по ОКОНЧАНИЮ названия, а не
    по точному совпадению целиком (число в начале названия бонусных
    колонок меняется от файла к файлу). Возвращает None, если не нашли —
    парсер не должен падать из-за этого, см. _MANDATORY_COLUMNS."""
    for col in columns:
        if str(col).strip().endswith(suffix):
            return col
    return None


def _normalize_supervisor(text: str) -> str:
    """Убирает "супервайзер"/"супервизор" и пунктуацию, схлопывает пробелы —
    чтобы "Супервайзер - Иванов И.И." и "Супервизор.Иванов И.И." совпали."""
    text = text.lower()
    text = re.sub(r"супервайзер|супервизор", " ", text)
    text = re.sub(r"[^а-яёa-z\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _match_supervisor_channel(supervisor: str | None, supervisor_channels: dict[str, str]) -> str | None:
    """Ищет канал для супервайзера: сначала точное совпадение после
    нормализации, потом — по вхождению фамилии (первое слово нормализованной
    строки в конфиге), т.к. пунктуация в названии группы плывёт между
    периодами. Возвращает None, если совпадений нет вообще."""
    if not supervisor:
        return None
    normalized_target = _normalize_supervisor(supervisor)
    if not normalized_target:
        return None

    normalized_map = {_normalize_supervisor(k): v for k, v in supervisor_channels.items()}
    if normalized_target in normalized_map:
        return normalized_map[normalized_target]

    for config_supervisor, channel in supervisor_channels.items():
        normalized_config = _normalize_supervisor(config_supervisor)
        surname = normalized_config.split(" ", 1)[0] if normalized_config else ""
        if surname and surname in normalized_target:
            return channel

    return None


def _pick_channel(row: pd.Series, supervisor: str | None, supervisor_channels: dict[str, str]) -> tuple[str, bool, dict]:
    """Канал — настройка (supervisor_channels), не вычисляемое поле, см.
    докстринг модуля. Если для супервайзера ещё нет записи — используем
    эвристику "больше сумма" как заглушку и возвращаем is_guessed=True."""
    radio_sum = _num(row.get(RADIO_SUM_COLUMN))
    inet_sum = _num(row.get(INET_SUM_COLUMN))

    matched = _match_supervisor_channel(supervisor, supervisor_channels)
    if matched is not None:
        channel, is_guessed = matched, False
    else:
        channel, is_guessed = ("inet" if inet_sum > radio_sum else "radio"), True

    if channel == "inet":
        values = {
            "ch_sum": inet_sum,
            "ch_check": _num(row.get(INET_CHECK_COLUMN)),
            "ch_conv": _num(row.get(INET_CONV_COLUMN)),
            "ch_per_contact": _num(row.get(INET_PER_CONTACT_COLUMN)),
            "ch_cards": _optional_num(row, INET_COUNT_COLUMN),
        }
    else:
        values = {
            "ch_sum": radio_sum,
            "ch_check": _num(row.get(RADIO_CHECK_COLUMN)),
            "ch_conv": _num(row.get(RADIO_CONV_COLUMN)),
            "ch_per_contact": _num(row.get(RADIO_PER_CONTACT_COLUMN)),
            "ch_cards": _optional_num(row, RADIO_COUNT_COLUMN),
        }
    return channel, is_guessed, values


def parse_weekly_rating_excel(raw: bytes, supervisor_channels: dict[str, str] | None = None) -> list[dict]:
    """Разбирает загруженный xlsx в список сырых строк по сотрудникам,
    разбитым на группы супервайзеров по строкам "ГРУППА: ...".
    Поднимает HTTPException(400), если не хватает обязательных колонок.

    supervisor_channels: {название супервайзера (как в supervisor_channels) -> 'radio'|'inet'},
    обычно результат GET /supervisor-channels. Без совпадения канал
    угадывается по сумме и помечается employee['channel_is_guessed'] = True."""
    supervisor_channels = supervisor_channels or {}
    df = pd.read_excel(io.BytesIO(raw))

    missing = _MANDATORY_COLUMNS - set(df.columns)
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"В файле не хватает колонок: {', '.join(sorted(missing))}. "
            f"Есть: {', '.join(df.columns.astype(str))}",
        )

    bonus075_col = _find_col_by_suffix(df.columns, BONUS075_SUFFIX)
    bonus2_col = _find_col_by_suffix(df.columns, BONUS2_SUFFIX)

    employees = []
    current_supervisor: str | None = None
    current_peaks_supervisor: str | None = None
    current_group_splits_region_uk = False

    for _, row in df.iterrows():
        fio = _text(row.get(FIO_COLUMN))
        if not fio:
            continue
        if fio.lower().startswith(GROUP_ROW_PREFIX):
            current_supervisor = fio[len(GROUP_ROW_PREFIX):].strip()
            current_group_splits_region_uk = bool(REGION_UK_GROUP_RE.search(current_supervisor))
            current_peaks_supervisor = (
                current_supervisor + PEAKS_SUFFIX if current_group_splits_region_uk else None
            )
            continue

        if current_group_splits_region_uk:
            is_region_uk = fio.upper().startswith("ЗДР")
            supervisor = current_supervisor if is_region_uk else current_peaks_supervisor
        else:
            is_region_uk = False
            supervisor = current_supervisor

        status_text = _text(row.get(STATUS_COLUMN))
        channel, channel_is_guessed, channel_values = _pick_channel(row, supervisor, supervisor_channels)

        employees.append({
            "fio": fio,
            "supervisor": supervisor,
            "is_region_uk": is_region_uk,
            "status": status_text,
            "is_novice": status_text.lower().startswith("новичок"),
            "bonus075": _num(row.get(bonus075_col)) if bonus075_col else None,
            "bonus2": _num(row.get(bonus2_col)) if bonus2_col else None,

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
            "channel_is_guessed": channel_is_guessed,
            **channel_values,

            "time_per_contact": _num(row.get(TIME_PER_CONTACT_COLUMN)),
            "errors_pct": _num(row.get(ERRORS_PCT_COLUMN)),
            "errors_count": _optional_num(row, ERRORS_COUNT_COLUMN),
            "work_hours": _optional_num(row, WORK_HOURS_COLUMN),
            "shift_count": _optional_num(row, SHIFT_COUNT_COLUMN),
        })

    return employees
