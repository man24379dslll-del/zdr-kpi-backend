from app.services.tier_channel import compute_tiered_channel_places


def _row(ch_cards, ch_conv, ch_per_contact):
    return {
        "ch_cards": ch_cards,
        "ch_conv": ch_conv,
        "ch_per_contact": ch_per_contact,
    }


def test_tier_a_ranked_by_per_contact_desc():
    items = [
        _row(1, 10, 100),  # карточек>=1 и конверсия>0, лучший ch_per_contact
        _row(15, 5, 50),   # карточек>=1 и конверсия>0, хуже ch_per_contact
    ]
    places = compute_tiered_channel_places(items)
    assert places == [1.0, 2.0]


def test_tier_a_ties_share_the_same_place():
    # Одинаковые суммы с контакта внутри тира A -> одинаковое место
    # (обычный спортивный ранг, как везде в проекте) — это норма.
    items = [
        _row(5, 10, 100),
        _row(3, 20, 100),
        _row(1, 5, 50),
    ]
    places = compute_tiered_channel_places(items)
    assert places[0] == places[1] == 1.0
    assert places[2] == 3.0  # следующее место сдвинуто на кол-во делящих (2), не на 1


def test_tier_b_all_share_one_place_right_after_tier_a():
    # Тир Б (карточек 0) — НЕ среднее по категориям (в отличие от тира ЛК),
    # а фиксированное ОДНО место сразу после тира A, которое делят ВСЕ.
    items = [
        _row(5, 10, 100),  # тир A -> место 1
        _row(0, 0, 0),     # тир Б
        _row(0, 0, 0),     # тир Б
    ]
    places = compute_tiered_channel_places(items)
    assert places[0] == 1.0
    assert places[1] == places[2] == 2.0  # |A|=1 + 1, оба делят одно место
    assert places[1] > places[0]


def test_tier_c_ranked_by_cards_ascending_more_wasted_cards_is_worse():
    # Тир В (карточки есть, конверсия 0%) — ранжируется по количеству
    # карточек: чем БОЛЬШЕ впустую потрачено карт, тем ХУЖЕ место.
    items = [
        _row(5, 10, 100),  # тир A -> место 1
        _row(0, 0, 0),     # тир Б -> место 2 (|A|=1 + 1)
        _row(0, 0, 0),     # тир Б -> место 2 (делит с предыдущим)
        _row(20, 0, 0),    # тир В, 20 впустую потраченных карточек -> хуже
        _row(5, 0, 0),     # тир В, 5 впустую потраченных карточек -> лучше, чем 20
    ]
    places = compute_tiered_channel_places(items)
    assert places[0] == 1.0
    assert places[1] == places[2] == 2.0
    # |A|=1 + |Б|=2 = 3 -> тир В начинается с места 4
    assert places[4] == 4.0  # 5 карточек -> лучший в тире В
    assert places[3] == 5.0  # 20 карточек -> худший в тире В
    assert places[3] > places[4] > places[1]


def test_tier_c_ties_share_place_with_skip():
    # Равное количество впустую потраченных карточек внутри тира В ->
    # одинаковое место, следующее — со сдвигом (обычная логика rank_standard).
    items = [
        _row(5, 10, 100),  # тир A -> место 1
        _row(10, 0, 0),    # тир В, 10 карточек
        _row(10, 0, 0),    # тир В, тоже 10 карточек -> делит место с предыдущим
        _row(20, 0, 0),    # тир В, 20 карточек -> хуже обоих
    ]
    places = compute_tiered_channel_places(items)
    assert places[0] == 1.0
    # |A|=1 + |Б|=0 = 1 -> тир В начинается с места 2
    assert places[1] == places[2] == 2.0
    assert places[3] == 4.0  # сдвиг на 2 (кол-во делящих место 2)


def test_boundary_zero_cards_vs_one_card_with_conversion():
    # Порог тот же, что у тира ЛК: карточек>=1 И конверсия>0 — а не
    # конкретное число карточек.
    items = [
        _row(0, 50, 999),  # 0 карточек -> тир Б, несмотря на (нереалистичную) конверсию
        _row(1, 1, 1),     # 1 карточка И конверсия>0 -> тир A
    ]
    places = compute_tiered_channel_places(items)
    assert places[1] == 1.0  # единственный в тире A -> место 1
    assert places[0] == 2.0  # тир Б: |A|=1 + 1
    assert places[0] > places[1]


def test_cards_without_conversion_does_not_count_as_tier_a():
    # Как и у тира ЛК: карточки есть, но конверсия 0% — это НЕ тир A,
    # несмотря на сколь угодно большое число карточек — это тир В.
    items = [
        _row(1, 1, 1),      # 1 карточка, конверсия>0 -> тир A
        _row(999, 0, 999),  # 999 карточек, конверсия 0% -> тир В
    ]
    places = compute_tiered_channel_places(items)
    assert places[0] == 1.0
    assert places[1] == 2.0  # |A|=1 + |Б|=0 + ранг 1 (единственный в тире В)
