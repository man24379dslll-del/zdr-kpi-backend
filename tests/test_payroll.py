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
    # Разбивка по неделям — сумма элементов равна row["sum"], значения net
    # (за вычетом по-недельного штрафа, как и sum)
    assert row["weeks"] == [
        {"period_label": "7-1", "sum": 1000 - 100},
        {"period_label": "7-2", "sum": 1200 - 0},
    ]
    assert sum(w["sum"] for w in row["weeks"]) == row["sum"]


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


# --- разбивка по неделям ("weeks") ---

def test_weeks_breakdown_has_three_entries_for_calc_stage():
    uploads = [
        {"id": "u7-3", "period_label": "7-3"},
        {"id": "u7-4", "period_label": "7-4"},
        {"id": "u7-5", "period_label": "7-5"},
    ]
    ratings_by_upload = {
        "u7-3": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000}],
        "u7-4": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1100}],
        "u7-5": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1200}],
    }
    result = build_two_stage_payroll(uploads, ratings_by_upload, {}, month=7, stage="2", year=2026)
    row = result["rows"][0]
    assert row["weeks"] == [
        {"period_label": "7-3", "sum": 1000},
        {"period_label": "7-4", "sum": 1100},
        {"period_label": "7-5", "sum": 1200},
    ]


def test_weeks_breakdown_only_includes_weeks_person_actually_has_salary_for():
    # Если человек пропустил неделю (не было строки/salary=None) — эта
    # неделя просто отсутствует в его разбивке, не 0.
    uploads = [{"id": "u7-3", "period_label": "7-3"}, {"id": "u7-4", "period_label": "7-4"}]
    ratings_by_upload = {
        "u7-3": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000}],
        "u7-4": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": None}],
    }
    result = build_two_stage_payroll(uploads, ratings_by_upload, {}, month=7, stage="2", year=2026)
    row = result["rows"][0]
    assert row["weeks"] == [{"period_label": "7-3", "sum": 1000}]


def test_weeks_breakdown_sorted_by_week_number_regardless_of_upload_order():
    uploads = [{"id": "u7-4", "period_label": "7-4"}, {"id": "u7-3", "period_label": "7-3"}]  # заведомо не по порядку
    ratings_by_upload = {
        "u7-4": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1100}],
        "u7-3": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000}],
    }
    result = build_two_stage_payroll(uploads, ratings_by_upload, {}, month=7, stage="2", year=2026)
    row = result["rows"][0]
    assert [w["period_label"] for w in row["weeks"]] == ["7-3", "7-4"]


def test_weeks_breakdown_unaffected_by_stage_adjustment():
    # Штраф/премия этапа применяются к итогу ("sum"), НЕ к конкретной
    # неделе — разбивка "weeks" отражает только по-недельные суммы,
    # сумма её элементов НЕ обязана совпадать с итоговым "sum" после
    # применения корректировки этапа.
    uploads = [{"id": "u7-3", "period_label": "7-3"}]
    ratings_by_upload = {"u7-3": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000}]}
    result = build_two_stage_payroll(
        uploads, ratings_by_upload, {}, month=7, stage="2", year=2026,
        stage_adjustments_by_fio={"Иванов И.И.": {"penalty": 500, "premium": 0}},
    )
    row = result["rows"][0]
    assert row["weeks"] == [{"period_label": "7-3", "sum": 1000}]
    assert row["sum"] == 500  # 1000 - 500 (корректировка этапа), не в разбивке


# --- штраф/премия за этап (payroll_stage_adjustments) ---

def test_stage_adjustment_applies_only_for_stage_2():
    uploads = [
        {"id": "u7-3", "period_label": "7-3"},
        {"id": "u7-4", "period_label": "7-4"},
        {"id": "u7-5", "period_label": "7-5"},
    ]
    ratings_by_upload = {
        u["id"]: [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000}]
        for u in uploads
    }
    stage_adjustments = {"Иванов И.И.": {"penalty": 500, "premium": 200}}

    result = build_two_stage_payroll(
        uploads, ratings_by_upload, {}, month=7, stage="2", year=2026,
        stage_adjustments_by_fio=stage_adjustments,
    )
    row = result["rows"][0]
    assert row["penalty"] == 500
    assert row["premium"] == 200
    assert row["sum"] == 3000 - 500 + 200


def test_stage_adjustment_has_no_effect_on_stage_1_even_if_passed():
    uploads = [{"id": "u7-1", "period_label": "7-1"}, {"id": "u7-2", "period_label": "7-2"}]
    ratings_by_upload = {
        u["id"]: [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000}]
        for u in uploads
    }
    # даже если по ошибке передать корректировки на аванс — они не должны применяться
    stage_adjustments = {"Иванов И.И.": {"penalty": 500, "premium": 200}}

    result = build_two_stage_payroll(
        uploads, ratings_by_upload, {}, month=7, stage="1", year=2026,
        stage_adjustments_by_fio=stage_adjustments,
    )
    row = result["rows"][0]
    assert "penalty" not in row
    assert "premium" not in row
    assert row["sum"] == 2000


def test_stage_adjustment_defaults_to_zero_when_no_record_for_stage_2():
    uploads = [{"id": "u7-3", "period_label": "7-3"}]
    ratings_by_upload = {"u7-3": [{"fio": "Без корректировки Б.Б.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 500}]}
    result = build_two_stage_payroll(uploads, ratings_by_upload, {}, month=7, stage="2", year=2026, stage_adjustments_by_fio={})
    row = result["rows"][0]
    assert row["penalty"] == 0
    assert row["premium"] == 0
    assert row["sum"] == 500


def test_stage_adjustment_reflects_latest_saved_value_after_upsert():
    # Эмулирует апсерт: PUT /payroll/stage-adjustment перезаписывает запись
    # по (month, year, fio) — второй расчёт с обновлённым значением должен
    # показать НОВОЕ значение, не накопленную сумму двух сохранений.
    uploads = [{"id": "u7-3", "period_label": "7-3"}]
    ratings_by_upload = {"u7-3": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000}]}

    first = build_two_stage_payroll(
        uploads, ratings_by_upload, {}, month=7, stage="2", year=2026,
        stage_adjustments_by_fio={"Иванов И.И.": {"penalty": 100, "premium": 0}},
    )
    assert first["rows"][0]["sum"] == 900

    second = build_two_stage_payroll(
        uploads, ratings_by_upload, {}, month=7, stage="2", year=2026,
        stage_adjustments_by_fio={"Иванов И.И.": {"penalty": 300, "premium": 50}},
    )
    assert second["rows"][0]["penalty"] == 300
    assert second["rows"][0]["premium"] == 50
    assert second["rows"][0]["sum"] == 750
