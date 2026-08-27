"""
Дашборды (сводка/воронка новичков/каналы/аномалии) — чистые функции,
без сети. Фикстуры подобраны так, чтобы числа проверялись вручную легко.
"""
from app.services.dashboards import (
    build_anomalies_dashboard,
    build_channels_dashboard,
    build_levels_dashboard,
    build_newcomer_funnel,
    build_summary_dashboard,
    conv_band,
)


def _row(
    fio, supervisor, status="Профи", is_novice=False, is_na=False, total_score=None,
    tier=None, salary=None, c1_per_contact=0, lk_per_contact=0, ch_per_contact=0,
    time_per_contact=0, errors_pct=0, channel="radio", ch_conv=0, ch_sum=0,
    c1_sum=1000, final_place=None,
    # Доп. поля — нужны только тестам build_levels_dashboard, у остальных
    # тестов этого файла остаются в дефолте (None/0), поведение не меняют.
    coefficient=None, c1_cards=None, c1_check=None, c1_conv=None, c1_place=None,
    lk_sum=0, lk_cards=None, lk_check=None, lk_conv=None, lk_place=None,
    ch_cards=None, ch_check=None, ch_place=None,
    time_place=None, errors_place=None, errors_count=None,
    work_hours=None, shift_count=None, bonus075=None, bonus2=None,
):
    return {
        "fio": fio, "supervisor": supervisor, "status": status, "is_novice": is_novice,
        "is_na": is_na, "total_score": total_score, "tier": tier, "coefficient": coefficient,
        "salary": salary, "c1_per_contact": c1_per_contact, "lk_per_contact": lk_per_contact,
        "ch_per_contact": ch_per_contact, "time_per_contact": time_per_contact,
        "errors_pct": errors_pct, "channel": channel, "ch_conv": ch_conv, "ch_sum": ch_sum,
        "c1_sum": c1_sum, "final_place": final_place,
        "c1_cards": c1_cards, "c1_check": c1_check, "c1_conv": c1_conv, "c1_place": c1_place,
        "lk_sum": lk_sum, "lk_cards": lk_cards, "lk_check": lk_check, "lk_conv": lk_conv, "lk_place": lk_place,
        "ch_cards": ch_cards, "ch_check": ch_check, "ch_place": ch_place,
        "time_place": time_place, "errors_place": errors_place, "errors_count": errors_count,
        "work_hours": work_hours, "shift_count": shift_count, "bonus075": bonus075, "bonus2": bonus2,
    }


# --- сводка ---

RATINGS = [
    _row("Иванов И.И.", "Супервайзер - А", total_score=10, tier=3, salary=1000, final_place=3),
    _row("Петров П.П.", "Супервайзер - А", total_score=20, tier=5, salary=800, final_place=5),
    _row("Сидоров С.С.", "Супервайзер - Б", status="Лидер", total_score=15, tier=4, salary=1200, final_place=4),
    _row("Кузнецов К.К.", "Супервайзер - Б", is_na=True, salary=500),
    _row("ЗДР Морозов М.М.", "операторы без супервизора", total_score=5, tier=1, salary=900, final_place=1),
    _row("Новиков Н.Н.", "Супервайзер - А", is_novice=True, c1_per_contact=1000),   # худшая band
    _row("Волкова В.В.", "Супервайзер - Б", is_novice=True, c1_per_contact=3000),   # не худшая band
]


def test_summary_counts_main_evaluated_and_region_uk():
    result = build_summary_dashboard(RATINGS, period_label="7-1")
    assert result["total_in_rating"] == 5          # без 2 новичков
    assert result["without_region_uk"] == 4         # без ЗДР Морозова
    assert result["evaluated_count"] == 4            # без Кузнецова (Н/О)


def test_summary_avg_score_over_evaluated_only():
    result = build_summary_dashboard(RATINGS, period_label="7-1")
    assert result["avg_score"] == (10 + 20 + 15 + 5) / 4


