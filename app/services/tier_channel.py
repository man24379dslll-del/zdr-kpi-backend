"""
Тир канала (Радио+ТВ / Интернет) — упрощённый аналог тира ЛК
(tier_lk.py): та же идея, но БЕЗ разделения на подтипы Б/В и без
проверки конверсии — только порог по количеству карточек.

  ch_cards >= 10 — обычный спортивный ранг по ch_per_contact СРЕДИ ТЕХ,
                   У КОГО ТОЖЕ ch_cards >= 10 (больше = лучше)
  ch_cards < 10  — место = (сколько человек с ch_cards >= 10) + среднее
                   МЕСТО (не значение) по остальным 4 категориям недели
                   (c1/ЛК/время/ошибки) — гарантирует, что "мало
                   карточек" всегда хуже, чем "достаточно карточек",
                   независимо от результатов в других категориях.

ВАЖНО про порядок вызова (см. weekly_rating.py): "остальные 4
категории" здесь — это c1_place/lk_place/time_place/errors_place, а у
тира ЛК "остальные 4" — c1_place/ch_place(!)/time_place/errors_place.
Раз каждый использует место ДРУГОГО как один из четырёх входов, тир ЛК
и тир канала не могут оба использовать финальные (уже тированные)
места друг друга — это было бы циклической зависимостью. Разрывается
порядком: сначала считается обычный (нетированный) ранг по каналу
через apply_category_ranks, тир ЛК использует именно это значение,
и только ПОСЛЕ тира ЛК считается тир канала — используя уже готовый
(тированный) lk_place. См. compute_weekly_rating.
"""
from __future__ import annotations

from app.services.rating_engine import rank_standard

OTHER_PLACE_FIELDS = ("c1_place", "lk_place", "time_place", "errors_place")


def compute_tiered_channel_places(items: list[dict]) -> list[float]:
    """
    items: строки за неделю; каждая уже должна содержать посчитанные места
    по остальным 4 категориям (c1_place/lk_place/time_place/errors_place)
    и сырые ch_cards/ch_per_contact.

    Возвращает список мест по категории "канал", в том же порядке, что
    items: у кого >=10 карточек — целые числа 1..|A|; у остальных —
    дробные, гарантированно хуже.
    """
    idx_enough: list[int] = []
    idx_few: list[int] = []
    for i, e in enumerate(items):
        cards = e.get("ch_cards") or 0
        if cards >= 10:
            idx_enough.append(i)
        else:
            idx_few.append(i)

    places: list[float] = [1.0] * len(items)

    def avg_other_places(i: int) -> float:
        e = items[i]
        return sum(e[field] for field in OTHER_PLACE_FIELDS) / 4

    pc_enough = [items[i]["ch_per_contact"] for i in idx_enough]
    for i in idx_enough:
        places[i] = float(rank_standard(pc_enough, items[i]["ch_per_contact"], "desc"))

    for i in idx_few:
        places[i] = len(idx_enough) + avg_other_places(i)

    return places
