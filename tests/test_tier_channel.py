from app.services.tier_channel import compute_tiered_channel_places


def _row(ch_cards, ch_per_contact, c1_place, lk_place, time_place, errors_place):
    return {
        "ch_cards": ch_cards,
        "ch_per_contact": ch_per_contact,
        "c1_place": c1_place,
        "lk_place": lk_place,
        "time_place": time_place,
        "errors_place": errors_place,
    }


def test_enough_cards_ranked_by_per_contact_desc():
    items = [
        _row(10, 100, 1, 1, 1, 1),  # >=10 карточек, лучший ch_per_contact
        _row(15, 50, 2, 2, 2, 2),   # >=10 карточек, хуже ch_per_contact
    ]
    places = compute_tiered_channel_places(items)
    assert places == [1.0, 2.0]


def test_few_cards_always_worse_than_enough_cards():
    items = [
        _row(10, 100, 1, 1, 1, 1),  # >=10 карточек -> место 1
        _row(0, 0, 3, 3, 3, 3),     # <10 карточек (0)
        _row(5, 0, 2, 2, 2, 2),     # <10 карточек (5)
    ]
    places = compute_tiered_channel_places(items)
    assert places[0] == 1.0
    assert places[1] == 1 + 3.0  # |enough| + среднее место (3,3,3,3)
    assert places[2] == 1 + 2.0  # |enough| + среднее место (2,2,2,2)
    assert places[1] > places[0]
    assert places[2] > places[0]


def test_boundary_ten_cards_counts_as_enough():
    items = [
        _row(9, 999, 1, 1, 1, 1),   # 9 карточек -> "мало", несмотря на большой ch_per_contact
        _row(10, 1, 1, 1, 1, 1),    # 10 карточек -> "достаточно"
    ]
    places = compute_tiered_channel_places(items)
    assert places[1] == 1.0  # единственный "достаточно" -> место 1
    assert places[0] == 1 + 1.0  # |enough|=1 + среднее место (1,1,1,1)
    assert places[0] > places[1]


def test_no_tier_c_variant_exists_only_two_cases():
    # В отличие от тира ЛК тут нет отдельной проверки конверсии/третьего
    # варианта — все, у кого <10 карточек, попадают в один и тот же расчёт.
    items = [
        _row(10, 100, 1, 1, 1, 1),
        _row(0, 0, 2, 2, 2, 2),
        _row(9, 0, 2, 2, 2, 2),
    ]
    places = compute_tiered_channel_places(items)
    # оба "мало карточек" сотрудника с одинаковыми местами по остальным
    # категориям получают ОДИНАКОВОЕ дробное место — нет расщепления на подтипы
    assert places[1] == places[2]
