"""
Ведомость ЗП — календарная структура (месяц, недели 1-4 фиксированы),
два режима на месяц:

  build_half_payroll — "полу-ведомость" за недели 1-2 (неделя 1 сама по
    себе никогда не подаётся отдельно). Исключает сотрудников с
    "Еженедельная оплата"=Да (payroll_employee_markers.weekly_pay) —
    они получают оплату отдельно, вне этой системы.

  build_month_close_payroll — "закрытие месяца" за недели 1-4. Для
    work_month 1/2 (payroll_employee_markers.work_month) — MAX(гарантия
    по часам [+доплата за обучение на 2-м месяце], сумма по рейтингу за
    4 недели); для work_month 3+ — просто сумма по рейтингу, без
    сравнения. Всегда вычитает уже выплаченную полу-ведомость за недели
    1-2 (0 для "еженедельных" — у них её никогда не было).

История: раньше здесь был build_flexible_payroll (произвольный набор
недель через чекбоксы, без календарной структуры и без гарантий) — убран
целиком по прямому запросу, до него был build_two_stage_payroll
(Аванс/Расчёт) — тоже убран в своё время. sort_periods/make_periods_key/
filter_uploads_for_periods остались от гибкой версии, переиспользуются
обеими текущими функциями (periods теперь всегда канонический набор —
[месяц-1, месяц-2] или [месяц-1..месяц-4], а не произвольный).

kpi_ratings.salary считается в services/salary.py (ставка_за_час ×
"Рабочее время, ч" + бонусы, × коэффициент ЛГ прошлой недели) и
проставляется в routers/ratings.py при расчёте недели. Здесь эти уже
посчитанные salary просто суммируются по неделям — если у кого-то
salary=None (не было колонки "Рабочее время, ч" в файле той недели),
такая неделя для этого человека пропускается, а не считается за 0.

Каждая строка ответа несёт не только итоговую сумму ("sum"), но и
разбивку по неделям ("weeks": [{period_label, sum}, ...], в
хронологическом порядке) — ЧИСТО для отображения (см.
routers/payroll.py, static/index.html), саму формулу расчёта не меняет.

payroll_penalties (штрафы) — уже существующая в Supabase таблица, здесь
не создаётся: id, upload_id, fio, penalty numeric, comment, updated_at,
unique(upload_id, fio). Это ПО-НЕДЕЛЬНЫЙ штраф, не путать с
payroll_stage_adjustments ниже.

payroll_stage_adjustments (см. app/db/schema.sql) — штраф/премия/оплата
за смены один раз на весь набор недель (не по неделям), ключ
periods_key (fio + отсортированные period_label через запятую, см.
make_periods_key) — у полу-ведомости и закрытия месяца РАЗНЫЕ записи
(разные periods_key на один и тот же fio).

payroll_employee_markers (см. app/db/schema.sql) — "Месяц работы"
(work_month, 1/2/3) и "Еженедельная оплата" (weekly_pay) ПО ФИО, не по
периоду — переносятся между периодами автоматически.

payment_requisites (должность/реквизиты на человека) — намеренно НЕ
подмешивается: таблицы в Python-версии ещё нет.

period_label (например "7-1") не содержит год, поэтому год передаётся
отдельным параметром в format_payroll_periods_text — не бизнес-правило,
а просто недостающий кусок данных, который period_label не кодирует.

ДОПОЛНИТЕЛЬНЫЕ СЛАГАЕМЫЕ ИТОГА (поверх суммы недельных salary), общие
для обеих функций:

  доплата_за_часы = (Σwork_hours_за_период − hours_norm) × overtime_rate
    - work_hours — то же поле, что уже используется для часовой ставки в
      services/salary.py, просуммировано по неделям периода. Ручного
      поля "доп. часы" в формуле нет — часы только из файла.
    - hours_norm — ТОТ ЖЕ параметр, что и в services/salary.py
      (DEFAULT_HOURS_NORM=160), передаётся вызывающей стороной.
    - overtime_rate — настраиваемая ставка (по умолчанию 150), НЕ
      per-человек — общий параметр расчёта, не таблица.
    - НЕ может быть отрицательной — если часов меньше нормы, доплата
      просто 0 (недоработку по часам людям не ставим в минус — штраф за
      недоработку — отдельная ручная история через поле "Штраф").

  оплата_за_смены (shift_pay) — ПОЛНОСТЬЮ ВРУЧНУЮ введённая ИТОГОВАЯ
    сумма (ставка за смену разная у разных людей, формулы "кол-во ×
    ставка" внутри системы нет) — ручное поле на весь период,
    прибавляется к итогу как есть.

  shift_count (кол-во смен) — АВТОМАТИЧЕСКОЕ: сумма kpi_ratings.shift_count
    по всем неделям периода (то же поле, что уже парсится из файла) —
    ТОЛЬКО для справки, в формулу итога НЕ входит.
"""
from __future__ import annotations