def test_summary_salary_fund_only_for_weekly_period_label():
    weekly = build_summary_dashboard(RATINGS, period_label="7-1")
    assert weekly["salary_fund"] == 1000 + 800 + 1200 + 500 + 900  # по main, включая Н/О

    daily = build_summary_dashboard(RATINGS, period_label="2026-07-27")
    assert daily["salary_fund"] is None


def test_summary_tier_distribution():
    result = build_summary_dashboard(RATINGS, period_label="7-1")
    assert result["tier_distribution"][1] == 1
    assert result["tier_distribution"][3] == 1
    assert result["tier_distribution"][4] == 1
    assert result["tier_distribution"][5] == 1
    assert result["tier_distribution"][2] == 0


def test_summary_status_counts_and_by_status():
    result = build_summary_dashboard(RATINGS, period_label="7-1")
    assert result["status_counts"]["Профи"] == 4  # Иванов, Петров, Кузнецов, ЗДР Морозов (включая Н/О)
    assert result["status_counts"]["Лидер"] == 1  # Сидоров

    # by_status считается по evaluated, не по main — Кузнецов (Н/О) сюда не входит
    by_status = {e["status"]: e for e in result["by_status"]}
    assert by_status["Профи"]["count"] == 3
    assert by_status["Лидер"]["count"] == 1


def test_summary_by_status_averages_exclude_na_even_though_status_counts_include_them():
    ratings = [
        _row("А", "С1", status="Профи", c1_per_contact=100),
        _row("Б", "С1", status="Профи", c1_per_contact=200),
        _row("В", "С1", status="Профи", is_na=True, c1_per_contact=99999),  # Н/О — не должен влиять на среднее
    ]
    result = build_summary_dashboard(ratings, period_label="7-1")
    assert result["status_counts"]["Профи"] == 3  # включая Н/О

    by_status = {e["status"]: e for e in result["by_status"]}
    assert by_status["Профи"]["count"] == 2  # без Н/О
    assert by_status["Профи"]["avg_c1_per_contact"] == 150  # (100+200)/2, не с учётом 99999


def test_summary_novices_by_supervisor_excludes_region_uk_and_computes_bad_pct():
    result = build_summary_dashboard(RATINGS, period_label="7-1")
    by_supervisor = {e["supervisor"]: e for e in result["novices_by_supervisor"]}
    assert "операторы без супервизора" not in by_supervisor
    assert by_supervisor["Супервайзер - А"]["total"] == 1
    assert by_supervisor["Супервайзер - А"]["bad_count"] == 1  # Новиков c1=1000 < 1608
    assert by_supervisor["Супервайзер - А"]["bad_pct"] == 100.0
    assert by_supervisor["Супервайзер - Б"]["total"] == 1
    assert by_supervisor["Супервайзер - Б"]["bad_count"] == 0  # Волкова c1=3000, не худшая band


def test_summary_deltas_direction_score_lower_is_better_salary_higher_is_better():
    previous = [_row("Иванов И.И.", "Супервайзер - А", total_score=30, salary=500)]
    result = build_summary_dashboard(RATINGS, period_label="7-1", previous_ratings=previous)
    # текущий avg_score (12.5) МЕНЬШЕ предыдущего (30) -> улучшение
    assert result["avg_score_delta"]["is_improvement"] is True
    # текущий фонд ЗП БОЛЬШЕ предыдущего -> улучшение
    assert result["salary_fund_delta"]["is_improvement"] is True


def test_summary_without_previous_ratings_omits_deltas():
    result = build_summary_dashboard(RATINGS, period_label="7-1")
    assert result["avg_score_delta"] is None
    assert result["salary_fund_delta"] is None


# --- воронка новичков ---

def test_conv_band_boundaries():
    assert conv_band(0) == "Прекращение сотрудничества"
    assert conv_band(1607) == "Прекращение сотрудничества"
    assert conv_band(1608) == "Предупреждение + 1 неделя"
    assert conv_band(2143) == "Предупреждение + 1 неделя"
    assert conv_band(2144) == "Норма 1-й недели"
    assert conv_band(2679) == "Норма 1-й недели"
    assert conv_band(2680) == "Сверх нормы"
    assert conv_band(3859) == "Сверх нормы"
    assert conv_band(3860) == "Мы искали Вас!"
    assert conv_band(999999) == "Мы искали Вас!"
    assert conv_band(None) == "Прекращение сотрудничества"  # None -> 0


