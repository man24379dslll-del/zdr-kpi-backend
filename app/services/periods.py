"""
Сортировка/поиск "предыдущего периода" по kpi_uploads.period_label.
Точный перенос periodSortValue/findPreviousPeriod из старой JS-версии.
Используется формулой ЗП (services/salary.py, коэффициент ЛГ прошлой
недели) — routers/ratings.py.

period_label бывает двух видов:
  - "неделя": "месяц-неделя", например "7-1" -> sort value = месяц*10 + неделя
  - "день": "ГГГГ-ММ-ДД", сортируется как обычная строка

Поиск "предыдущего" — среди ВСЕХ периодов такого же типа, БЕЗ
ограничения "тот же месяц": неделя 1 августа (8*10+1=81) естественно
находит неделю 5 июля (7*10+5=75) как ближайшую меньшую, раз 75 < 81 и
это максимум среди меньших значений.

Год в недельном period_label не участвует (его там просто нет) — это
осознанное ограничение самой старой системы (не наше), переход через
границу ГОДА (декабрь -> январь) этой схемой не различается. Не
исправляем: в реальности такой стык историй пока не встречался.
"""
from __future__ import annotations

import re

WEEK_LABEL_RE = re.compile(r"^(\d+)-(\d+)$")


def period_sort_value(period_type: str, period_label: str | None):
    """period_type: 'week' | 'day'. Для 'day' — сама строка (ГГГГ-ММ-ДД
    сортируется лексикографически верно). Для 'week' — месяц*10+неделя
    (номер недели у нас 1..5, множитель 10 — с запасом). "" — если
    period_label не распознан под этот тип."""
    if period_type == "day":
        return period_label or ""
    m = WEEK_LABEL_RE.match(period_label or "")
    if not m:
        return ""
    return int(m.group(1)) * 10 + int(m.group(2))


def find_previous_period(periods: list[dict], current_label: str, period_type: str) -> dict | None:
    """periods: [{"period_label": ..., ...}, ...] (обычно строки kpi_uploads).
    Возвращает период с наибольшим sort value СРЕДИ ТЕХ, ЧТО МЕНЬШЕ
    текущего (ближайший предыдущий) — среди ВСЕХ periods этого типа, без
    ограничения "тот же месяц". None, если такого нет."""
    current_value = period_sort_value(period_type, current_label)
    if current_value == "":
        return None

    best = None
    best_value = None
    for p in periods:
        label = p.get("period_label")
        if label == current_label:
            continue
        value = period_sort_value(period_type, label)
        if value == "" or value >= current_value:
            continue
        if best_value is None or value > best_value:
            best_value = value
            best = p
    return best
