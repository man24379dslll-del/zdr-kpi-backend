"""
"Регион УК", "ПП" и "Увеличители" — три виртуальные группы, на которые
excel_parsing.py делит группу "ГРУППА: операторы без супервизора"
(сборная солянка разных ролей: ЗДР/ПП/Увеличители вперемешку).
Разделение — по префиксу ФИО: "ЗДР" -> "Регион УК", "ПП" -> "ПП",
"Увеличители" -> "Увеличители". Раньше "ПП" и "Увеличители" были одной
общей группой "Выходы на Пики" — по прямому запросу заказчика разделены
на две отдельные группы (у каждой свой рейтинг/ЛГ, но те же особые
правила, что были у общей "Пики", см. ниже). Все три группы — НЕ
настоящие супервайзеры: исключаются из сравнения/рейтинга супервайзеров
между собой, но участвуют в основном рейтинге по группам (включая ЛГ
внутри своей "группы") как обычно.

"ПП" и "Увеличители" (бывшая объединённая "Пики") дополнительно
исключаются из часовой ставки в формуле ЗП (см. services/salary.py) —
это тоже общий признак PEAKS_GROUP_RE, а не что-то специфичное для
одной из двух подгрупп.

Здесь — общая логика распознавания и отображаемое название группы,
используемая и при расчёте недельного рейтинга (weekly_rating.py), и в
ведомости ЗП (payroll.py), и в дашбордах (dashboards.py).
"""
from __future__ import annotations

import re

REGION_UK_GROUP_RE = re.compile(r"операторы\s+без\s+супервизора", re.IGNORECASE)
PEAKS_PP_GROUP_RE = re.compile(r"операторы\s+без\s+супервизора\s*\[Пики-ПП\]", re.IGNORECASE)
PEAKS_UVELICHITELI_GROUP_RE = re.compile(r"операторы\s+без\s+супервизора\s*\[Пики-Увеличители\]", re.IGNORECASE)
# Общий признак ОБЕИХ подгрупп бывшей "Пики" — используется там, где
# правило одинаково для "ПП" и "Увеличители" (исключение из часовой
# ставки в ЗП, см. salary.py). НЕ путать с REGION_UK_GROUP_RE — тот
# матчит ещё и "Регион УК" (голое "операторы без супервизора").
PEAKS_GROUP_RE = re.compile(
    r"операторы\s+без\s+супервизора\s*\[Пики-(?:ПП|Увеличители)\]", re.IGNORECASE
)
PEAKS_PP_SUFFIX = " [Пики-ПП]"
PEAKS_UVELICHITELI_SUFFIX = " [Пики-Увеличители]"

# cleanSupervisorName() из старой JS-версии — префиксы вида
# "Супервайзер - "/"Супервайзер.- "/"Супервизор " перед именем обычного
# супервайзера. Порядок важен: сначала более длинный "Супервайзер...".
_SUPERVISOR_PREFIX_RE = re.compile(r"^Супервайзер[.\-–\s]+", re.IGNORECASE)
_SUPERVIZOR_PREFIX_RE = re.compile(r"^Супервизор\s*", re.IGNORECASE)

# Тир ЛК жёстко завязан на 5 стандартных категорий (см. weekly_rating.py) —
# "Регион УК" считается только по этим трём, без канала и % ошибок.
# "ПП"/"Увеличители" — полный набор категорий, как у обычных групп (это
# НЕ входит в REGION_UK_SCORE_KEYS, weekly_rating.py применяет урезание
# только к employee['is_region_uk']==True, а он True только у ЗДР).
REGION_UK_SCORE_KEYS = {"c1", "lk", "time"}


def is_region_uk_or_peaks_supervisor(supervisor: str | None) -> bool:
    """True для ВСЕХ ТРЁХ виртуальных групп (совпадает по общему префиксу
    "операторы без супервизора" — для "Регион УК", "ПП" и "Увеличители",
    у двух последних supervisor заканчивается на " [Пики-ПП]"/
    " [Пики-Увеличители]")."""
    return bool(supervisor) and bool(REGION_UK_GROUP_RE.search(supervisor))


def clean_supervisor_name(name: str | None) -> str:
    """Убирает префикс "Супервайзер - "/"Супервайзер.- "/"Супервизор " перед
    именем обычного супервайзера. Точный перенос cleanSupervisorName()."""
    name = name or ""
    name = _SUPERVISOR_PREFIX_RE.sub("", name)
    name = _SUPERVIZOR_PREFIX_RE.sub("", name)
    return name.strip()


def display_group_name(supervisor: str | None) -> str:
    """Человекочитаемое название группы для API-ответов/фронтенда."""
    if not supervisor:
        return ""
    if PEAKS_PP_GROUP_RE.search(supervisor):
        return "ПП"
    if PEAKS_UVELICHITELI_GROUP_RE.search(supervisor):
        return "Увеличители"
    if REGION_UK_GROUP_RE.search(supervisor):
        return "Регион УК"
    return clean_supervisor_name(supervisor)
