"""
Двухэтапная ведомость ЗП: "Аванс" = сумма ЗП за недели 1-2 месяца,
"Расчёт" = сумма ЗП за недели 3-5. Точный перенос buildTwoStagePayroll
из старой JS-версии.

ВАЖНО: kpi_ratings.salary сейчас всегда null — формула ЗП ещё не
перенесена (отдельный, следующий шаг, см. README, п.7). Эта агрегация
уже готова к работе, но реально будет возвращать пустые/нулевые суммы,
пока salary не считается где-то выше по пайплайну.

payroll_penalties (штрафы) — уже существующая в Supabase таблица, здесь
не создаётся: id, upload_id, fio, penalty numeric, comment, updated_at,
unique(upload_id, fio). Колонка суммы штрафа называется "penalty" (не
"amount" — уточнено и поправлено в routers/payroll.py).

payment_requisites (должность/реквизиты на человека) — намеренно НЕ
подмешивается: таблицы в Python-версии ещё нет (сказали, что можно
пропустить, отдельная фича).

period_label (например "7-1") не содержит год, поэтому год передаётся
отдельным параметром в format_payroll_period_label — это не бизнес-
правило, а просто недостающий кусок данных, который period_label не
кодирует.
"""
from __future__ import annotations

import calendar
import re

from app.services.group_naming import display_group_name

WEEKS_BY_STAGE = {"1": (1, 2), "2": (3, 4, 5)}
PERIOD_LABEL_RE = re.compile(r"^(\d+)-(\d+)$")

RU_MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


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
) -> dict:
    """
    uploads: строки kpi_uploads (нужны id и period_label); можно передать
             как есть (уже отфильтрованными filter_uploads_for_stage, или
             нет — тут они переотфильтруются)
    ratings_by_upload_id: upload_id -> сырые строки kpi_ratings этой загрузки
    penalties_by_upload_id: upload_id -> {fio: сумма штрафа} из payroll_penalties
    """
    matching_uploads = filter_uploads_for_stage(uploads, month, stage)

    acc: dict[str, dict] = {}
    for upload in matching_uploads:
        upload_id = upload["id"]
        penalty_map = penalties_by_upload_id.get(upload_id, {})
        for r in ratings_by_upload_id.get(upload_id, []):
            if r.get("is_novice") or r.get("salary") is None:
                continue
            fio = r["fio"]
            penalty = penalty_map.get(fio) or 0
            net = (r.get("salary") or 0) - penalty

            entry = acc.setdefault(fio, {
                "fio": fio, "supervisor": None, "status": None, "sum": 0.0, "penalty_sum": 0.0,
            })
            entry["sum"] += net
            entry["penalty_sum"] += penalty
            entry["supervisor"] = r.get("supervisor")
            entry["status"] = r.get("status")

    rows = list(acc.values())
    for entry in rows:
        penalty_sum = entry["penalty_sum"]
        penalty_text = int(penalty_sum) if penalty_sum == int(penalty_sum) else penalty_sum
        entry["comment"] = f"Штраф удержан: {penalty_text} ₽" if penalty_sum > 0 else None
    rows.sort(key=lambda e: (display_group_name(e["supervisor"]), e["fio"]))

    return {
        "rows": rows,
        "month": month,
        "stage": stage,
        "weeks": list(WEEKS_BY_STAGE[stage]),
        "period_label_text": format_payroll_period_label(month, stage, year),
    }
