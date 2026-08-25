"""
Полный недельный расчёт: тир канала → категории конструктора рейтинга →
тир ЛК → итоговое место → распределение по ЛГ (лестничным группам).

Соединяет самостоятельные модули в один пайплайн, НЕ сливая их логику
воедино (так и просили при переносе тира ЛК и ЛГ):
  - rating_engine.py  — обобщённое ранжирование категорий конструктора
  - tier_channel.py   — особый случай для категории 'channel' (тир A/Б/В
                         по картам+конверсии канала); считается ПЕРВЫМ,
                         ни от чего не зависит
  - tier_lk.py         — особый случай для категории 'lk' (тир A/Б/В по
                         картам+конверсии ЛК); считается ПОСЛЕ тира
                         канала, использует его финальное место в
                         среднем для тиров Б/В — см. LK_TIER_PLACE_FIELDS
  - ladder_groups.py  — ЛГ, следующая ступень поверх итогового места;
                         новичкам (Н/О) отдельно считается "теоретический"
                         коэффициент ЛГ (assign_novice_coefficients), не
                         влияющий на их final_place и не меняющий тиры
                         оценённых сотрудников

Живёт отдельным модулем (не внутри rating_engine.py), чтобы не создавать
циклический импорт: tier_lk.py уже импортирует rank_standard из
rating_engine.py, поэтому обратный импорт tier_lk.py внутрь
rating_engine.py невозможен.

"Регион УК" (Уволенные/Нераспределенные, employee['is_region_uk'] = True,
см. excel_parsing.py) — особый случай: место по каждой категории
считается как обычно (внутри своей группы, нужно для тира ЛК и для
хранения в kpi_ratings), но в total_score идут только c1/lk/time — канал
и % ошибок для этих сотрудников не в счёт (см. REGION_UK_SCORE_KEYS).

"ПП"/"Увеличители" (supervisor матчит PEAKS_GROUP_RE — обе подгруппы
бывшей общей "Пики") — зеркальный случай: в total_score идёт ТОЛЬКО
channel, остальные 4 категории считаются как обычно (см.
PEAKS_SCORE_KEYS), но не в сумме. Часовая ставка в формуле ЗП для этих
групп тоже отменена — см. services/salary.py, это отдельный, не
связанный с total_score механизм.

ВАЖНО: места по категориям, тир ЛК, тир канала и итоговое место
считаются ВНУТРИ каждой группы супервайзера отдельно, а не по всей
компании сразу — точный перенос старой JS-версии, где scoreSlice
вызывается по одному разу на каждую группу (см. computeMainRating в
static/index.html), а не один раз на весь файл. Сотрудник соревнуется
со своей командой, а не со всеми сотрудниками компании. Раньше здесь
было по-другому (общий пул компании) — это был баг, обнаруженный и
исправленный отдельно от переноса тира канала/сплита Курбановой; см.
tests/test_weekly_rating.py::test_category_places_are_scoped_to_supervisor_group_not_company_wide.
"""
from __future__ import annotations