def test_newcomer_funnel_groups_by_band_sorted_desc_by_c1_per_contact():
    novices = [
        _row("А", "С1", is_novice=True, c1_per_contact=1500),
        _row("Б", "С1", is_novice=True, c1_per_contact=1000),
        _row("В", "С2", is_novice=True, c1_per_contact=3000),
    ]
    result = build_newcomer_funnel(novices)
    bands = {b["label"]: b for b in result["bands"]}
    worst = bands["Прекращение сотрудничества"]
    assert worst["count"] == 2
    assert [e["fio"] for e in worst["employees"]] == ["А", "Б"]  # 1500 > 1000, убыв.
    assert bands["Сверх нормы"]["count"] == 1


def test_newcomer_funnel_count_delta_vs_previous():
    novices = [_row("А", "С1", is_novice=True, c1_per_contact=1000)]
    previous = [
        _row("Б", "С1", is_novice=True, c1_per_contact=1000),
        _row("В", "С1", is_novice=True, c1_per_contact=1000),
    ]
    result = build_newcomer_funnel(novices, previous)
    bands = {b["label"]: b for b in result["bands"]}
    assert bands["Прекращение сотрудничества"]["count_delta"] == 1 - 2


# --- каналы ---

def test_channels_dashboard_groups_by_channel_excludes_novices_and_na():
    ratings = [
        _row("А", "С1", channel="radio", ch_per_contact=100, ch_conv=10, ch_sum=1000),
        _row("Б", "С1", channel="radio", ch_per_contact=200, ch_conv=20, ch_sum=2000),
        _row("В", "С1", channel="inet", ch_per_contact=300, ch_conv=30, ch_sum=3000),
        _row("Г", "С1", channel="inet", is_na=True, ch_per_contact=999),        # Н/О исключён
        _row("Д", "С1", channel="radio", is_novice=True, ch_per_contact=999),   # новичок исключён
    ]
    result = build_channels_dashboard(ratings)
    by_channel = {c["channel"]: c for c in result["channels"]}
    assert by_channel["radio"]["count"] == 2  # без Д (новичок)
    assert by_channel["radio"]["avg_ch_per_contact"] == 150
    assert by_channel["radio"]["sum_ch_sum"] == 3000
    assert by_channel["inet"]["count"] == 1  # без Г (Н/О)
    assert by_channel["inet"]["avg_ch_per_contact"] == 300


# --- аномалии ---

def test_anomalies_detects_sharp_drop():
    current = [_row("А", "С1", final_place=15, is_na=False)]
    previous = [_row("А", "С1", final_place=3, is_na=False)]
    result = build_anomalies_dashboard(current, previous)
    assert len(result) == 1
    assert result[0]["severity"] == "err"
    assert "Резкое падение" in result[0]["reason"]


def test_anomalies_ignores_drop_under_10_places():
    current = [_row("А", "С1", final_place=10, is_na=False)]
    previous = [_row("А", "С1", final_place=3, is_na=False)]
    result = build_anomalies_dashboard(current, previous)
    assert result == []


def test_anomalies_zero_sales_message_includes_both_period_labels():
    current = [_row("А", "С1", c1_sum=0)]
    previous = [_row("А", "С1", c1_sum=0)]
    result = build_anomalies_dashboard(current, previous, period_label="7-2", previous_period_label="7-1")
    assert any(
        a["reason"] == "0 продаж по 1 обращению два периода подряд (7-1 и 7-2)"
        for a in result
    )


def test_anomalies_high_error_rate_does_not_need_previous_period():
    current = [_row("А", "С1", errors_pct=15)]
    result = build_anomalies_dashboard(current, previous_ratings=None)
    assert any(a["reason"] == "Высокий % ошибок: 15%" for a in result)


