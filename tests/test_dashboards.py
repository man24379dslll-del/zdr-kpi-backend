"""
Дашборды (сводка/воронка новичков/каналы/аномалии) — чистые функции,
без сети. Фикстуры подобраны так, чтобы числа проверялись вручную легко.
"""
from app.services.dashboards import (
    build_anomalies_dashboard,
    build_channels_dashboard,
    build_newcomer_funnel,
    build_summary_dashboard,
    conv_band,
)


def _row(
    fio, supervisor, status="Профи", is_novice=False, is_na=False, total_score=None,
    tier=None, salary=None, c1_per_contact=0, lk_per_contact=0, ch_per_contact=0,
    time_per_contact=0, errors_pct=0, channel="radio", ch_conv=0, ch_sum=0,
    c1_sum=1000, final_place=None,
):
    return {
        "fio": fio, "supervisor": supervisor, "status": status, "is_novice": is_novice,
        "is_na": is_na, "total_score": total_score, "tier": tier, "coefficient": None,
        "salary": salary, "c1_per_contact": c1_per_contact, "lk_per_contact": lk_per_contact,
        "ch_per_contact": ch_per_contact, "time_per_contact": time_per_contact,
        "errors_pct": errors_pct, "channel": channel, "ch_conv": ch_conv, "ch_sum": ch_sum,
        "c1_sum": c1_sum, "final_place": final_place,
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
