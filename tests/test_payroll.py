from app.services.payroll import (
    build_two_stage_payroll,
    filter_uploads_for_stage,
    format_payroll_period_label,
)

UPLOADS = [
    {"id": "u7-1", "period_label": "7-1"},
    {"id": "u7-2", "period_label": "7-2"},
    {"id": "u7-3", "period_label": "7-3"},
    {"id": "u7-4", "period_label": "7-4"},
    {"id": "u7-5", "period_label": "7-5"},
    {"id": "u8-1", "period_label": "8-1"},   # другой месяц, не должен попасть
    {"id": "u-daily", "period_label": "2026-07-27"},  # дневная выгрузка, не week-месяц
]


def test_filter_uploads_for_stage_advance_picks_weeks_1_and_2():
    matching = filter_uploads_for_stage(UPLOADS, month=7, stage="1")
    assert {u["id"] for u in matching} == {"u7-1", "u7-2"}


def test_filter_uploads_for_stage_calc_picks_weeks_3_4_5():
    matching = filter_uploads_for_stage(UPLOADS, month=7, stage="2")
    assert {u["id"] for u in matching} == {"u7-3", "u7-4", "u7-5"}


def test_filter_uploads_for_stage_ignores_other_months_and_non_weekly_labels():
    matching = filter_uploads_for_stage(UPLOADS, month=7, stage="1")
    ids = {u["id"] for u in matching}
    assert "u8-1" not in ids
    assert "u-daily" not in ids


def test_format_payroll_period_label_advance_and_calc():
    assert format_payroll_period_label(8, "1", 2026) == "01-15 Августа 2026"
    assert format_payroll_period_label(8, "2", 2026) == "16-31 Августа 2026"
    assert format_payroll_period_label(2, "2", 2024) == "16-29 Февраля 2024"  # високосный год


def test_build_two_stage_payroll_sums_net_salary_across_weeks():
    uploads = [{"id": "u7-1", "period_label": "7-1"}, {"id": "u7-2", "period_label": "7-2"}]
    ratings_by_upload = {
        "u7-1": [
            {"fio": "Иванов И.И.", "supervisor": "Супервайзер - А", "status": "Профи", "is_novice": False, "salary": 1000},
        ],
        "u7-2": [
            {"fio": "Иванов И.И.", "supervisor": "Супервайзер - А", "status": "Профи", "is_novice": False, "salary": 1200},
        ],
    }
    penalties_by_upload = {"u7-1": {"Иванов И.И.": 100}, "u7-2": {}}

    result = build_two_stage_payroll(uploads, ratings_by_upload, penalties_by_upload, month=7, stage="1", year=2026)

    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["fio"] == "Иванов И.И."
    assert row["sum"] == (1000 - 100) + (1200 - 0)
    assert row["penalty_sum"] == 100
    assert row["comment"] == "Штраф удержан: 100 ₽"
    assert result["period_label_text"] == "01-15 Июля 2026"
    assert result["weeks"] == [1, 2]


def test_build_two_stage_payroll_excludes_novices_and_null_salary():
    uploads = [{"id": "u7-1", "period_label": "7-1"}]
    ratings_by_upload = {
        "u7-1": [
            {"fio": "Новичков Н.Н.", "supervisor": "А", "status": "Новичок", "is_novice": True, "salary": 500},
            {"fio": "БезЗарплаты Б.Б.", "supervisor": "А", "status": "Профи", "is_novice": False, "salary": None},
            {"fio": "Обычный О.О.", "supervisor": "А", "status": "Профи", "is_novice": False, "salary": 900},
        ],
    }
    result = build_two_stage_payroll(uploads, ratings_by_upload, {}, month=7, stage="1", year=2026)
    fios = {r["fio"] for r in result["rows"]}
    assert fios == {"Обычный О.О."}


def test_build_two_stage_payroll_no_comment_without_penalty():
    uploads = [{"id": "u7-1", "period_label": "7-1"}]
    ratings_by_upload = {"u7-1": [{"fio": "А. А.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 700}]}
    result = build_two_stage_payroll(uploads, ratings_by_upload, {}, month=7, stage="1", year=2026)
    assert result["rows"][0]["comment"] is None


def test_build_two_stage_payroll_sorted_by_display_group_name_then_fio():
    uploads = [{"id": "u7-1", "period_label": "7-1"}]
    ratings_by_upload = {
        "u7-1": [
            {"fio": "Яковлев Я.Я.", "supervisor": "Супервайзер - Смирнов С.С.", "status": "Профи", "is_novice": False, "salary": 100},
            {"fio": "Антонов А.А.", "supervisor": "Супервайзер - Смирнов С.С.", "status": "Профи", "is_novice": False, "salary": 100},
            {"fio": "ЗДР Борисов Б.Б.", "supervisor": "операторы без супервизора", "status": "Профи", "is_novice": False, "salary": 100},
        ],
    }
    result = build_two_stage_payroll(uploads, ratings_by_upload, {}, month=7, stage="1", year=2026)
    fios_in_order = [r["fio"] for r in result["rows"]]
    # display_group_name: "операторы без супервизора" -> "Регион УК" (кириллица
    # Р), "Супервайзер - Смирнов С.С." -> очищенное "Смирнов С.С." (кириллица
    # С) — "Регион УК" идёт раньше по алфавиту, внутри группы — по fio
    assert fios_in_order == ["ЗДР Борисов Б.Б.", "Антонов А.А.", "Яковлев Я.Я."]