def test_anomalies_excludes_novices():
    current = [_row("А", "С1", is_novice=True, errors_pct=99)]
    result = build_anomalies_dashboard(current)
    assert result == []


# --- "По уровням" ---

def test_levels_excludes_region_uk_peaks_and_vasko():
    ratings = [
        _row("Иванов И.И.", "Супервайзер - А", status="Профи", c1_per_contact=100),
        _row("ЗДР Кузьмин К.К.", "операторы без супервизора", status="Профи", c1_per_contact=99999),
        _row("Оператор О.О.", "операторы без супервизора [Пики-ПП]", status="Профи", c1_per_contact=99999),
        _row("Николаева Н.Н.", "Супервайзер - Васько Юлия Владимировна", status="Профи", c1_per_contact=99999),
    ]
    result = build_levels_dashboard(ratings)
    # только "настоящая" группа осталась — Регион УК/ПП/Васько убраны
    assert result["included_groups"] == ["А"]
    profi = next(e for e in result["levels"] if e["status"] == "Профи")
    assert profi["count"] == 1
    assert profi["c1"]["pc"] == 100  # не 99999 — исключённые не попали в среднее


def test_levels_includes_novices_as_separate_status_rows():
    ratings = [
        _row("Иванов И.И.", "Супервайзер - А", status="Профи", c1_per_contact=100),
        _row("Сидорова С.С.", "Супервайзер - А", status="Новичок, 1-й уровень", is_novice=True, c1_per_contact=500),
    ]
    result = build_levels_dashboard(ratings)
    statuses = {e["status"] for e in result["levels"]}
    assert "Новичок, 1-й уровень" in statuses
    novice_level = next(e for e in result["levels"] if e["status"] == "Новичок, 1-й уровень")
    assert novice_level["count"] == 1
    assert novice_level["c1"]["pc"] == 500


def test_levels_excludes_na_rows():
    ratings = [
        _row("Иванов И.И.", "Супервайзер - А", status="Профи", c1_per_contact=100),
        _row("Тренер Т.Т.", "Супервайзер - А", status="Тренер", is_na=True, c1_per_contact=99999),
    ]
    result = build_levels_dashboard(ratings)
    statuses = {e["status"] for e in result["levels"]}
    assert "Тренер" not in statuses
    profi = next(e for e in result["levels"] if e["status"] == "Профи")
    assert profi["count"] == 1


def test_levels_category_cards_and_sum_are_summed_rest_is_averaged():
    ratings = [
        _row(
            "Иванов И.И.", "Супервайзер - А", status="Профи",
            c1_cards=2, c1_sum=1000, c1_check=100, c1_conv=10, c1_per_contact=200, c1_place=1,
        ),
        _row(
            "Петров П.П.", "Супервайзер - А", status="Профи",
            c1_cards=4, c1_sum=2000, c1_check=200, c1_conv=20, c1_per_contact=400, c1_place=3,
        ),
    ]
    result = build_levels_dashboard(ratings)
    profi = next(e for e in result["levels"] if e["status"] == "Профи")
    assert profi["c1"]["cards"] == 6      # сумма
    assert profi["c1"]["sum"] == 3000     # сумма
    assert profi["c1"]["check"] == 150    # среднее
    assert profi["c1"]["conv"] == 15      # среднее
    assert profi["c1"]["pc"] == 300       # среднее
    assert profi["c1"]["place"] == 2      # среднее


def test_levels_final_place_tier_coefficient_average_only_over_non_null():
    ratings = [
        _row("Иванов И.И.", "Супервайзер - А", status="Профи", final_place=1, tier=3, coefficient=1.2),
        _row("Петров П.П.", "Супервайзер - А", status="Профи", final_place=3, tier=None, coefficient=None),
    ]
    result = build_levels_dashboard(ratings)
    profi = next(e for e in result["levels"] if e["status"] == "Профи")
    assert profi["final_place_avg"] == 2      # (1+3)/2
    assert profi["tier_avg"] == 3             # только Иванов, Петров пропущен (None)
    assert profi["coefficient_avg"] == 1.2    # только Иванов


