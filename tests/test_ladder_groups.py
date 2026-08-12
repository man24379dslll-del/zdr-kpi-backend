from app.services.ladder_groups import (
    TIER_COEFFICIENTS,
    assign_novice_coefficients,
    assign_tier_coefficients,
    tier_sizes,
)


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


# ---------- assign_novice_coefficients ----------
# Новички (is_novice=True) не участвуют в официальном месте группы
# (final_place остаётся None), но теперь могут получить "теоретический"
# коэффициент ЛГ для ЗП следующей недели, если их показатели достаточно
# сильные — см. docstring в app/services/ladder_groups.py.

def _evaluated_row(fio, final_place, total_score):
    return {
        "fio": fio, "supervisor": "Группа А", "is_na": False, "is_novice": False,
        "final_place": final_place, "total_score": total_score, "tie_break_value": 0,
    }


def _novice_row(fio, total_score, supervisor="Группа А"):
    return {
        "fio": fio, "supervisor": supervisor, "is_na": True, "is_novice": True,
        "final_place": None, "total_score": total_score, "tie_break_value": 0,
    }


def _make_12_evaluated():
    # total_score 1..12 (меньше = лучше), final_place = ранг = сам total_score
    return [_evaluated_row(f"Сотрудник {i}", i, float(i)) for i in range(1, 13)]


def test_strong_novice_gets_real_coefficient_above_1_05():
    # total_score=0 — лучше вообще всех 12 оценённых (1..12) -> теоретическое
    # место 1 из 13 -> tier_sizes(13) = [2,2,2,1,1,1,1,1,1,1] -> тир 1 -> 1.4
    rows = _make_12_evaluated() + [_novice_row("Новичков Н.", 0.0)]
    assign_tier_coefficients(rows)
    assign_novice_coefficients(rows)

    novice = next(r for r in rows if r["fio"] == "Новичков Н.")
    assert novice["tier"] == 1
    assert novice["coefficient"] == TIER_COEFFICIENTS[0]
    assert novice["coefficient"] >= 1.05


def test_weak_novice_coefficient_floored_to_1_0_not_worse():
    # total_score=13 — хуже вообще всех 12 оценённых -> теоретическое место
    # 13 из 13 -> tier_sizes(13)=[2,2,2,1,1,1,1,1,1,1] -> последний тир (10) ->
    # 0.25 по умолчанию, но новичка это не должно наказывать -> 1.0
    rows = _make_12_evaluated() + [_novice_row("Новичков Н.", 13.0)]
    assign_tier_coefficients(rows)
    assign_novice_coefficients(rows)

    novice = next(r for r in rows if r["fio"] == "Новичков Н.")
    assert novice["tier"] == 10
    assert novice["coefficient"] == 1.0
    assert novice["coefficient"] not in (0.75, 0.5, 0.25)


def test_novice_final_place_stays_none():
    rows = _make_12_evaluated() + [_novice_row("Новичков Н.", 0.0)]
    assign_tier_coefficients(rows)
    assign_novice_coefficients(rows)

    novice = next(r for r in rows if r["fio"] == "Новичков Н.")
    assert novice["final_place"] is None
    assert novice["is_na"] is True


def test_novices_are_independent_of_each_other():
    # Сильный (0.0 -> тир 1) и слабый (13.0 -> тир 10) новичок одной группы:
    # присутствие одного не должно менять коэффициент другого.
    evaluated = _make_12_evaluated()
    rows_both = evaluated + [_novice_row("Сильный Н.", 0.0), _novice_row("Слабый Н.", 13.0)]
    assign_tier_coefficients(rows_both)
    assign_novice_coefficients(rows_both)
    strong_both = next(r for r in rows_both if r["fio"] == "Сильный Н.")
    weak_both = next(r for r in rows_both if r["fio"] == "Слабый Н.")

    rows_strong_only = [dict(r) for r in evaluated] + [_novice_row("Сильный Н.", 0.0)]
    assign_tier_coefficients(rows_strong_only)
    assign_novice_coefficients(rows_strong_only)
    strong_alone = next(r for r in rows_strong_only if r["fio"] == "Сильный Н.")

    rows_weak_only = [dict(r) for r in evaluated] + [_novice_row("Слабый Н.", 13.0)]
    assign_tier_coefficients(rows_weak_only)
    assign_novice_coefficients(rows_weak_only)
    weak_alone = next(r for r in rows_weak_only if r["fio"] == "Слабый Н.")

    assert strong_both["coefficient"] == strong_alone["coefficient"] == TIER_COEFFICIENTS[0]
    assert weak_both["coefficient"] == weak_alone["coefficient"] == 1.0


def test_novice_presence_does_not_change_evaluated_tiers_or_coefficients():
    evaluated_without = _make_12_evaluated()
    assign_tier_coefficients(evaluated_without)
    baseline = {r["fio"]: (r["tier"], r["coefficient"]) for r in evaluated_without}

    evaluated_with = _make_12_evaluated() + [_novice_row("Новичков Н.", 0.0)]
    assign_tier_coefficients(evaluated_with)
    assign_novice_coefficients(evaluated_with)
    after = {
        r["fio"]: (r["tier"], r["coefficient"])
        for r in evaluated_with if not r.get("is_novice")
    }

    assert after == baseline


def test_group_with_no_novices_is_untouched():
    rows = _make_12_evaluated()
    assign_tier_coefficients(rows)
    assign_novice_coefficients(rows)  # не должно падать и ничего не должно добавлять
    assert all("coefficient" in r for r in rows)


def test_novice_alone_in_group_with_no_evaluated_peers():
    # evaluated пуст -> tier_sizes(0+1=1) = [1,0,...,0] -> новичок один в
    # тире 1 "по умолчанию" (не с кем сравнивать) -> максимальный коэффициент.
    rows = [_novice_row("Новичков Н.", 5.0)]
    assign_tier_coefficients(rows)
    assign_novice_coefficients(rows)
    novice = rows[0]
    assert novice["tier"] == 1
    assert novice["coefficient"] == TIER_COEFFICIENTS[0]


def test_novice_respects_custom_tier_coefficients():
    custom = [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
    rows = _make_12_evaluated() + [_novice_row("Новичков Н.", 0.0)]
    assign_tier_coefficients(rows, custom)
    assign_novice_coefficients(rows, custom)
    novice = next(r for r in rows if r["fio"] == "Новичков Н.")
    assert novice["tier"] == 1
    assert novice["coefficient"] == 9  # >= 1.05, используется как есть
