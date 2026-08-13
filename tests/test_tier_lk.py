from app.services.tier_lk import compute_tiered_lk_places


def _row(lk_cards, lk_conv, lk_pc, c1_place, ch_place, time_place, errors_place):
    return {
        "lk_cards": lk_cards,
        "lk_conv": lk_conv,
        "lk_pc": lk_pc,
        "c1_place": c1_place,
        "ch_place": ch_place,
        "time_place": time_place,
        "errors_place": errors_place,
    }


def test_tier_a_ranked_by_sum_per_contact_desc():
    items = [
        _row(5, 10, 100, 1, 1, 1, 1),  # тир A, лучший lk_pc
        _row(3, 20, 50, 2, 2, 2, 2),   # тир A, хуже lk_pc
    ]
    places = compute_tiered_lk_places(items)
    assert places == [1.0, 2.0]


def test_tier_b_equals_plain_average_without_any_offset():
    # По прямому запросу заказчика: размер тира A НЕ входит в формулу
    # тира Б — просто среднее место по остальным 4 категориям, без сдвига.
    items = [
        _row(5, 10, 100, 1, 1, 1, 1),  # тир A -> место 1
        _row(0, 0, 0, 3, 3, 3, 3),     # тир Б: карточек 0
        _row(5, 0, 0, 2, 2, 2, 2),     # тир Б: 1..9 карточек, конверсия 0
    ]
    places = compute_tiered_lk_places(items)
    assert places[0] == 1.0
    assert places[1] == 3.0  # среднее место (3,3,3,3), БЕЗ +|A|
    assert places[2] == 2.0  # среднее место (2,2,2,2), БЕЗ +|A|


def test_tier_b_can_outrank_tier_a_when_other_categories_are_good():
    # Осознанное следствие отказа от сдвига на размер тира A: при хороших
    # местах по остальным категориям человек без ЛК-карточек (тир Б)
    # может обогнать тех, у кого карточки есть (тир A) — это НЕ баг.
    items = [
        _row(5, 10, 100, 5, 5, 5, 5),  # тир A, но плохие места по остальным категориям
        _row(0, 0, 0, 1, 1, 1, 1),     # тир Б, но отличные места по остальным категориям
    ]
    places = compute_tiered_lk_places(items)
    assert places[0] == 1.0   # тир A: единственный, обычный ранг -> место 1
    assert places[1] == 1.0   # тир Б: среднее (1,1,1,1) = 1, наравне с тиром A
    assert places[1] <= places[0]


def test_tier_c_is_always_worse_than_tier_b_but_not_necessarily_than_tier_a():
    items = [
        _row(5, 10, 100, 1, 1, 1, 1),  # A
        _row(0, 0, 0, 2, 2, 2, 2),     # Б #1
        _row(0, 0, 0, 2, 2, 2, 2),     # Б #2 (тоже среднее 2.0)
        _row(15, 0, 0, 3, 3, 3, 3),    # В: 10+ карточек, конверсия 0, единственный в тире В
    ]
    places = compute_tiered_lk_places(items)
    assert places[0] == 1.0
    assert places[1] == places[2] == 2.0  # тир Б: среднее (2,2,2,2) у обоих, без сдвига
    assert places[3] == 2.0 + 1.0         # тир В: max(Б)=2.0 + ранг 1 (единственный в тире В)
    assert places[3] > places[1]          # В хуже Б


def test_tier_c_worse_than_every_tier_b_person_even_if_one_of_them_has_bad_average():
    """Гарантия, которую ДОЛЖНА давать формула: сдвиг тира В — это
    МАКСИМАЛЬНОЕ (худшее) фактическое место среди людей тира Б, а не
    просто размер |Б| — иначе человек тира В с сильными местами по
    остальным категориям мог обогнать человека тира Б со слабыми
    местами по остальным категориям (найдено на реальных данных:
    Кузнецова К./Сидоров С. в фикстуре test_weekly_rating.py).

    Тут нарочно у Б#2 очень плохое среднее (10.0), а у человека тира В —
    отличные остальные места (1,1,1,1) и минимально возможное число
    карточек, ещё квалифицирующее как тир В (10 — граница тира В/Б).
    Несмотря на это, В должен остаться строго хуже ОБОИХ представителей
    тира Б.
    """
    items = [
        _row(0, 0, 0, 2, 2, 2, 2),      # Б #1: среднее 2.0
        _row(0, 0, 0, 10, 10, 10, 10),  # Б #2: очень плохое среднее 10.0
        _row(10, 0, 0, 1, 1, 1, 1),     # В: 10 карточек (минимум для тира В), отличные остальные места
    ]
    places = compute_tiered_lk_places(items)
    assert places[0] == 2.0
    assert places[1] == 10.0
    assert places[2] == 10.0 + 1.0  # сдвиг = max(2.0, 10.0) = 10.0, + ранг 1
    assert places[2] > places[0]
    assert places[2] > places[1]  # строго хуже ЛЮБОГО из тира Б, не только "среднего"