from app.services.group_naming import PEAKS_GROUP_RE, PEAKS_SCORE_KEYS, REGION_UK_SCORE_KEYS
from app.services.ladder_groups import assign_novice_coefficients, assign_tier_coefficients
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
# настраивается через конструктор рейтинга. "channel" здесь — уже
# ФИНАЛЬНОЕ место по каналу (тир канала считается раньше и ни от чего
# не зависит, см. compute_weekly_rating и docstring tier_channel.py).
LK_TIER_PLACE_FIELDS = {
    "c1": "c1_place",
    "channel": "ch_place",
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
    # Ни 'lk', ни 'channel' не участвуют в обычном apply_category_ranks —
    # у обеих свой особый расчёт (см. ниже).
    other_categories = [c for c in active if c.key not in ("lk", "channel")]

    if lk_category is not None:
        missing = set(LK_TIER_PLACE_FIELDS) - active_keys
        if missing:
            raise ValueError(
                f"Тир ЛК требует категории {sorted(LK_TIER_PLACE_FIELDS)}, "
                f"не хватает: {sorted(missing)}"
            )

    results = [EmployeeScore(fio=row.get(fio_field, ""), raw=row) for row in employees]

    # Группируем по супервайзеру и считаем места/тиры/итоговое место
    # ОТДЕЛЬНО внутри каждой группы (см. докстринг модуля) — Регион
    # УК/Пики распадаются на свои собственные группы естественно, т.к. у
    # них уже разные значения supervisor (см. excel_parsing.py), никакого
    # дополнительного кода тут не нужно.
    groups: dict[object, list[EmployeeScore]] = {}
    for r in results:
        groups.setdefault(r.raw.get(supervisor_field), []).append(r)

    for group_results in groups.values():
        # 1. Тир канала — считается ПЕРВЫМ и полностью самостоятельно: не
        # зависит от мест других категорий вообще, только от собственных
        # ch_cards/ch_conv/ch_per_contact (см. docstring tier_channel.py).
        if channel_category is not None:
            channel_items = []
            for r in group_results:
                channel_items.append({
                    "ch_cards": r.raw.get("ch_cards") or 0,
                    "ch_conv": r.raw.get("ch_conv") or 0,
                    "ch_per_contact": r.raw.get(channel_category.source_column) or 0,
                })
            for r, place in zip(group_results, compute_tiered_channel_places(channel_items)):
                r.places["channel"] = place
                r.scores["channel"] = place * channel_category.weight

        # 2. Обычные категории конструктора (1 обращение, время, % ошибок,
        # любые кастомные) — независимы, обычный спортивный ранг.
        apply_category_ranks(group_results, other_categories)

        # 3. Тир ЛК — ПОСЛЕ канала: среднее для тиров Б/В использует уже
        # ФИНАЛЬНОЕ (не промежуточное) место по каналу из шага 1, циклической
        # зависимости между тиром ЛК и тиром канала больше нет.
        if lk_category is not None:
            lk_items = []
            for r in group_results:
                item = {field: r.places[key] for key, field in LK_TIER_PLACE_FIELDS.items()}
                item["lk_cards"] = r.raw.get("lk_cards") or 0
                item["lk_conv"] = r.raw.get("lk_conv") or 0
                item["lk_pc"] = r.raw.get(lk_category.source_column) or 0
                lk_items.append(item)
            for r, place in zip(group_results, compute_tiered_lk_places(lk_items)):
                r.places["lk"] = place
                r.scores["lk"] = place * lk_category.weight

        # "Регион УК": total_score только по c1/lk/time. "ПП"/"Увеличители":
        # наоборот, total_score только по channel. Места (r.places) в обоих
        # случаях не трогаем — они уже посчитаны внутри группы и нужны тиру
        # ЛК (LK_TIER_PLACE_FIELDS) плюс для хранения в kpi_ratings.
        for r in group_results:
            if r.raw.get("is_region_uk"):
                r.scores = {k: v for k, v in r.scores.items() if k in REGION_UK_SCORE_KEYS}
            elif PEAKS_GROUP_RE.search(r.raw.get(supervisor_field) or ""):
                r.scores = {k: v for k, v in r.scores.items() if k in PEAKS_SCORE_KEYS}

        finalize_final_places(group_results, na_predicate, tie_break_field)

    ladder_rows = [
        {
            "supervisor": r.raw.get(supervisor_field),
            "final_place": r.final_place,
            "is_na": r.is_na,
            "is_novice": bool(r.raw.get("is_novice")),
            "total_score": r.total_score,
            "tie_break_value": (r.raw.get(tie_break_field) or 0) if tie_break_field else 0,
        }
        for r in results
    ]
    assign_tier_coefficients(ladder_rows, tier_coefficients)
    # ПОСЛЕ обычных тиров: новичкам (is_novice, уже Н/О — final_place=None
    # выше) отдельно проставляем "теоретический" коэффициент ЛГ, не трогая
    # тиры/коэффициенты оценённых сотрудников (см. docstring функции).
    assign_novice_coefficients(ladder_rows, tier_coefficients)
    for r, ladder_row in zip(results, ladder_rows):
        if "tier" in ladder_row:
            r.tier = ladder_row["tier"]
            r.coefficient = ladder_row["coefficient"]

    return results
