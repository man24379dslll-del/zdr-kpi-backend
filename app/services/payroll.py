"""
Двухэтапная ведомость ЗП: "Аванс" = сумма ЗП за недели 1-2 месяца,
"Расчёт" = сумма ЗП за недели 3-5. Точный перенос buildTwoStagePayroll
из старой JS-версии.

kpi_ratings.salary считается в services/salary.py (ставка_за_час ×
"Рабочее время, ч" + бонусы, × коэффициент ЛГ прошлой недели) и
проставляется в routers/ratings.py при расчёте недели. Здесь эти уже
посчитанные salary просто суммируются по этапам — если у кого-то
salary=None (не было колонки "Рабочее время, ч" в файле той недели),
такая неделя для этого человека пропускается (см. ниже), а не считается
за 0.

Каждая строка ответа несёт не только итоговую сумму этапа ("sum"), но и
разбивку по неделям ("weeks": [{period_label, sum}, ...], по возрастанию
номера недели) — ЧИСТО для отображения (см. routers/payroll.py,
static/index.html), саму формулу расчёта не меняет: сумма элементов
"weeks" равна "sum" ДО штрафа/премии этапа (stage_adjustments), которые
применяются одним разом на весь этап, а не к конкретной неделе.

payroll_penalties (штрафы) — уже существующая в Supabase таблица, здесь
не создаётся: id, upload_id, fio, penalty numeric, comment, updated_at,
unique(upload_id, fio). Колонка суммы штрафа называется "penalty" (не
"amount" — уточнено и поправлено в routers/payroll.py). Это ПО-НЕДЕЛЬНЫЙ
штраф, не путать с payroll_stage_adjustments ниже.

payroll_stage_adjustments (см. app/db/schema.sql) — штраф/премия ОДИН РАЗ
на весь этап (месяц, год, ФИО), не по неделям. Применяется ТОЛЬКО к
stage="2" (Расчёт, недели 3-5) — у "Аванса" этих полей нет вообще, даже
если stage_adjustments_by_fio передан, для stage="1" build_two_stage_payroll
его игнорирует. Та же таблица (те же 3 условия) хранит ещё 3 поля —
доплату за часы и оплату за смены, см. ниже.

payment_requisites (должность/реквизиты на человека) — намеренно НЕ
подмешивается: таблицы в Python-версии ещё нет (сказали, что можно
пропустить, отдельная фича).

period_label (например "7-1") не содержит год, поэтому год передаётся
отдельным параметром в format_payroll_period_label — это не бизнес-
правило, а просто недостающий кусок данных, который period_label не
кодирует.

ДОПОЛНИТЕЛЬНЫЕ СЛАГАЕМЫЕ ИТОГА ЭТАПА (поверх существующей формулы —
ничего в ней не меняется, только добавляется), оба ТОЛЬКО для stage="2":

  доплата_за_часы = (work_hours_за_этап + extra_hours − hours_norm) × overtime_rate
    - work_hours_за_этап — сумма work_hours из kpi_ratings по всем неделям
      этапа (то же самое поле, что уже используется для часовой ставки
      в services/salary.py — просто просуммировано по неделям этапа)
    - extra_hours — ручное поле на весь этап (payroll_stage_adjustments,
      как штраф/премия)
    - hours_norm — ТОТ ЖЕ параметр, что и в services/salary.py
      (DEFAULT_HOURS_NORM=160), передаётся вызывающей стороной, не
      дублируется здесь как отдельная константа
    - overtime_rate — настраиваемая ставка доплаты за час (по умолчанию
      150), НЕ per-человек — общий параметр расчёта (как hours_norm),
      не таблица
    - Может быть ОТРИЦАТЕЛЬНОЙ (недоработка часов) — осознанно, не
      защищаем от минуса.

  оплата_за_смены (shift_pay) — ПОЛНОСТЬЮ ВРУЧНУЮ введённая ИТОГОВАЯ
    сумма (ставка за смену разная у разных людей, формулы "кол-во ×
    ставка" внутри системы нет) — ручное поле на весь этап, как штраф/
    премия, прибавляется к итогу как есть. shift_count (кол-во смен) —
    тоже ручное поле, но ТОЛЬКО для справки рядом с суммой, в саму
    формулу итога НЕ входит.
"""
from __future__ import annotations

import calendar
import re

from app.services.group_naming import display_group_name
from app.services.salary import DEFAULT_HOURS_NORM

DEFAULT_OVERTIME_RATE = 150

WEEKS_BY_STAGE = {"1": (1, 2), "2": (3, 4, 5)}
PERIOD_LABEL_RE = re.compile(r"^(\d+)-(\d+)$")

RU_MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _week_number(period_label: str) -> int:
    """"7-1" -> 1. Используется только для сортировки разбивки по неделям
    внутри этапа — не путать с periods.py (сравнение периодов между
    месяцами), тут месяц уже один и тот же (этап всегда внутри 1 месяца)."""
    m = PERIOD_LABEL_RE.match(period_label)
    return int(m.group(2)) if m else 0


def is_weekly_period_label(period_label: str | None) -> bool:
    """period_label вида "месяц-неделя" (например "7-1") — недельный
    период; вида "2026-07-27" (дата) — дневной. Используется и здесь
    (фонд ЗП/формула ЗП только для недельных периодов), и в
    services/dashboards.py."""
    return bool(period_label and PERIOD_LABEL_RE.match(period_label))


