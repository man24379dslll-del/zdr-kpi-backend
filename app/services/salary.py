"""
ЗП недели: часовая ставка (БЕЗ умножения на коэффициент) + бонусы
(бонус075 + бонус2) × коэффициент ЛГ ПРОШЛОЙ недели.

ПОЛНАЯ ЗАМЕНА старой формулы (была: MONTHLY_BASE_RATE / weeks_in_month,
не зависела от реально отработанного времени). Новая формула:

  ставка_за_час = monthly_base_rate / hours_norm
  week_base      = ставка_за_час × work_hours (рабочее время СОТРУДНИКА
                    за эту неделю, из колонки "Рабочее время, ч" исходного
                    Excel-файла — см. services/excel_parsing.py)
  salary         = week_base + (бонус075 + бонус2) × coefficient

ВАЖНО: коэффициент умножает ТОЛЬКО сумму бонусов, НЕ week_base — это
отличается от порядка операций в старой формуле, где коэффициент
умножал ВСЮ сумму (база+бонусы) целиком. Часовая ставка идёт отдельным
слагаемым, без умножения на коэффициент.

monthly_base_rate/hours_norm — настраиваемые заказчиком числа (по
умолчанию 40000/160), а не жёстко зашитые константы; передаёт вызывающая
сторона (routers/ratings.py), как раньше передавала weeks_in_month.

work_hours теперь ОБЯЗАТЕЛЬНО для честного расчёта ЗП (в отличие от
более раннего решения "смены/часы не влияют на деньги" — это решение
отменено). Если у сотрудника нет work_hours (колонки не было в файле,
либо конкретная ячейка пуста) — week_base посчитать нельзя (это не "0
часов", а "неизвестно"), поэтому salary = None целиком, а не просто
без базы: null явно виден в интерфейсе, тогда как "0 + бонусы" выглядел
бы как настоящая (заниженная) ЗП и мог остаться незамеченным.

Коэффициент — НЕ из этой же недели (тир/коэффициент этой недели
описывает результат ЭТОЙ недели, а не то, что человек уже заработал к
её началу), а из результата ПРЕДЫДУЩЕЙ недели (ищет и передаёт вызывающая
сторона через services/periods.find_previous_period — переход через
границу месяца обрабатывается корректно, см. routers/ratings.py). Если
прошлой недели нет, или человека там не было — коэффициент = 1.0.

Если сотрудник Н/О ЭТОЙ недели (r.is_na — любая причина: новичок,
отпуск, больничный, тренер, нулевые продажи), коэффициент из прошлой
недели floor'ится до 1.0, если он был ниже — по прямому запросу
заказчика: Н/О недели не должна "наказываться" низким коэффициентом,
заработанным раньше. Новичков это на практике не меняет: их
coefficient уже >= 1.0 по построению (см. ladder_groups.
assign_novice_coefficients) — floor тут общий, а не специфичный для них.

Применяется ТОЛЬКО к недельным периодам (period_label вида
"месяц-неделя"), не к дневным — это тоже решает вызывающая сторона
(routers/ratings.py), сама функция такого решения не принимает.
"""
from __future__ import annotations

from app.services.rating_engine import EmployeeScore

DEFAULT_MONTHLY_BASE_RATE = 40000
DEFAULT_HOURS_NORM = 160


def assign_salary(
    results: list[EmployeeScore],
    prev_coefficient_by_fio: dict[str, float],
    hours_norm: float = DEFAULT_HOURS_NORM,
    monthly_base_rate: float = DEFAULT_MONTHLY_BASE_RATE,
) -> None:
    """Модифицирует results на месте: проставляет r.salary у каждого.

    hours_norm/monthly_base_rate: см. докстринг модуля — по умолчанию
    160/40000, но обычно заказчик задаёт свои значения через интерфейс.
    """
    hourly_rate = monthly_base_rate / hours_norm
    for r in results:
        work_hours = r.raw.get("work_hours")
        if work_hours is None:
            r.salary = None
            continue
        bonus075 = r.raw.get("bonus075") or 0
        bonus2 = r.raw.get("bonus2") or 0
        week_base = hourly_rate * work_hours
        coefficient = prev_coefficient_by_fio.get(r.fio)
        if coefficient is None:
            coefficient = 1.0
        elif r.is_na and coefficient < 1.0:
            # Н/О ЭТОЙ недели (любая причина — новичок, отпуск, больничный,
            # тренер, нулевые продажи) никогда не наказывается заниженным
            # коэффициентом, заработанным на ПРОШЛОЙ неделе — минимум 1.0.
            # Новичков это фактически не трогает: их coefficient уже >= 1.0
            # (см. ladder_groups.assign_novice_coefficients), правило общее.
            coefficient = 1.0
        r.salary = week_base + (bonus075 + bonus2) * coefficient