from app.services.group_naming import display_group_name
from app.services.periods import WEEK_LABEL_RE, period_sort_value
from app.services.salary import DEFAULT_HOURS_NORM

DEFAULT_OVERTIME_RATE = 150
DEFAULT_GUARANTEED_BASE = 40000  # "гарантированная" — 1-й/2-й месяц работы
DEFAULT_MONTH2_TRAINING_BONUS = 5000  # доплата за период обучения, только 2-й месяц

RU_MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def is_weekly_period_label(period_label: str | None) -> bool:
    """period_label вида "месяц-неделя" (например "7-1") — недельный
    период; вида "2026-07-27" (дата) — дневной. Используется и здесь
    (ведомость ЗП работает только с недельными периодами), и в
    services/dashboards.py, routers/ratings.py."""
    return bool(period_label and WEEK_LABEL_RE.match(period_label))


def sort_periods(periods: list[str]) -> list[str]:
    """Хронологическая сортировка period_label ("месяц×10+неделя",
    services/periods.py::period_sort_value) — недели из разных месяцев
    сравниваются корректно, без ограничения "тот же месяц"."""
    return sorted(periods, key=lambda label: period_sort_value("week", label))


def make_periods_key(periods: list[str]) -> str:
    """Ключ для payroll_stage_adjustments (уникальность fio+periods_key,
    см. app/db/schema.sql): отсортированные period_label через запятую,
    например "7-5,8-1,8-2" — не зависит от порядка, в котором фронтенд
    прислал отмеченные недели."""
    return ",".join(sort_periods(periods))


def format_payroll_periods_text(periods: list[str], year: int) -> str:
    """"7-5, 8-1, 8-2 (2026)" — человекочитаемый текст периода начисления
    по отмеченным неделям, в хронологическом порядке."""
    return f"{', '.join(sort_periods(periods))} ({year})"


def filter_uploads_for_periods(uploads: list[dict], periods: list[str]) -> list[dict]:
    """uploads с period_label, входящим в отмеченный набор periods."""
    period_set = set(periods)
    return [u for u in uploads if (u.get("period_label") or "") in period_set]


# ============================================================
# Возврат к календарной структуре (месяц, недели 1-4) — отменяет
# произвольный выбор недель (build_flexible_payroll убран). Неделя 1
# сама по себе никогда не подаётся в ведомость — только фиксация
# показателей рейтинга (обычный недельный расчёт, без изменений).
# ============================================================

def half_payroll_periods(month: int) -> list[str]:
    """Недели 1-2 месяца — "полу-ведомость" (см. build_half_payroll)."""
    return [f"{month}-1", f"{month}-2"]


def month_close_periods(month: int) -> list[str]:
    """Недели 1-4 месяца — "закрытие месяца" (см. build_month_close_payroll)."""
    return [f"{month}-{w}" for w in (1, 2, 3, 4)]


