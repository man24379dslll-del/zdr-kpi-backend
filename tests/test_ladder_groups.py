from app.services.ladder_groups import TIER_COEFFICIENTS, assign_tier_coefficients, tier_sizes


def test_tier_sizes_even_split():
    assert tier_sizes(10) == [1] * 10


def test_tier_sizes_remainder_goes_to_first_tiers():
    # 25 = 2*10 + 5 -> первые 5 тиров получают по 3, остальные по 2
    assert tier_sizes(25) == [3, 3, 3, 3, 3, 2, 2, 2, 2, 2]


def test_tier_sizes_fewer_than_ten_people():
    assert tier_sizes(3) == [1, 1, 1, 0, 0, 0, 0, 0, 0, 0]


def _row(supervisor, final_place, is_na=False):
    return {"supervisor": supervisor, "final_place": final_place, "is_na": is_na}


def test_assigns_tiers_by_final_place_within_supervisor():
    rows = [_row("Иванов", place) for place in range(1, 13)]  # 12 человек
    assign_tier_coefficients(rows)
    by_place = {r["final_place"]: r for r in rows}

    # 12 = 1*10 + 2 -> первые 2 тира получают по 2 человека, остальные по 1
    assert by_place[1]["tier"] == 1
    assert by_place[2]["tier"] == 1
    assert by_place[1]["coefficient"] == TIER_COEFFICIENTS[0]
    assert by_place[3]["tier"] == 2
    assert by_place[4]["tier"] == 2
    assert by_place[5]["tier"] == 3
    assert by_place[12]["tier"] == 10
    assert by_place[12]["coefficient"] == TIER_COEFFICIENTS[-1]


def test_na_rows_are_excluded_and_untouched():
    rows = [_row("Иванов", 1), _row("Иванов", 2, is_na=True), _row("Иванов", 3)]
    assign_tier_coefficients(rows)
    by_place = {r["final_place"]: r for r in rows}
    assert "tier" not in by_place[2]
    assert "coefficient" not in by_place[2]
    assert by_place[1]["tier"] == 1
    assert by_place[3]["tier"] == 2  # только 2 оценённых -> тиры 1 и 2 по одному


def test_supervisors_are_grouped_independently():
    rows = [
        _row("Иванов", 1), _row("Иванов", 2),
        _row("Петров", 1), _row("Петров", 2),
    ]
    assign_tier_coefficients(rows)
    ivanov = [r for r in rows if r["supervisor"] == "Иванов"]
    petrov = [r for r in rows if r["supervisor"] == "Петров"]
    assert sorted(r["tier"] for r in ivanov) == [1, 2]
    assert sorted(r["tier"] for r in petrov) == [1, 2]


def test_custom_tier_coefficients_override_the_default():
    # Кастомный набор, явно отличающийся от TIER_COEFFICIENTS по умолчанию:
    # тир 1 должен получить ×2, а не захардкоженный ×1.4.
    custom = [2, 1, 1, 1, 1, 1, 1, 1, 1, 1]
    rows = [_row("Иванов", place) for place in range(1, 11)]  # ровно 10 -> по 1 на тир
    assign_tier_coefficients(rows, custom)
    by_place = {r["final_place"]: r for r in rows}
    assert by_place[1]["coefficient"] == 2
    assert by_place[1]["coefficient"] != TIER_COEFFICIENTS[0]
    for place in range(2, 11):
        assert by_place[place]["coefficient"] == 1


def test_no_custom_coefficients_falls_back_to_default():
    rows = [_row("Иванов", place) for place in range(1, 11)]
    assign_tier_coefficients(rows, None)
    by_place = {r["final_place"]: r for r in rows}
    for tier_idx, place in enumerate(range(1, 11)):
        assert by_place[place]["coefficient"] == TIER_COEFFICIENTS[tier_idx]
