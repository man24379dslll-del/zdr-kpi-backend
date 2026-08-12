"""
ЛГ ("лестничные группы", тиры 1..10) — точный перенос из старой JS-версии
(assignTierCoefficients). Отдельная, следующая ступень поверх ИТОГОВОГО
места в рейтинге за неделю (после всех 5 категорий, включая тир ЛК —
см. tier_lk.py, с которым это НЕ следует путать или сливать).

Внутри каждой группы супервайзера сотрудников (не Н/О) сортируют по
итоговому месту недели и делят на 10 примерно равных частей ("лестница");
первые (n % 10) тиров получают на 1 человека больше остальных. Тиру
присваивается коэффициент — настраивается через /ladder-tiers
(таблица ladder_tier_coefficients в Supabase), TIER_COEFFICIENTS ниже —
только запасной вариант по умолчанию, если таблица пустая/недоступна,
НЕ единственный источник истины. Коэффициент идёт в формулу ЗП
СЛЕДУЮЩЕЙ недели (см. services/salary.py — формула на отработанных
часах, а не на делении фиксированной ставки на кол-во недель):

    ЗП = (ставка_за_час × рабочее_время_ч + бонус075 + бонус2) × коэффициент_ПРОШЛОЙ_недели

(если для человека нет данных за прошлую неделю — коэффициент = 1.0).
"""
from __future__ import annotations

TIER_COEFFICIENTS = [1.4, 1.3, 1.2, 1.1, 1.05, 1, 0.9, 0.75, 0.5, 0.25]


def tier_sizes(n: int) -> list[int]:
    """
    n — сколько человек оценено (не Н/О) в группе супервайзера.
    Первые (n % 10) тиров получают на 1 человека больше остальных.
    """
    base, rem = divmod(n, 10)
    return [base + 1 if i < rem else base for i in range(10)]


def assign_tier_coefficients(rows: list[dict], tier_coefficients: list[float] | None = None) -> None:
    """
    Модифицирует rows на месте: каждой не-Н/О строке проставляет
    row['tier'] (1..10) и row['coefficient'] на основе итогового места
    ЗА ЭТУ НЕДЕЛЮ (row['final_place']), отдельно в рамках каждого
    супервайзера (row['supervisor']).

    rows: строки рейтинга с полями supervisor, is_na, final_place.
    tier_coefficients: 10 чисел по порядку тиров 1..10 (обычно результат
        GET /ladder-tiers). Если не передан — берётся TIER_COEFFICIENTS
        (запасной вариант по умолчанию, не единственный источник истины).
    """
    coefficients = tier_coefficients if tier_coefficients is not None else TIER_COEFFICIENTS

    by_supervisor: dict[str, list[dict]] = {}
    for r in rows:
        by_supervisor.setdefault(r["supervisor"], []).append(r)

    for group in by_supervisor.values():
        evaluated = sorted(
            (r for r in group if not r.get("is_na")),
            key=lambda r: r["final_place"],
        )
        sizes = tier_sizes(len(evaluated))
        idx = 0
        for tier_idx, size in enumerate(sizes):
            for _ in range(size):
                if idx >= len(evaluated):
                    break
                evaluated[idx]["tier"] = tier_idx + 1
                evaluated[idx]["coefficient"] = coefficients[tier_idx]
                idx += 1


NOVICE_MIN_COEFFICIENT = 1.05


def assign_novice_coefficients(rows: list[dict], tier_coefficients: list[float] | None = None) -> None:
    """
    Новички (is_novice=True — статусы "Новичок"/"Новичок, 1..3-й уровень",
    все они же Н/О, final_place=None) НЕ участвуют в официальном месте
    группы, но теперь МОГУТ получить хороший коэффициент ЛГ для ЗП
    следующей недели, если их показатели достаточно сильные — задача
    заказчика, отдельная от assign_tier_coefficients выше.

    Модифицирует rows на месте: каждой строке с is_novice=True проставляет
    row['tier']/row['coefficient'] (справочно, для прозрачности в таблице —
    row['final_place'] эта функция НЕ трогает, новичок остаётся вне
    официального рейтинга).

    Для КАЖДОГО новичка НЕЗАВИСИМО (не все вместе): считаем, каким было бы
    его место, если бы он временно добавился к оценённым (не Н/О)
    сотрудникам ЭТОЙ ЖЕ группы супервайзера — сравнение по total_score
    (row['total_score'], уже посчитан для всех, включая новичков, в
    weekly_rating.py, просто не используется для официального места), по
    тем же правилам, что и обычное место (меньше total_score = лучше,
    tie-break — row['tie_break_value']). Тиры/размеры групп берём через
    tier_sizes(), но применённой к РАЗМЕРУ evaluated+1 (только этот один
    новичок, ВРЕМЕННО, только для его собственного расчёта — реальные
    тиры/коэффициенты оценённых сотрудников, уже расставленные
    assign_tier_coefficients выше, не пересчитываются и не меняются).

    Коэффициент никогда не хуже нейтрального: если получившийся < 1.05 —
    используется 1.0 вместо него (защита новичка, не наказываем плохим
    коэффициентом, только поощряем хорошим).

    Вызывать ПОСЛЕ assign_tier_coefficients (чтобы тиры/коэффициенты
    оценённых сотрудников уже были зафиксированы).

    rows: строки с полями supervisor, is_na, is_novice, total_score,
        tie_break_value (число; 0, если tie-break не задан).
    """
    coefficients = tier_coefficients if tier_coefficients is not None else TIER_COEFFICIENTS

    by_supervisor: dict[str, list[dict]] = {}
    for r in rows:
        by_supervisor.setdefault(r["supervisor"], []).append(r)

    for group in by_supervisor.values():
        evaluated = [r for r in group if not r.get("is_na")]
        novices = [r for r in group if r.get("is_novice")]
        if not novices:
            continue
        sizes = tier_sizes(len(evaluated) + 1)

        for novice in novices:
            place = 1
            for other in evaluated:
                if other["total_score"] < novice["total_score"]:
                    place += 1
                elif (
                    other["total_score"] == novice["total_score"]
                    and other.get("tie_break_value", 0) > novice.get("tie_break_value", 0)
                ):
                    place += 1
            idx = place - 1  # 0-based позиция среди evaluated+novice

            cumulative = 0
            tier_idx = len(sizes) - 1
            for i, size in enumerate(sizes):
                if idx < cumulative + size:
                    tier_idx = i
                    break
                cumulative += size

            coeff = coefficients[tier_idx]
            novice["tier"] = tier_idx + 1
            novice["coefficient"] = coeff if coeff >= NOVICE_MIN_COEFFICIENT else 1.0
