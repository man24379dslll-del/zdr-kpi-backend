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
        _row(0, 0, 0, 2, 2, 2, 2),     # Б
        _row(15, 0, 0, 3, 3, 3, 3),    # В: 10+ карточек, конверсия 0
    ]
    places = compute_tiered_lk_places(items)
    assert places[0] == 1.0
    assert places[1] == 2.0        # тир Б: среднее (2,2,2,2), без сдвига
    assert places[2] == 1 + 3.0    # тир В: |Б|=1 + среднее (3,3,3,3)
    assert places[2] > places[1]   # В гарантированно хуже Б


def test_boundary_ten_cards_switches_b_to_c():
    items = [
        _row(9, 0, 0, 1, 1, 1, 1),   # 9 карточек, конв 0 -> тир Б
        _row(10, 0, 0, 1, 1, 1, 1),  # 10 карточек, конв 0 -> тир В
    ]
    places = compute_tiered_lk_places(items)
    assert places[0] == 1.0  # тир Б: среднее место (1,1,1,1), без сдвига
    assert places[1] == 2.0  # тир В: |Б|=1 + среднее место (1,1,1,1)
    assert places[1] > places[0]


def test_positive_cards_zero_conversion_is_tier_b_not_a():
    items = [_row(5, 0, 999, 1, 1, 1, 1)]  # карточки есть, но конверсия 0
    places = compute_tiered_lk_places(items)
    assert places[0] == 1.0  # тир Б: среднее место (1,1,1,1), не ранг по lk_pc