def test_boundary_ten_cards_switches_b_to_c():
    items = [
        _row(9, 0, 0, 1, 1, 1, 1),   # 9 карточек, конв 0 -> тир Б
        _row(10, 0, 0, 1, 1, 1, 1),  # 10 карточек, конв 0 -> тир В
    ]
    places = compute_tiered_lk_places(items)
    assert places[0] == 1.0  # тир Б: среднее место (1,1,1,1), без сдвига
    assert places[1] == 2.0  # тир В: max(Б)=1.0 + ранг 1 (единственный в тире В)
    assert places[1] > places[0]


def test_tier_c_ranked_by_cards_ascending_more_wasted_cards_is_worse():
    # СТАЛО: место ВНУТРИ тира В ранжируется по количеству карточек ЛК —
    # чем БОЛЬШЕ впустую потрачено карт (конверсия 0%), тем ХУЖЕ место —
    # та же логика, что и у худшего тира канала (см. test_tier_channel.py).
    # Средние места по остальным 4 категориям (c1/ch/time/errors) у всех
    # троих ОДИНАКОВЫЕ (5,5,5,5) — если бы формула ещё была "среднее",
    # все трое делили бы одно место; по новой формуле относительный
    # порядок между ними определяется ИСКЛЮЧИТЕЛЬНО количеством карточек
    # (абсолютный сдвиг задаёт худшее место тира Б).
    items = [
        _row(5, 10, 100, 1, 1, 1, 1),  # тир A -> место 1
        _row(0, 0, 0, 2, 2, 2, 2),     # тир Б -> место 2
        _row(50, 0, 0, 5, 5, 5, 5),    # тир В, 50 карточек -> худший в тире В
        _row(10, 0, 0, 5, 5, 5, 5),    # тир В, 10 карточек -> лучший в тире В
        _row(25, 0, 0, 5, 5, 5, 5),    # тир В, 25 карточек -> средний в тире В
    ]
    places = compute_tiered_lk_places(items)
    assert places[0] == 1.0
    assert places[1] == 2.0
    # max(Б)=2.0 -> тир В начинается с места 3
    assert places[3] == 3.0  # 10 карточек -> лучший в тире В
    assert places[4] == 4.0  # 25 карточек -> средний
    assert places[2] == 5.0  # 50 карточек -> худший
    assert places[3] < places[4] < places[2]
    assert places[3] > places[1]  # весь тир В строго хуже тира Б


def test_tier_c_ties_share_place_with_skip():
    # Равное количество карточек внутри тира В -> одинаковое место,
    # следующее — со сдвигом (обычная логика rank_standard/skip-tie).
    items = [
        _row(0, 0, 0, 1, 1, 1, 1),    # тир Б -> место 1
        _row(10, 0, 0, 9, 9, 9, 9),   # тир В, 10 карточек
        _row(10, 0, 0, 9, 9, 9, 9),   # тир В, тоже 10 -> делит место с предыдущим
        _row(20, 0, 0, 9, 9, 9, 9),   # тир В, 20 карточек -> хуже обоих
    ]
    places = compute_tiered_lk_places(items)
    assert places[0] == 1.0
    # max(Б)=1.0 -> тир В начинается с места 2
    assert places[1] == places[2] == 2.0
    assert places[3] == 4.0  # сдвиг на 2 (кол-во делящих место 2)


def test_empty_tier_b_gives_zero_offset():
    # Если тира Б в группе нет вообще — сдвига брать неоткуда, тир В
    # ранжируется с места 1 (внутри самого тира В).
    items = [
        _row(5, 10, 100, 1, 1, 1, 1),  # тир A -> место 1
        _row(20, 0, 0, 2, 2, 2, 2),    # тир В, 20 карточек
        _row(10, 0, 0, 2, 2, 2, 2),    # тир В, 10 карточек -> лучше
    ]
    places = compute_tiered_lk_places(items)
    assert places[0] == 1.0
    assert places[2] == 1.0  # 10 карточек -> лучший в тире В, сдвиг 0
    assert places[1] == 2.0  # 20 карточек -> хуже


def test_positive_cards_zero_conversion_is_tier_b_not_a():
    items = [_row(5, 0, 999, 1, 1, 1, 1)]  # карточки есть, но конверсия 0
    places = compute_tiered_lk_places(items)
    assert places[0] == 1.0  # тир Б: среднее место (1,1,1,1), не ранг по lk_pc
