from app.services.tier_channel import compute_tiered_channel_places


def _row(ch_cards, ch_conv, ch_per_contact, c1_place, lk_place, time_place, errors_place):
    return {
        "ch_cards": ch_cards,
        "ch_conv": ch_conv,
        "ch_per_contact": ch_per_contact,
        "c1_place": c1_place,
        "lk_place": lk_place,
        "time_place": time_place,
        "errors_place": errors_place,
    }


def test_tier_a_ranked_by_per_contact_desc():
    items = [
        _row(1, 10, 100, 1, 1, 1, 1),   # карточек>=1 и конверсия>0, лучший ch_per_contact
        _row(15, 5, 50, 2, 2, 2, 2),    # карточек>=1 и конверсия>0, хуже ch_per_contact
    ]
    places = compute_tiered_channel_places(items)
    assert places == [1.0, 2.0]


def test_no_deal_always_worse_than_having_a_deal():
    items = [
        _row(1, 10, 100, 1, 1, 1, 1),  # есть сделка -> место 1
        _row(0, 0, 0, 3, 3, 3, 3),     # 0 карточек
        _row(5, 0, 0, 2, 2, 2, 2),     # карточки есть, но конверсия 0%
    ]
    places = compute_tiered_channel_places(items)
    assert places[0] == 1.0
    assert places[1] == 1 + 3.0  # |тир A| + среднее место (3,3,3,3)
    assert places[2] == 1 + 2.0  # |тир A| + среднее место (2,2,2,2)
    assert places[1] > places[0]
    assert places[2] > places[0]


def test_boundary_zero_cards_vs_one_card_with_conversion():
    # Порог тот же, что у тира ЛК: карточек>=1 И конверсия>0 — а не
    # конкретное число карточек (раньше было ">=10", это устарело).
    items = [
        _row(0, 50, 999, 1, 1, 1, 1),  # 0 карточек, но задана (нереалистичная) конверсия -> "нет сделки" всё равно
        _row(1, 1, 1, 1, 1, 1, 1),     # 1 карточка И конверсия>0 -> "тир A"
    ]
    places = compute_tiered_channel_places(items)
    assert places[1] == 1.0  # единственный в тире A -> место 1
    assert places[0] == 1 + 1.0  # |тир A|=1 + среднее место (1,1,1,1)
    assert places[0] > places[1]


def test_cards_without_conversion_does_not_count_as_tier_a():
    # Как и у тира ЛК: карточки есть, но конверсия 0% — это НЕ тир A,
    # несмотря на сколь угодно большое число карточек.
    items = [
        _row(1, 1, 1, 1, 1, 1, 1),      # 1 карточка, конверсия>0 -> тир A
        _row(999, 0, 999, 2, 2, 2, 2),  # 999 карточек, конверсия 0% -> НЕ тир A
    ]
    places = compute_tiered_channel_places(items)
    assert places[0] == 1.0
    assert places[1] == 1 + 2.0  # |тир A|=1 + среднее место (2,2,2,2)


def test_no_tier_c_variant_exists_only_two_cases():
    # В отличие от тира ЛК тут нет отдельной проверки "10+ карточек при
    # конверсии 0%" (тир В) — все, кто не попал в тир A, попадают в один
    # и тот же расчёт среднего, без расщепления на подтипы.
    items = [
        _row(1, 10, 100, 1, 1, 1, 1),
        _row(0, 0, 0, 2, 2, 2, 2),
        _row(9, 0, 0, 2, 2, 2, 2),
    ]
    places = compute_tiered_channel_places(items)
    # оба "не тир A" сотрудника с одинаковыми местами по остальным
    # категориям получают ОДИНАКОВОЕ дробное место — нет расщепления на подтипы
    assert places[1] == places[2]
