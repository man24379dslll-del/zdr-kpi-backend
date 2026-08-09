"""
"Регион УК" и "Выходы на Пики" — две виртуальные группы, на которые
excel_parsing.py делит группу "ГРУППА: операторы без супервизора"
(сборная солянка разных ролей: ЗДР/ПП/Увеличители вперемешку).
Разделение — по префиксу ФИО "ЗДР": такие сотрудники идут в "Регион УК",
остальные — в "Выходы на Пики". Обе группы — НЕ настоящие супервайзеры:
исключаются из сравнения/рейтинга супервайзеров между собой (если/когда
такая фича появится), но участвуют в основном рейтинге по группам
(включая ЛГ внутри своей "группы") как обычно.

Здесь — общая логика распознавания и отображаемое название группы,
используемая и при расчёте недельного рейтинга (weekly_rating.py), и в
ведомости ЗП (payroll.py), и в дашбордах (dashboards.py).
"""
from __future__ import annotations

import re

REGION_UK_GROUP_RE = re.compile(r"операторы\s+без\s+супервизора", re.IGNORECASE)
PEAKS_GROUP_RE = re.compile(r"операторы\s+без\s+супервизора\s*\[Пики\]", re.IGNORECASE)
PEAKS_SUFFIX = " [Пики]"

# cleanSupervisorName() из старой JS-версии — префиксы вида
# "Супервайзер - "/"Супервайзер.- "/"Супервизор " перед именем обычного
# супервайзера. Порядок важен: сначала более длинный "Супервайзер...".
_SUPERVISOR_PREFIX_RE = re.compile(r"^Супервайзер[.\-–\s]+", re.IGNORECASE)
_SUPERVIZOR_PREFIX_RE = re.compile(r"^Супервизор\s*", re.IGNORECASE)

# Тир ЛК жёстко завязан на 5 стандартных категорий (см. weekly_rating.py) —
# "Регион УК" считается только по этим трём, без канала и % ошибок.
REGION_UK_SCORE_KEYS = {"c1", "lk", "time"}


def is_region_uk_or_peaks_supervisor(supervisor: str | None) -> bool:
    """True для ОБЕИХ виртуальных групп (совпадает по общему префиксу
    "операторы без супервизора" — как для "Регион УК", так и для
    "Выходы на Пики", у которой строка supervisor заканчивается на
    " [Пики]")."""
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
    if PEAKS_GROUP_RE.search(supervisor):
        return "Выходы на Пики"
    if REGION_UK_GROUP_RE.search(supervisor):
        return "Регион УК"
    return clean_supervisor_name(supervisor)
