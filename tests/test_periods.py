from app.services.periods import find_previous_period, period_sort_value


def test_period_sort_value_week_is_month_times_ten_plus_week():
    assert period_sort_value("week", "7-1") == 71
    assert period_sort_value("week", "8-1") == 81
    assert period_sort_value("week", "7-5") == 75


def test_period_sort_value_day_is_the_label_itself():
    assert period_sort_value("day", "2026-07-27") == "2026-07-27"


def test_period_sort_value_unparseable_label_is_empty_string():
    assert period_sort_value("week", "not-a-period") == ""
    assert period_sort_value("week", None) == ""
    assert period_sort_value("day", None) == ""


def test_find_previous_period_crosses_month_boundary():
    # неделя 1 августа должна найти неделю 5 июля как ближайшую предыдущую
    periods = [
        {"id": "u7-3", "period_label": "7-3"},
        {"id": "u7-4", "period_label": "7-4"},
        {"id": "u7-5", "period_label": "7-5"},
        {"id": "u8-1", "period_label": "8-1"},
    ]
    previous = find_previous_period(periods, "8-1", period_type="week")
    assert previous["id"] == "u7-5"


def test_find_previous_period_within_same_month():
    periods = [
        {"id": "u7-1", "period_label": "7-1"},
        {"id": "u7-2", "period_label": "7-2"},
        {"id": "u7-3", "period_label": "7-3"},
    ]
    previous = find_previous_period(periods, "7-3", period_type="week")
    assert previous["id"] == "u7-2"


def test_find_previous_period_returns_none_when_none_earlier():
    periods = [{"id": "u7-1", "period_label": "7-1"}, {"id": "u7-2", "period_label": "7-2"}]
    assert find_previous_period(periods, "7-1", period_type="week") is None


def test_find_previous_period_ignores_other_type_and_unparseable_labels():
    periods = [
        {"id": "u-daily", "period_label": "2026-07-20"},   # другой тип (day), не должен мешать week-поиску
        {"id": "u-bad", "period_label": "not-a-period"},
        {"id": "u7-1", "period_label": "7-1"},
    ]
    previous = find_previous_period(periods, "7-2", period_type="week")
    assert previous["id"] == "u7-1"


def test_find_previous_period_day_type_sorts_lexicographically():
    periods = [
        {"id": "d1", "period_label": "2026-07-20"},
        {"id": "d2", "period_label": "2026-07-25"},
    ]
    previous = find_previous_period(periods, "2026-07-27", period_type="day")
    assert previous["id"] == "d2"


def test_find_previous_period_skips_itself_even_if_duplicated():
    periods = [{"id": "a", "period_label": "7-1"}, {"id": "b", "period_label": "7-1"}]
    assert find_previous_period(periods, "7-1", period_type="week") is None