def format_payroll_period_label(month: int, stage: str, year: int) -> str:
    """"01-15 Августа 2026" (аванс) / "16-31 Августа 2026" (расчёт)."""
    month_name = RU_MONTHS_GENITIVE[month - 1].capitalize()
    if stage == "1":
        return f"01-15 {month_name} {year}"
    last_day = calendar.monthrange(year, month)[1]
    return f"16-{last_day} {month_name} {year}"


def filter_uploads_for_stage(uploads: list[dict], month: int, stage: str) -> list[dict]:
    """uploads с period_label вида "{месяц}-{неделя}", неделя — в этапе.
    Загрузки с нераспознаваемым period_label (не 'месяц-неделя', например
    дневные вида '2026-07-27') в двухэтапную ведомость не попадают."""
    weeks = WEEKS_BY_STAGE.get(stage)
    if weeks is None:
        raise ValueError(f"stage должен быть '1' (аванс) или '2' (расчёт), получено: {stage!r}")

    matching = []
    for u in uploads:
        m = PERIOD_LABEL_RE.match(u.get("period_label") or "")
        if not m:
            continue
        if int(m.group(1)) == month and int(m.group(2)) in weeks:
            matching.append(u)
    return matching


def build_two_stage_payroll(
    uploads: list[dict],
    ratings_by_upload_id: dict[str, list[dict]],
    penalties_by_upload_id: dict[str, dict[str, float]],
    month: int,
    stage: str,
    year: int,
    stage_adjustments_by_fio: dict[str, dict] | None = None,
    hours_norm: float = DEFAULT_HOURS_NORM,
    overtime_rate: float = DEFAULT_OVERTIME_RATE,
) -> dict:
    """
    uploads: строки kpi_uploads (нужны id и period_label); можно передать
             как есть (уже отфильтрованными filter_uploads_for_stage, или
             нет — тут они переотфильтруются)
    ratings_by_upload_id: upload_id -> сырые строки kpi_ratings этой загрузки
             (нужны salary И work_hours — последний для доплаты за часы)
    penalties_by_upload_id: upload_id -> {fio: сумма штрафа} из payroll_penalties
                             (по-недельный штраф, уже учтён в "sum" ниже)
    stage_adjustments_by_fio: {fio: {"penalty":.., "premium":.., "extra_hours":..,
             "shift_count":.., "shift_pay":..}} из payroll_stage_adjustments —
             по одному разу на весь этап. Применяется ТОЛЬКО когда stage == '2'
             (Расчёт); для stage == '1' (Аванс) полностью игнорируется, даже
             если передан — в rows не появятся эти ключи вовсе.
    hours_norm: та же настройка, что в services/salary.py — импортируется
             оттуда же (DEFAULT_HOURS_NORM), не дублируется тут как
             отдельная константа. Нужна только для доплаты за часы
             (stage == '2'); при stage == '1' не используется.
    overtime_rate: ставка доплаты за час переработки/недоработки (см.
             докстринг модуля) — по умолчанию DEFAULT_OVERTIME_RATE (150).
    """
    matching_uploads = filter_uploads_for_stage(uploads, month, stage)

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
            })
            entry["sum"] += net
            entry["penalty_sum"] += penalty
            entry["supervisor"] = r.get("supervisor")
            entry["status"] = r.get("status")
            entry["weeks"][period_label] = entry["weeks"].get(period_label, 0.0) + net
            entry["work_hours_sum"] += r.get("work_hours") or 0

    rows = list(acc.values())
    for entry in rows:
        # Разбивка по неделям — ТОЛЬКО отображение (см. докстринг функции):
        # список {period_label, sum} по возрастанию номера недели, сумма
        # элементов равна entry["sum"] ДО штрафа/премии этапа ниже (та
        # применяется одним разом на весь этап, не привязана к неделе).
        entry["weeks"] = [
            {"period_label": period_label, "sum": week_sum}
            for period_label, week_sum in sorted(entry["weeks"].items(), key=lambda kv: _week_number(kv[0]))
        ]

        penalty_sum = entry["penalty_sum"]
        penalty_text = int(penalty_sum) if penalty_sum == int(penalty_sum) else penalty_sum
        entry["comment"] = f"Штраф удержан: {penalty_text} ₽" if penalty_sum > 0 else None

        if stage == "2":
            adjustment = (stage_adjustments_by_fio or {}).get(entry["fio"], {})
            penalty = adjustment.get("penalty") or 0
            premium = adjustment.get("premium") or 0
            extra_hours = adjustment.get("extra_hours") or 0
            shift_count = adjustment.get("shift_count") or 0
            shift_pay = adjustment.get("shift_pay") or 0
            overtime_pay = (entry["work_hours_sum"] + extra_hours - hours_norm) * overtime_rate

            entry["penalty"] = penalty
            entry["premium"] = premium
            entry["extra_hours"] = extra_hours
            entry["shift_count"] = shift_count
            entry["shift_pay"] = shift_pay
            entry["overtime_pay"] = overtime_pay
            entry["sum"] = entry["sum"] - penalty + premium + overtime_pay + shift_pay
            # work_hours_sum остаётся в ответе ТОЛЬКО для stage="2" — фронтенду
            # нужен этот компонент, чтобы пересчитывать overtime_pay на лету
            # при редактировании extra_hours, не делая новый запрос к API
            # (см. static/index.html::saveStageAdjustment).
        else:
            del entry["work_hours_sum"]

    rows.sort(key=lambda e: (display_group_name(e["supervisor"]), e["fio"]))

    return {
        "rows": rows,
        "month": month,
        "stage": stage,
        "weeks": list(WEEKS_BY_STAGE[stage]),
        "period_label_text": format_payroll_period_label(month, stage, year),
        "matched_uploads": len(matching_uploads),
    }
