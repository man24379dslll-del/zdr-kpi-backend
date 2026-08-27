"""
Гибкая ведомость ЗП: произвольный набор отмеченных недель (periods)
вместо жёсткой привязки "месяц + этап (Аванс/Расчёт)" — выплаты теперь
еженедельные, не привязаны к календарным половинам месяца. Заменяет
прежнюю build_two_stage_payroll/WEEKS_BY_STAGE/filter_uploads_for_stage
(понятие "этап" убрано целиком — везде, где было "stage=='2'", теперь
применяется безусловно, к любому набору отмеченных недель).

kpi_ratings.salary считается в services/salary.py (ставка_за_час ×
"Рабочее время, ч" + бонусы, × коэффициент ЛГ прошлой недели) и
проставляется в routers/ratings.py при расчёте недели. Здесь эти уже
посчитанные salary просто суммируются по отмеченным неделям — если у
кого-то salary=None (не было колонки "Рабочее время, ч" в файле той
недели), такая неделя для этого человека пропускается (см. ниже), а не
считается за 0.

Каждая строка ответа несёт не только итоговую сумму ("sum"), но и
разбивку по неделям ("weeks": [{period_label, sum}, ...], в
хронологическом порядке) — ЧИСТО для отображения (см.
routers/payroll.py, static/index.html), саму формулу расчёта не меняет:
сумма элементов "weeks" равна "sum" ДО ручных корректировок
(penalty/premium/shift_pay), которые применяются одним разом на весь
набор отмеченных недель, а не к конкретной неделе.

payroll_penalties (штрафы) — уже существующая в Supabase таблица, здесь
не создаётся: id, upload_id, fio, penalty numeric, comment, updated_at,
unique(upload_id, fio). Это ПО-НЕДЕЛЬНЫЙ штраф, не путать с
payroll_stage_adjustments ниже.

payroll_stage_adjustments (см. app/db/schema.sql) — штраф/премия/оплата
за смены ОДИН РАЗ на весь набор отмеченных недель, не по неделям. Раньше
ключ был (month, year, fio) и применялся только при stage="2" — теперь
ключ periods_key (fio + отсортированные period_label через запятую,
см. make_periods_key) и применяется ВСЕГДА, для любого набора отмеченных
недель.

payment_requisites (должность/реквизиты на человека) — намеренно НЕ
подмешивается: таблицы в Python-версии ещё нет.

period_label (например "7-1") не содержит год, поэтому год передаётся
отдельным параметром в format_payroll_periods_text — не бизнес-правило,
а просто недостающий кусок данных, который period_label не кодирует.

ДОПОЛНИТЕЛЬНЫЕ СЛАГАЕМЫЕ ИТОГА (поверх суммы недельных salary):

  доплата_за_часы = (Σwork_hours_по_отмеченным_неделям − hours_norm) × overtime_rate
    - work_hours — то же поле, что уже используется для часовой ставки в
      services/salary.py, просто просуммировано по отмеченным неделям.
      Ручного поля "доп. часы" в формуле БОЛЬШЕ НЕТ (убрано целиком) —
      часы только из файла.
    - hours_norm — ТОТ ЖЕ параметр, что и в services/salary.py
      (DEFAULT_HOURS_NORM=160), передаётся вызывающей стороной. НЕ
      масштабируется по количеству отмеченных недель — фиксированное
      число, admin сам отмечает "месяц's worth" недель, когда хочет
      получить осмысленное сравнение (явное решение по итогам
      обсуждения: "без нормы на неделю, важно по итогу месяца часы").
    - overtime_rate — настраиваемая ставка (по умолчанию 150), НЕ
      per-человек — общий параметр расчёта, не таблица.
    - НЕ может быть отрицательной — если часов меньше нормы, доплата
      просто 0 (недоработку по часам людям не ставим в минус; явное
      решение — раньше было наоборот, "осознанно не защищаем от
      минуса", пересмотрено по факту: штраф за недоработку — отдельная
      ручная история через поле "Штраф", не автоматика по часам).

  оплата_за_смены (shift_pay) — ПОЛНОСТЬЮ ВРУЧНУЮ введённая ИТОГОВАЯ
    сумма (ставка за смену разная у разных людей, формулы "кол-во ×
    ставка" внутри системы нет) — ручное поле на весь набор недель,
    прибавляется к итогу как есть.

  shift_count (кол-во смен) — АВТОМАТИЧЕСКОЕ: сумма kpi_ratings.shift_count
    по всем отмеченным неделям (то же поле, что уже парсится из файла) —
    ТОЛЬКО для справки, в формулу итога НЕ входит. Ручное поле shift_count
    в payroll_stage_adjustments (schema.sql) этим модулем больше не
    читается — осталось в БД неиспользуемым/deprecated, как и extra_hours.
"""
from __future__ import annotations

