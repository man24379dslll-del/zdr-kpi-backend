"""
Полный недельный расчёт: категории конструктора рейтинга → тир ЛК →
итоговое место → распределение по ЛГ (лестничным группам).

Соединяет три самостоятельных модуля в один пайплайн, НЕ сливая их
логику воедино (так и просили при переносе тира ЛК и ЛГ):
  - rating_engine.py — обобщённое ранжирование категорий конструктора
  - tier_lk.py        — особый случай для категории 'lk' (тир A/Б/В)
  - ladder_groups.py  — ЛГ, следующая ступень поверх итогового места

Живёт отдельным модулем (не внутри rating_engine.py), чтобы не создавать
циклический импорт: tier_lk.py уже импортирует rank_standard из
rating_engine.py, поэтому обратный импорт tier_lk.py внутрь
rating_engine.py невозможен.

"Регион УК" (employee['is_region_uk'] = True, см. excel_parsing.py) —
особый случай: место по каждой категории считается как обычно (общий
пул компании, нужно для тира ЛК и для хранения в kpi_ratings), но в
total_score идут только c1/lk/time — канал и % ошибок для этих
сотрудников не в счёт (см. REGION_UK_SCORE_KEYS).
"""
from __future__ import annotations

from app.services.group_naming import REGION_UK_SCORE_KEYS
from app.services.ladder_groups import assign_tier_coefficients
from app.services.rating_engine import (
    EmployeeScore,
    RatingCategory,
    apply_category_ranks,
    finalize_final_places,
)
from app.services.tier_channel import compute_tiered_channel_places
from app.services.tier_lk import compute_tiered_lk_places

# Тир ЛК (в отличие от остальных категорий конструктора) жёстко завязан
# на эти 4 конкретные категории — как в старой JS-версии. Это не
# настраивается через конструктор рейтинга.
LK_TIER_PLACE_FIELDS = {
    "c1": "c1_place",
    "channel": "ch_place",
    "time": "time_place",
    "errors": "errors_place",
}

# Тир канала — аналогично, но использует уже ТИРИРОВАННОЕ место по ЛК
# (считается ПОСЛЕ тира ЛК, см. compute_weekly_rating и docstring
# tier_channel.py — иначе тир ЛК и тир канала зависели бы друг от друга
# циклически).
CHANNEL_TIER_PLACE_FIELDS = {
    "c1": "c1_place",
    "lk": "lk_place",
    "time": "time_place",
    "errors": "errors_place",
}


def compute_weekly_rating(
    employees: list[dict],
    categories: list[RatingCategory],
    fio_field: str = "fio",
    supervisor_field: str = "supervisor",
    na_predicate=None,
    tie_break_field: str | None = None,
    tier_coefficients: list[float] | None = None,
) -> list[EmployeeScore]:
    """
    employees: сырые строки за неделю (см. routers/ratings.py:parse_weekly_rating_excel),
               включая lk_cards/lk_conv и source_column категории 'lk' (= lk_pc)
    categories: активные категории конструктора рейтинга (rating_categories).
                Если среди них есть 'lk', должны быть и все 4 категории из
                LK_TIER_PLACE_FIELDS — иначе тир ЛК посчитать нечем.
    supervisor_field: поле в employees с именем супервайзера (для ЛГ)
    na_predicate/tie_break_field: см. rating_engine.finalize_final_places
    tier_coefficients: см. ladder_groups.assign_tier_coefficients — 10 чисел
                по тирам 1..10, обычно результат GET /ladder-tiers. Не
                передан — ladder_groups сам подставит запасной вариант.
    """
    active = [c for c in categories if c.enabled]
    active_keys = {c.key for c in active}
    lk_category = next((c for c in active if c.key == "lk"), None)
    channel_category = next((c for c in active if c.key == "channel"), None)
    other_categories = [c for c in active if c.key != "lk"]

    if lk_category is not None:
        missing = set(LK_TIER_PLACE_FIELDS) - {c.key for c in other_categories}
        if missing:
            raise ValueError(
                f"Тир ЛК требует категории {sorted(LK_TIER_PLACE_FIELDS)}, "
                f"не хватает: {sorted(missing)}"
            )

    if channel_category is not None:
        missing = set(CHANNEL_TIER_PLACE_FIELDS) - active_keys
        if missing:
            raise ValueError(
                f"Тир канала требует категории {sorted(CHANNEL_TIER_PLACE_FIELDS)}, "
                f"не хватает: {sorted(missing)}"
            )

    results = [EmployeeScore(fio=row.get(fio_field, ""), raw=row) for row in employees]

    apply_category_ranks(results, other_categories)

    if lk_category is not None:
        lk_items = []
        for r in results:
            item = {field: r.places[key] for key, field in LK_TIER_PLACE_FIELDS.items()}
            item["lk_cards"] = r.raw.get("lk_cards") or 0
            item["lk_conv"] = r.raw.get("lk_conv") or 0
            item["lk_pc"] = r.raw.get(lk_category.source_column) or 0
            lk_items.append(item)
        for r, place in zip(results, compute_tiered_lk_places(lk_items)):
            r.places["lk"] = place
            r.scores["lk"] = place * lk_category.weight

    # Тир канала — обязательно ПОСЛЕ тира ЛК: читает уже тированное
    # r.places["lk"] (см. CHANNEL_TIER_PLACE_FIELDS и docstring
    # tier_channel.py про разрыв циклической зависимости).
    if channel_category is not None:
        channel_items = []
        for r in results:
            item = {field: r.places[key] for key, field in CHANNEL_TIER_PLACE_FIELDS.items()}
            item["ch_cards"] = r.raw.get("ch_cards") or 0
            item["ch_per_contact"] = r.raw.get(channel_category.source_column) or 0
            channel_items.append(item)
        for r, place in zip(results, compute_tiered_channel_places(channel_items)):
            r.places["channel"] = place
            r.scores["channel"] = place * channel_category.weight

    # "Регион УК": total_score только по c1/lk/time. Места (r.places)
    # не трогаем — они уже посчитаны по общему пулу компании и нужны
    # тиру ЛК (LK_TIER_PLACE_FIELDS) плюс для хранения в kpi_ratings.
    for r in results:
        if r.raw.get("is_region_uk"):
            r.scores = {k: v for k, v in r.scores.items() if k in REGION_UK_SCORE_KEYS}

    finalize_final_places(results, na_predicate, tie_break_field)

    ladder_rows = [
        {
            "supervisor": r.raw.get(supervisor_field),
            "final_place": r.final_place,
            "is_na": r.is_na,
        }
        for r in results
    ]
    assign_tier_coefficients(ladder_rows, tier_coefficients)
    for r, ladder_row in zip(results, ladder_rows):
        if "tier" in ladder_row:
            r.tier = ladder_row["tier"]
            r.coefficient = ladder_row["coefficient"]

    return results
