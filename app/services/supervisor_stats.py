"""
Показатели групп ОДНОГО сектора для "Рейтинга супервайзеров сектора" в
рабочем окне обычного супервайзера (GET /ratings/sector-supervisor-stats).

У обычного супервайзера RLS оставляет в kpi_ratings только его группу, а
рейтинг между супервайзерами нужен по всему сектору. Чтобы не отдавать ему
строки чужих сотрудников, бэкенд отдаёт только АГРЕГАТЫ по группам (средние
и суммы по оценённым людям) — без ФИО и без денег (ни ЗП, ни бонусов, ни ЛГ).
Места, баллы и коэффициент считает фронтенд тем же кодом, что у
руководителей секторов (rankSupervisorStats в static/index.html), по весам
периода — поэтому у супервайзера и у руководителя сектора цифры совпадают.

Агрегаты — точный перенос фронтовой computeSupervisorRatingFromRows:
  * сектор 2/3 — оценённый = не тренер/руководитель/отпуск/больничный и
    c1_sum != 0 (новички считаются; isNarrowSectorEvaluated);
  * сектор 1 — оценённый = не Н/О (is_na);
  * нет оценённых — группы в списке нет;
  * суммы (c1_sum/_cards, lk_*, ch_*) и средние (check/conv/pc, время,
    % ошибок) — по оценённым, None считается нулём;
  * n_total — все основные строки группы (без дублей новичков).
В сектор 1 входят все обычные группы, не вошедшие в 2 и 3; Регион УК/ПП/
Увеличители/Васько в сравнение групп не входят.
"""
from __future__ import annotations

from app.services.dashboards import _is_excluded_from_levels
from app.services.sector_weights import sector_of_supervisor

# Статусы, при которых сотрудник Секторов 2/3 не оценивается (JS:
# NARROW_SECTOR_NON_NOVICE_EXCLUDED_STATUSES). Статус "Новичок" сюда НЕ
# входит — в этих секторах новички оцениваются.
NARROW_SECTOR_EXCLUDED_STATUSES = {"Тренер", "руководитель", "Отпуск", "Больничный"}

# Только эти колонки читаются из kpi_ratings: ни fio, ни денег.
STATS_COLUMNS = (
    "supervisor,is_novice,is_na,status,channel,"
    "c1_sum,c1_check,c1_conv,c1_per_contact,c1_cards,"
    "lk_sum,lk_check,lk_conv,lk_per_contact,lk_cards,"
    "ch_sum,ch_check,ch_conv,ch_per_contact,ch_cards,"
    "time_per_contact,errors_pct"
)


def _is_evaluated(row: dict, sector: int) -> bool:
    if sector in (2, 3):
        return row.get("status") not in NARROW_SECTOR_EXCLUDED_STATUSES and row.get("c1_sum") != 0
    return not row.get("is_na")


def sector_group_stats(rows: list[dict], sector: int) -> list[dict]:
    """rows — строки kpi_ratings одного периода (любые колонки из STATS_COLUMNS).
    Возвращает агрегаты по группам сектора в тех полях, что ждёт фронтенд."""
    by_group: dict[str, list[dict]] = {}
    for r in rows:
        supervisor = r.get("supervisor")
        if r.get("is_novice") or not supervisor:
            continue  # дубли новичков для общего списка — не сотрудники группы
        if sector_of_supervisor(supervisor) != sector or _is_excluded_from_levels(supervisor):
            continue
        by_group.setdefault(supervisor, []).append(r)

    stats = []
    for supervisor, group_rows in by_group.items():
        evaluated = [r for r in group_rows if _is_evaluated(r, sector)]
        n = len(evaluated)
        if not n:
            continue

        def total(field: str) -> float:
            return sum((r.get(field) or 0) for r in evaluated)

        def mean(field: str) -> float:
            return total(field) / n

        stats.append({
            "supervisor": supervisor,
            "channel": evaluated[0].get("channel") or "radio",
            "n_evaluated": n,
            "n_total": len(group_rows),
            "c1_sum": total("c1_sum"), "c1_check": mean("c1_check"), "c1_conv": mean("c1_conv"),
            "c1_pc": mean("c1_per_contact"), "c1_cards": total("c1_cards"),
            "lk_sum": total("lk_sum"), "lk_check": mean("lk_check"), "lk_conv": mean("lk_conv"),
            "lk_pc": mean("lk_per_contact"), "lk_cards": total("lk_cards"),
            "ch_sum": total("ch_sum"), "ch_check": mean("ch_check"), "ch_conv": mean("ch_conv"),
            "ch_pc": mean("ch_per_contact"), "ch_cards": total("ch_cards"),
            "time": mean("time_per_contact"), "errors_pct": mean("errors_pct"),
        })
    return stats
