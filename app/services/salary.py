"""
ЗП недели: (недельная база + бонус075 + бонус2) × коэффициент ЛГ
ПРОШЛОЙ недели. Точный перенос assignSalary из старой JS-версии.

  weekBase = MONTHLY_BASE_RATE / weeksInMonth   (MONTHLY_BASE_RATE — см.
                                                  services/ladder_groups.py)
  salary = (weekBase + bonus075 + bonus2) × coefficient

Коэффициент — НЕ из этой же недели (тир/коэффициент этой недели
описывает результат ЭТОЙ недели, а не то, что человек уже заработал к
её началу), а из результата ПРЕДЫДУЩЕЙ недели (ищет и передаёт вызывающая
сторона через services/periods.find_previous_period — переход через
границу месяца обрабатывается корректно, см. routers/ratings.py). Если
прошлой недели нет, или человека там не было — коэффициент = 1.0.

Применяется ТОЛЬКО к недельным периодам (period_label вида
"месяц-неделя"), не к дневным — это тоже решает вызывающая сторона
(routers/ratings.py), сама функция такого решения не принимает.
"""
from __future__ import annotations

from app.services.ladder_groups import MONTHLY_BASE_RATE
from app.services.rating_engine import EmployeeScore


def assign_salary(
    results: list[EmployeeScore],
    prev_coefficient_by_fio: dict[str, float],
    weeks_in_month: int,
) -> None:
    """Модифицирует results на месте: проставляет r.salary у каждого."""
    week_base = MONTHLY_BASE_RATE / weeks_in_month
    for r in results:
        bonus075 = r.raw.get("bonus075") or 0
        bonus2 = r.raw.get("bonus2") or 0
        coefficient = prev_coefficient_by_fio.get(r.fio)
        if coefficient is None:
            coefficient = 1.0
        r.salary = (week_base + bonus075 + bonus2) * coefficient