def build_half_payroll(
    uploads: list[dict],
    ratings_by_upload_id: dict[str, list[dict]],
    penalties_by_upload_id: dict[str, dict[str, float]],
    month: int,
    year: int,
    weekly_pay_fios: set[str] | None = None,
    adjustments_by_fio: dict[str, dict] | None = None,
    hours_norm: float = DEFAULT_HOURS_NORM,
    overtime_rate: float = DEFAULT_OVERTIME_RATE,
) -> dict:
    """"Полу-ведомость" за недели 1-2 месяца (см. half_payroll_periods).
    Сотрудники из weekly_pay_fios ("Еженедельная оплата" = Да, см.
    payroll_employee_markers) ПОЛНОСТЬЮ исключены из rows — они получают
    оплату отдельно, вне этой системы; их показатели по-прежнему
    фиксируются обычным недельным расчётом (routers/ratings.py), просто
    не участвуют здесь. Для остальных — штраф/премия/оплата за
    смены/доплата за переработку, периоды всегда ровно [месяц-1, месяц-2]."""
    periods = half_payroll_periods(month)
    matching_uploads = filter_uploads_for_periods(uploads, periods)
    weekly_pay_fios = weekly_pay_fios or set()

    acc: dict[str, dict] = {}
    for upload in matching_uploads:
        upload_id = upload["id"]
        period_label = upload["period_label"]
        penalty_map = penalties_by_upload_id.get(upload_id, {})
        for r in ratings_by_upload_id.get(upload_id, []):
            if r.get("is_novice") or r.get("salary") is None:
                continue
            fio = r["fio"]
            if fio in weekly_pay_fios:
                continue
            penalty = penalty_map.get(fio) or 0
            net = (r.get("salary") or 0) - penalty

            entry = acc.setdefault(fio, {
                "fio": fio, "supervisor": None, "status": None, "sum": 0.0, "penalty_sum": 0.0,
                "weeks": {}, "work_hours_sum": 0.0, "shift_count_sum": 0.0,
            })
            entry["sum"] += net
            entry["penalty_sum"] += penalty
            entry["supervisor"] = r.get("supervisor")
            entry["status"] = r.get("status")
            entry["weeks"][period_label] = entry["weeks"].get(period_label, 0.0) + net
            entry["work_hours_sum"] += r.get("work_hours") or 0
            entry["shift_count_sum"] += r.get("shift_count") or 0

    rows = list(acc.values())
    for entry in rows:
        entry["weeks"] = [
            {"period_label": period_label, "sum": week_sum}
            for period_label, week_sum in sorted(
                entry["weeks"].items(), key=lambda kv: period_sort_value("week", kv[0])
            )
        ]

        penalty_sum = entry["penalty_sum"]
        penalty_text = int(penalty_sum) if penalty_sum == int(penalty_sum) else penalty_sum
        entry["comment"] = f"Штраф удержан: {penalty_text} ₽" if penalty_sum > 0 else None

        adjustment = (adjustments_by_fio or {}).get(entry["fio"], {})
        penalty = adjustment.get("penalty") or 0
        premium = adjustment.get("premium") or 0
        shift_pay = adjustment.get("shift_pay") or 0
        overtime_pay = max(0.0, (entry["work_hours_sum"] - hours_norm) * overtime_rate)

        entry["penalty"] = penalty
        entry["premium"] = premium
        entry["shift_pay"] = shift_pay
        entry["shift_count"] = entry.pop("shift_count_sum")
        entry["overtime_pay"] = overtime_pay
        entry["sum"] = entry["sum"] - penalty + premium + overtime_pay + shift_pay

    rows.sort(key=lambda e: (display_group_name(e["supervisor"]), e["fio"]))

    return {
        "rows": rows,
        "month": month,
        "year": year,
        "periods": periods,
        "periods_key": make_periods_key(periods),
        "period_label_text": format_payroll_periods_text(periods, year),
        "matched_uploads": len(matching_uploads),
    }


