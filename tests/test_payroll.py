from app.services.payroll import (
    DEFAULT_GUARANTEED_BASE,
    DEFAULT_MONTH2_TRAINING_BONUS,
    build_half_payroll,
    build_month_close_payroll,
    filter_uploads_for_periods,
    format_payroll_periods_text,
    half_payroll_periods,
    make_periods_key,
    month_close_periods,
    sort_periods,
)

UPLOADS = [
    {"id": "u7-1", "period_label": "7-1"},
    {"id": "u7-2", "period_label": "7-2"},
    {"id": "u7-3", "period_label": "7-3"},
    {"id": "u7-4", "period_label": "7-4"},
    {"id": "u7-5", "period_label": "7-5"},
    {"id": "u8-1", "period_label": "8-1"},
    {"id": "u-daily", "period_label": "2026-07-27"},  # дневная выгрузка, не week-месяц
]


def test_filter_uploads_for_periods_picks_only_marked_labels():
    matching = filter_uploads_for_periods(UPLOADS, ["7-1", "7-2"])
    assert {u["id"] for u in matching} == {"u7-1", "u7-2"}


def test_filter_uploads_for_periods_works_across_months():
    matching = filter_uploads_for_periods(UPLOADS, ["7-5", "8-1"])
    assert {u["id"] for u in matching} == {"u7-5", "u8-1"}


def test_filter_uploads_for_periods_ignores_unmarked_and_daily():
    matching = filter_uploads_for_periods(UPLOADS, ["7-1"])
    ids = {u["id"] for u in matching}
    assert ids == {"u7-1"}


def test_sort_periods_orders_chronologically_across_months():
    assert sort_periods(["8-2", "7-5", "8-1"]) == ["7-5", "8-1", "8-2"]


def test_make_periods_key_is_order_independent():
    assert make_periods_key(["8-1", "7-5", "8-2"]) == make_periods_key(["7-5", "8-2", "8-1"])
    assert make_periods_key(["7-5", "8-1", "8-2"]) == "7-5,8-1,8-2"


def test_format_payroll_periods_text_sorted_with_year():
    assert format_payroll_periods_text(["8-1", "7-5"], 2026) == "7-5, 8-1 (2026)"


# --- полу-ведомость (недели 1-2 месяца, возврат к календарной структуре) ---

def test_half_payroll_periods_is_always_weeks_1_and_2():
    assert half_payroll_periods(8) == ["8-1", "8-2"]


def test_month_close_periods_is_weeks_1_to_4():
    assert month_close_periods(8) == ["8-1", "8-2", "8-3", "8-4"]


def test_half_payroll_uses_only_weeks_1_and_2_ignores_3_and_4():
    uploads = [
        {"id": "u8-1", "period_label": "8-1"},
        {"id": "u8-2", "period_label": "8-2"},
        {"id": "u8-3", "period_label": "8-3"},
        {"id": "u8-4", "period_label": "8-4"},
    ]
    ratings_by_upload = {
        "u8-1": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000}],
        "u8-2": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1200}],
        "u8-3": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 99999}],
        "u8-4": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 99999}],
    }
    result = build_half_payroll(uploads, ratings_by_upload, {}, month=8, year=2026, hours_norm=0)
    assert result["matched_uploads"] == 2
    assert result["periods"] == ["8-1", "8-2"]
    row = result["rows"][0]
    assert row["sum"] == 1000 + 1200  # недели 3-4 не участвуют