from app.services.group_naming import display_group_name
from app.services.periods import WEEK_LABEL_RE, period_sort_value
from app.services.salary import DEFAULT_HOURS_NORM

DEFAULT_OVERTIME_RATE = 150

RU_MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def is_weekly_period_label(period_label: str | None) -> bool:
    """period_label вида "месяц-неделя" (например "7-1") — недельный
    период; вида "2026-07-27" (дата) — дневной. Используется и здесь
    (гибкая ведомость работает только с недельными периодами), и в
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


def build_flexible_payroll(
    uploads: list[dict],
    ratings_by_upload_id: dict[str, list[dict]],
    penalties_by_upload_id: dict[str, dict[str, float]],
    periods: list[str],
    year: int,
    adjustments_by_fio: dict[str, dict] | None = None,
    hours_norm: float = DEFAULT_HOURS_NORM,
    overtime_rate: float = DEFAULT_OVERTIME_RATE,
) -> dict:
    """
    uploads: строки kpi_uploads (нужны id и period_label); можно передать
             как есть (переотфильтруются filter_uploads_for_periods)
    ratings_by_upload_id: upload_id -> сырые строки kpi_ratings этой
             загрузки (нужны salary, work_hours, shift_count)
    penalties_by_upload_id: upload_id -> {fio: сумма штрафа} из
             payroll_penalties (по-недельный штраф, уже учтён в "sum")
    periods: отмеченные period_label — любое количество, любые месяцы;
             заменяет прежние (month, stage)
    adjustments_by_fio: {fio: {"penalty":.., "premium":.., "shift_pay":..}}
             из payroll_stage_adjustments, ключ (fio, periods_key) —
             применяется ВСЕГДА (см. докстринг модуля)
    hours_norm: тот же параметр, что в services/salary.py — НЕ
             масштабируется по количеству отмеченных недель
    overtime_rate: ставка доплаты за час переработки/недоработки
    """
    periods = sort_periods(periods)
    matching_uploads = filter_uploads_for_periods(uploads, periods)

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
                "fio": fio, "supervisor": None, "status": None, "sum": 0.0, "penalty_sum": 0.0,
                "weeks": {},  # period_label -> сумма ЗП этой недели (net, за вычетом по-недельного штрафа)
                "work_hours_sum": 0.0,
                "shift_count_sum": 0.0,
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
        # Разбивка по неделям — ТОЛЬКО отображение (см. докстринг модуля):
        # список {period_label, sum} в хронологическом порядке, сумма
        # элементов равна entry["sum"] ДО ручных корректировок ниже (те
        # применяются одним разом на весь набор недель).
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
        "periods": periods,
        "periods_key": make_periods_key(periods),
        "period_label_text": format_payroll_periods_text(periods, year),
        "matched_uploads": len(matching_uploads),
    }


# ============================================================
# Возврат к календарной структуре (месяц, недели 1-4) — отменяет
# произвольный выбор недель выше (build_flexible_payroll остаётся пока
# нетронутым, будет убран отдельным коммитом). Неделя 1 сама по себе
# никогда не подаётся в ведомость — только фиксация показателей рейтинга
# (обычный недельный расчёт, без изменений).
# ============================================================

def half_payroll_periods(month: int) -> list[str]:
    """Недели 1-2 месяца — "полу-ведомость" (см. build_half_payroll)."""
    return [f"{month}-1", f"{month}-2"]


def month_close_periods(month: int) -> list[str]:
    """Недели 1-4 месяца — "закрытие месяца" (см. build_month_close_payroll,
    следующий коммит)."""
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
    не участвуют здесь. Для остальных — тот же принцип, что раньше был у
    build_flexible_payroll (штраф/премия/оплата за смены/доплата за
    переработку), периоды теперь всегда ровно [месяц-1, месяц-2]."""
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