def build_month_close_payroll(
    uploads: list[dict],
    ratings_by_upload_id: dict[str, list[dict]],
    penalties_by_upload_id: dict[str, dict[str, float]],
    month: int,
    year: int,
    markers_by_fio: dict[str, dict] | None = None,
    adjustments_by_fio: dict[str, dict] | None = None,
    half_sum_by_fio: dict[str, float] | None = None,
    hours_norm: float = DEFAULT_HOURS_NORM,
    overtime_rate: float = DEFAULT_OVERTIME_RATE,
    guaranteed_base: float = DEFAULT_GUARANTEED_BASE,
    month2_bonus: float = DEFAULT_MONTH2_TRAINING_BONUS,
) -> dict:
    """"Закрытие месяца" — недели 1-4 (см. month_close_periods). Для КАЖДОГО
    сотрудника (включая weekly_pay=true, см. ниже) считается:

      work_month 1 или 2 (payroll_employee_markers.work_month):
        guaranteed_pay = guaranteed_base × (work_hours_за_4нед / hours_norm)
                          [+ month2_bonus, если work_month == 2]
        base = MAX(guaranteed_pay, rating_sum)  — rating_sum = обычная
               сумма по системе рейтинга (ставка+бонусы×коэфф.) за 4 недели

      work_month 3+ (или нет маркера — по умолчанию work_month=1, см.
      payroll_employee_markers.work_month default):
        base = rating_sum, БЕЗ сравнения с гарантией

    Дальше ВСЕГДА, независимо от work_month:
      sum = base − штраф(adjustment) + премия(adjustment)
                 + доплата за переработку (за все 4 недели)
                 + оплата за смены(adjustment)
                 − half_sum_by_fio[fio] (уже выплаченная полу-ведомость за
                   недели 1-2 — 0 для weekly_pay=true: у них полу-ведомости
                   никогда не было, см. build_half_payroll, осознанный
                   компромисс — их месячный расчёт от этого занижен, они
                   получают оплату отдельно, вне этой системы)

    Штраф/премия/оплата за смены здесь — ОТДЕЛЬНАЯ запись
    payroll_stage_adjustments от той, что у полу-ведомости (свой
    periods_key на весь месяц, см. month_close_periods)."""
    periods = month_close_periods(month)
    matching_uploads = filter_uploads_for_periods(uploads, periods)
    markers_by_fio = markers_by_fio or {}
    half_sum_by_fio = half_sum_by_fio or {}

    acc: dict[str, dict] = {}
    for upload in matching_uploads:
        upload_id = upload["id"]
        period_label = upload["period_label"]
        penalty_map = penalties_by_upload_id.get(upload_id, {})
        for r in ratings_by_upload_id.get(upload_id, []):
            if r.get("is_novice") or r.get("salary") is None:
                continue
            fio = r["fio"]
            penalty = penalty_map.get(fio) or 0
            net = (r.get("salary") or 0) - penalty

            entry = acc.setdefault(fio, {
                "fio": fio, "supervisor": None, "status": None, "rating_sum": 0.0, "penalty_sum": 0.0,
                "weeks": {}, "work_hours_sum": 0.0, "shift_count_sum": 0.0,
            })
            entry["rating_sum"] += net
            entry["penalty_sum"] += penalty
            entry["supervisor"] = r.get("supervisor")
            entry["status"] = r.get("status")
            entry["weeks"][period_label] = entry["weeks"].get(period_label, 0.0) + net
            entry["work_hours_sum"] += r.get("work_hours") or 0
            entry["shift_count_sum"] += r.get("shift_count") or 0

    rows = list(acc.values())
    for entry in rows:
        entry["weeks"] = [
            {"period_label": period_label, "sum": week_sum}
            for period_label, week_sum in sorted(
                entry["weeks"].items(), key=lambda kv: period_sort_value("week", kv[0])
            )
        ]

        penalty_sum = entry["penalty_sum"]
        penalty_text = int(penalty_sum) if penalty_sum == int(penalty_sum) else penalty_sum
        entry["comment"] = f"Штраф удержан: {penalty_text} ₽" if penalty_sum > 0 else None

        fio = entry["fio"]
        marker = markers_by_fio.get(fio) or {}
        work_month = marker.get("work_month") or 1
        weekly_pay = bool(marker.get("weekly_pay"))

        rating_sum = entry["rating_sum"]
        if work_month in (1, 2):
            guaranteed_pay = guaranteed_base * (entry["work_hours_sum"] / hours_norm) if hours_norm else 0.0
            if work_month == 2:
                guaranteed_pay += month2_bonus
            base = max(guaranteed_pay, rating_sum)
        else:
            guaranteed_pay = None
            base = rating_sum

        adjustment = (adjustments_by_fio or {}).get(fio, {})
        penalty = adjustment.get("penalty") or 0
        premium = adjustment.get("premium") or 0
        shift_pay = adjustment.get("shift_pay") or 0
        overtime_pay = max(0.0, (entry["work_hours_sum"] - hours_norm) * overtime_rate)
        half_deduction = 0.0 if weekly_pay else (half_sum_by_fio.get(fio) or 0.0)

        entry["work_month"] = work_month
        entry["weekly_pay"] = weekly_pay
        entry["guaranteed_pay"] = guaranteed_pay
        entry["rating_sum"] = rating_sum
        entry["base"] = base
        entry["penalty"] = penalty
        entry["premium"] = premium
        entry["shift_pay"] = shift_pay
        entry["shift_count"] = entry.pop("shift_count_sum")
        entry["overtime_pay"] = overtime_pay
        entry["half_deduction"] = half_deduction
        entry["sum"] = base - penalty + premium + overtime_pay + shift_pay - half_deduction

    rows.sort(key=lambda e: (display_group_name(e["supervisor"]), e["fio"]))

    return {
        "rows": rows,
        "month": month,
        "year": year,
        "periods": periods,
        "periods_key": make_periods_key(periods),
        "period_label_text": format_payroll_periods_text(periods, year),
        "matched_uploads": len(matching_uploads),
    }