def test_half_payroll_excludes_weekly_pay_fios_completely():
    uploads = [{"id": "u8-1", "period_label": "8-1"}]
    ratings_by_upload = {
        "u8-1": [
            {"fio": "Обычный О.О.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000},
            {"fio": "Еженедельный Е.Е.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 2000},
        ],
    }
    result = build_half_payroll(
        uploads, ratings_by_upload, {}, month=8, year=2026,
        weekly_pay_fios={"Еженедельный Е.Е."}, hours_norm=0,
    )
    fios = {r["fio"] for r in result["rows"]}
    assert fios == {"Обычный О.О."}  # "Еженедельный Е.Е." не попал вообще


def test_half_payroll_no_weekly_pay_fios_means_everyone_included():
    uploads = [{"id": "u8-1", "period_label": "8-1"}]
    ratings_by_upload = {
        "u8-1": [{"fio": "А. А.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000}],
    }
    result = build_half_payroll(uploads, ratings_by_upload, {}, month=8, year=2026, hours_norm=0)
    assert {r["fio"] for r in result["rows"]} == {"А. А."}


def test_half_payroll_applies_penalty_premium_shift_pay_adjustments():
    uploads = [{"id": "u8-1", "period_label": "8-1"}, {"id": "u8-2", "period_label": "8-2"}]
    ratings_by_upload = {
        u["id"]: [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000}]
        for u in uploads
    }
    result = build_half_payroll(
        uploads, ratings_by_upload, {}, month=8, year=2026,
        adjustments_by_fio={"Иванов И.И.": {"penalty": 300, "premium": 100, "shift_pay": 500}},
        hours_norm=0,
    )
    row = result["rows"][0]
    assert row["sum"] == 2000 - 300 + 100 + 500


def test_half_payroll_response_includes_month_and_year():
    result = build_half_payroll([], {}, {}, month=8, year=2026)
    assert result["month"] == 8
    assert result["year"] == 2026
    assert result["periods_key"] == "8-1,8-2"


# --- закрытие месяца (недели 1-4, MAX-гарантии для 1-го/2-го месяца) ---

MONTH_UPLOADS = [
    {"id": f"u8-{w}", "period_label": f"8-{w}"} for w in (1, 2, 3, 4)
]


def _month_ratings(fio, salary_per_week, work_hours_per_week=40, supervisor="С"):
    """4 недели, поровну по salary/work_hours — удобно для тестов гарантии
    (160 ч суммарно при 40 ч/нед × 4)."""
    return {
        f"u8-{w}": [{
            "fio": fio, "supervisor": supervisor, "status": "Профи", "is_novice": False,
            "salary": salary_per_week, "work_hours": work_hours_per_week,
        }]
        for w in (1, 2, 3, 4)
    }


def test_month_close_periods_covers_all_4_weeks_of_the_month():
    result = build_month_close_payroll(MONTH_UPLOADS, {}, {}, month=8, year=2026)
    assert result["periods"] == ["8-1", "8-2", "8-3", "8-4"]
    assert result["periods_key"] == "8-1,8-2,8-3,8-4"


def test_month_close_month1_guarantee_wins_when_higher_than_rating():
    ratings = _month_ratings("А. А.", salary_per_week=5000, work_hours_per_week=40)  # rating_sum=20000
    result = build_month_close_payroll(
        MONTH_UPLOADS, ratings, {}, month=8, year=2026,
        markers_by_fio={"А. А.": {"work_month": 1, "weekly_pay": False}},
        hours_norm=160,
    )
    row = result["rows"][0]
    assert row["rating_sum"] == 20000
    assert row["guaranteed_pay"] == DEFAULT_GUARANTEED_BASE * (160 / 160)  # = 40000
    assert row["base"] == 40000  # гарантия больше
    assert row["sum"] == 40000


def test_month_close_month1_rating_wins_when_higher_than_guarantee():
    ratings = _month_ratings("А. А.", salary_per_week=12500, work_hours_per_week=40)  # rating_sum=50000
    result = build_month_close_payroll(
        MONTH_UPLOADS, ratings, {}, month=8, year=2026,
        markers_by_fio={"А. А.": {"work_month": 1, "weekly_pay": False}},
        hours_norm=160,
    )
    row = result["rows"][0]
    assert row["base"] == 50000  # по рейтингу больше гарантии (40000)
    assert row["sum"] == 50000


def test_month_close_month2_adds_training_bonus_to_guarantee():
    ratings = _month_ratings("А. А.", salary_per_week=2500, work_hours_per_week=40)  # rating_sum=10000
    result = build_month_close_payroll(
        MONTH_UPLOADS, ratings, {}, month=8, year=2026,
        markers_by_fio={"А. А.": {"work_month": 2, "weekly_pay": False}},
        hours_norm=160,
    )
    row = result["rows"][0]
    assert row["guaranteed_pay"] == DEFAULT_GUARANTEED_BASE + DEFAULT_MONTH2_TRAINING_BONUS  # 40000+5000
    assert row["base"] == 45000


def test_month_close_month3_plus_ignores_guarantee_entirely():
    # Часов достаточно для гарантии 40000, но rating_sum намного меньше —
    # с 3-го месяца сравнения нет вообще, база = ровно rating_sum.
    ratings = _month_ratings("А. А.", salary_per_week=3086.25, work_hours_per_week=40)  # rating_sum=12345
    result = build_month_close_payroll(
        MONTH_UPLOADS, ratings, {}, month=8, year=2026,
        markers_by_fio={"А. А.": {"work_month": 3, "weekly_pay": False}},
        hours_norm=160,
    )
    row = result["rows"][0]
    assert row["guaranteed_pay"] is None
    assert row["base"] == 12345
    assert row["sum"] == 12345


def test_month_close_deducts_half_payroll_for_regular_employee():
    ratings = _month_ratings("А. А.", salary_per_week=5000, work_hours_per_week=0)  # rating_sum=20000
    result = build_month_close_payroll(
        MONTH_UPLOADS, ratings, {}, month=8, year=2026,
        markers_by_fio={"А. А.": {"work_month": 3, "weekly_pay": False}},
        half_sum_by_fio={"А. А.": 2000},
        hours_norm=0,
    )
    row = result["rows"][0]
    assert row["half_deduction"] == 2000
    assert row["sum"] == 20000 - 2000


def test_month_close_no_deduction_for_weekly_pay_even_if_half_sum_present():
    # Защита: half_sum_by_fio у "еженедельного" может случайно содержать
    # запись (build_half_payroll её никогда не создаёт, но проверяем, что
    # даже тогда вычет не применяется — решает флаг weekly_pay, не
    # наличие/отсутствие в словаре).
    ratings = _month_ratings("Е. Е.", salary_per_week=5000, work_hours_per_week=0)  # rating_sum=20000
    result = build_month_close_payroll(
        MONTH_UPLOADS, ratings, {}, month=8, year=2026,
        markers_by_fio={"Е. Е.": {"work_month": 3, "weekly_pay": True}},
        half_sum_by_fio={"Е. Е.": 9999},
        hours_norm=0,
    )
    row = result["rows"][0]
    assert row["half_deduction"] == 0
    assert row["sum"] == 20000


def test_month_close_applies_penalty_premium_shift_pay_after_base():
    ratings = _month_ratings("А. А.", salary_per_week=5000, work_hours_per_week=0)  # rating_sum=20000
    result = build_month_close_payroll(
        MONTH_UPLOADS, ratings, {}, month=8, year=2026,
        markers_by_fio={"А. А.": {"work_month": 3, "weekly_pay": False}},
        adjustments_by_fio={"А. А.": {"penalty": 1000, "premium": 500, "shift_pay": 3000}},
        hours_norm=0,
    )
    row = result["rows"][0]
    assert row["sum"] == 20000 - 1000 + 500 + 3000


def test_month_close_overtime_pay_added_and_clamped_at_zero():
    ratings = _month_ratings("А. А.", salary_per_week=5000, work_hours_per_week=50)  # 200ч за месяц
    result = build_month_close_payroll(
        MONTH_UPLOADS, ratings, {}, month=8, year=2026,
        markers_by_fio={"А. А.": {"work_month": 3, "weekly_pay": False}},
        hours_norm=160, overtime_rate=150,
    )
    row = result["rows"][0]
    assert row["overtime_pay"] == (200 - 160) * 150  # = 6000
    assert row["sum"] == 20000 + 6000

    ratings_under = _month_ratings("Б. Б.", salary_per_week=5000, work_hours_per_week=30)  # 120ч, меньше нормы
    result_under = build_month_close_payroll(
        MONTH_UPLOADS, ratings_under, {}, month=8, year=2026,
        markers_by_fio={"Б. Б.": {"work_month": 3, "weekly_pay": False}},
        hours_norm=160, overtime_rate=150,
    )
    row_under = result_under["rows"][0]
    assert row_under["overtime_pay"] == 0  # не уходит в минус
    assert row_under["sum"] == 20000


def test_month_close_uses_default_guaranteed_base_and_month2_bonus_when_not_passed():
    ratings = _month_ratings("А. А.", salary_per_week=0, work_hours_per_week=40)  # rating_sum=0 -> гарантия побеждает
    result = build_month_close_payroll(
        MONTH_UPLOADS, ratings, {}, month=8, year=2026,
        markers_by_fio={"А. А.": {"work_month": 2, "weekly_pay": False}},
        hours_norm=160,
    )
    row = result["rows"][0]
    assert row["guaranteed_pay"] == DEFAULT_GUARANTEED_BASE + DEFAULT_MONTH2_TRAINING_BONUS


def test_month_close_missing_marker_defaults_to_work_month_1_and_not_weekly_pay():
    ratings = _month_ratings("Без маркера Б. М.", salary_per_week=1000, work_hours_per_week=40)  # rating_sum=4000
    result = build_month_close_payroll(MONTH_UPLOADS, ratings, {}, month=8, year=2026, hours_norm=160)
    row = result["rows"][0]
    assert row["work_month"] == 1
    assert row["weekly_pay"] is False
    assert row["guaranteed_pay"] == DEFAULT_GUARANTEED_BASE  # сравнение всё равно применяется (work_month=1)