def test_levels_prev_week_coefficient_matched_by_fio_only_when_found():
    current = [
        _row("А", "С1", status="Профи"),
        _row("Б", "С1", status="Профи"),
    ]
    previous = [
        _row("А", "С1", coefficient=2.0),
        _row("В", "С1", coefficient=99),  # другой человек, не должен влиять
    ]
    result = build_levels_dashboard(current, previous)
    profi = next(e for e in result["levels"] if e["status"] == "Профи")
    # "Б" не нашёлся в previous -> пропущен, не считается за 0
    assert profi["prev_week_coefficient_avg"] == 2.0


def test_levels_work_hours_shifts_bonuses_salary_are_summed():
    ratings = [
        _row("А", "С1", status="Профи", work_hours=40, shift_count=5, bonus075=100, bonus2=200, salary=5000),
        _row("Б", "С1", status="Профи", work_hours=35, shift_count=4, bonus075=50, bonus2=100, salary=4000),
    ]
    result = build_levels_dashboard(ratings)
    profi = next(e for e in result["levels"] if e["status"] == "Профи")
    assert profi["work_hours"] == 75
    assert profi["shift_count"] == 9
    assert profi["bonus075"] == 150
    assert profi["bonus2"] == 300
    assert profi["salary"] == 9000


def test_levels_total_row_is_honest_recompute_not_average_of_level_averages():
    ratings = [
        _row("А", "С1", status="Профи", c1_per_contact=200),
        _row("Б", "С1", status="Профи", c1_per_contact=400),
        _row("В", "С1", status="Лидер", c1_per_contact=900),
    ]
    result = build_levels_dashboard(ratings)
    # среднее по всем 3 людям = (200+400+900)/3 = 500, а НЕ среднее
    # средних по уровням ((300+900)/2 = 600) — честный пересчёт, не
    # механическая сумма/среднее строк уровней.
    assert result["total"]["c1"]["pc"] == 500
    assert result["total"]["status"] == "ИТОГО — ВСЕ УРОВНИ"


def test_levels_sorted_by_fixed_progression_not_alphabetically():
    ratings = [
        _row("А", "С1", status="Лидер"),
        _row("Б", "С1", status="Новичок, 2-й уровень", is_novice=True),
        _row("В", "С1", status="Квалифицированный"),
        _row("Г", "С1", status="НеизвестныйСтатус"),
    ]
    result = build_levels_dashboard(ratings)
    order = [e["status"] for e in result["levels"]]
    # алфавитный порядок дал бы "Квалифицированный, Лидер, ..." — тут
    # прогрессия: новички -> ... -> Лидер, неизвестные — в конце
    assert order == ["Новичок, 2-й уровень", "Квалифицированный", "Лидер", "НеизвестныйСтатус"]


def test_levels_deltas_present_for_requested_metrics_with_correct_direction():
    current = [_row("А", "С1", status="Профи", total_score=10, salary=1000, errors_pct=5, c1_per_contact=200)]
    previous = [_row("А", "С1", status="Профи", total_score=20, salary=500, errors_pct=10, c1_per_contact=100)]
    result = build_levels_dashboard(current, previous)
    profi = next(e for e in result["levels"] if e["status"] == "Профи")
    # total_score меньше -> улучшение (меньше баллов = лучше место, LOWER_IS_BETTER)
    assert profi["deltas"]["total_score"]["is_improvement"] is True
    # salary больше -> улучшение
    assert profi["deltas"]["salary"]["is_improvement"] is True
    # errors_pct меньше -> улучшение
    assert profi["deltas"]["errors_pct"]["is_improvement"] is True
    # c1_pc больше -> улучшение
    assert profi["deltas"]["c1_pc"]["is_improvement"] is True


def test_levels_without_previous_ratings_omits_deltas():
    ratings = [_row("А", "С1", status="Профи")]
    result = build_levels_dashboard(ratings)
    profi = next(e for e in result["levels"] if e["status"] == "Профи")
    assert "deltas" not in profi
    assert "deltas" not in result["total"]
