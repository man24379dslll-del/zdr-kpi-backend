from app.services.payroll import (
    build_flexible_payroll,
    filter_uploads_for_periods,
    format_payroll_periods_text,
    make_periods_key,
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


def test_build_flexible_payroll_sums_net_salary_across_weeks():
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

    result = build_flexible_payroll(
        uploads, ratings_by_upload, penalties_by_upload, periods=["7-1", "7-2"], year=2026, hours_norm=0,
    )

    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["fio"] == "Иванов И.И."
    assert row["sum"] == (1000 - 100) + (1200 - 0)
    assert row["penalty_sum"] == 100
    assert row["comment"] == "Штраф удержан: 100 ₽"
    assert result["periods"] == ["7-1", "7-2"]
    assert result["periods_key"] == "7-1,7-2"
    assert result["period_label_text"] == "7-1, 7-2 (2026)"
    # Разбивка по неделям — сумма элементов равна row["sum"] (adjustments
    # по умолчанию нулевые, hours_norm=0 без work_hours -> overtime_pay=0)
    assert row["weeks"] == [
        {"period_label": "7-1", "sum": 1000 - 100},
        {"period_label": "7-2", "sum": 1200 - 0},
    ]
    assert sum(w["sum"] for w in row["weeks"]) == row["sum"]


def test_build_flexible_payroll_excludes_novices_and_null_salary():
    uploads = [{"id": "u7-1", "period_label": "7-1"}]
    ratings_by_upload = {
        "u7-1": [
            {"fio": "Новичков Н.Н.", "supervisor": "А", "status": "Новичок", "is_novice": True, "salary": 500},
            {"fio": "БезЗарплаты Б.Б.", "supervisor": "А", "status": "Профи", "is_novice": False, "salary": None},
            {"fio": "Обычный О.О.", "supervisor": "А", "status": "Профи", "is_novice": False, "salary": 900},
        ],
    }
    result = build_flexible_payroll(uploads, ratings_by_upload, {}, periods=["7-1"], year=2026, hours_norm=0)
    fios = {r["fio"] for r in result["rows"]}
    assert fios == {"Обычный О.О."}


def test_build_flexible_payroll_no_comment_without_penalty():
    uploads = [{"id": "u7-1", "period_label": "7-1"}]
    ratings_by_upload = {"u7-1": [{"fio": "А. А.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 700}]}
    result = build_flexible_payroll(uploads, ratings_by_upload, {}, periods=["7-1"], year=2026, hours_norm=0)
    assert result["rows"][0]["comment"] is None


def test_build_flexible_payroll_sorted_by_display_group_name_then_fio():
    uploads = [{"id": "u7-1", "period_label": "7-1"}]
    ratings_by_upload = {
        "u7-1": [
            {"fio": "Яковлев Я.Я.", "supervisor": "Супервайзер - Смирнов С.С.", "status": "Профи", "is_novice": False, "salary": 100},
            {"fio": "Антонов А.А.", "supervisor": "Супервайзер - Смирнов С.С.", "status": "Профи", "is_novice": False, "salary": 100},
            {"fio": "ЗДР Борисов Б.Б.", "supervisor": "операторы без супервизора", "status": "Профи", "is_novice": False, "salary": 100},
        ],
    }
    result = build_flexible_payroll(uploads, ratings_by_upload, {}, periods=["7-1"], year=2026, hours_norm=0)
    fios_in_order = [r["fio"] for r in result["rows"]]
    # display_group_name: "операторы без супервизора" -> "Регион УК" (кириллица
    # Р), "Супервайзер - Смирнов С.С." -> очищенное "Смирнов С.С." (кириллица
    # С) — "Регион УК" идёт раньше по алфавиту, внутри группы — по fio
    assert fios_in_order == ["ЗДР Борисов Б.Б.", "Антонов А.А.", "Яковлев Я.Я."]


# --- разбивка по неделям ("weeks") ---

def test_weeks_breakdown_has_entries_for_every_marked_period():
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
    result = build_flexible_payroll(uploads, ratings_by_upload, {}, periods=["7-3", "7-4", "7-5"], year=2026, hours_norm=0)
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
    result = build_flexible_payroll(uploads, ratings_by_upload, {}, periods=["7-3", "7-4"], year=2026, hours_norm=0)
    row = result["rows"][0]
    assert row["weeks"] == [{"period_label": "7-3", "sum": 1000}]


def test_weeks_breakdown_sorted_chronologically_regardless_of_upload_order():
    uploads = [{"id": "u8-1", "period_label": "8-1"}, {"id": "u7-5", "period_label": "7-5"}]  # заведомо не по порядку
    ratings_by_upload = {
        "u8-1": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1100}],
        "u7-5": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000}],
    }
    result = build_flexible_payroll(uploads, ratings_by_upload, {}, periods=["8-1", "7-5"], year=2026, hours_norm=0)
    row = result["rows"][0]
    # 7-5 (месяц 7) идёт раньше 8-1 (месяц 8) — межмесячная хронология
    assert [w["period_label"] for w in row["weeks"]] == ["7-5", "8-1"]


def test_weeks_breakdown_unaffected_by_adjustment():
    # Штраф/премия применяются к итогу ("sum"), НЕ к конкретной неделе —
    # разбивка "weeks" отражает только по-недельные суммы, сумма её
    # элементов НЕ обязана совпадать с итоговым "sum" после корректировки.
    uploads = [{"id": "u7-3", "period_label": "7-3"}]
    ratings_by_upload = {"u7-3": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000}]}
    result = build_flexible_payroll(
        uploads, ratings_by_upload, {}, periods=["7-3"], year=2026,
        adjustments_by_fio={"Иванов И.И.": {"penalty": 500, "premium": 0}},
        hours_norm=0,  # нейтрализует доплату за часы — этот тест не про неё
    )
    row = result["rows"][0]
    assert row["weeks"] == [{"period_label": "7-3", "sum": 1000}]
    assert row["sum"] == 500  # 1000 - 500 (корректировка), не в разбивке


# --- штраф/премия/оплата за смены (payroll_stage_adjustments) ---

def test_adjustment_applies_regardless_of_how_many_periods_are_marked():
    uploads = [
        {"id": "u7-3", "period_label": "7-3"},
        {"id": "u7-4", "period_label": "7-4"},
        {"id": "u7-5", "period_label": "7-5"},
    ]
    ratings_by_upload = {
        u["id"]: [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000}]
        for u in uploads
    }
    adjustments = {"Иванов И.И.": {"penalty": 500, "premium": 200}}

    result = build_flexible_payroll(
        uploads, ratings_by_upload, {}, periods=["7-3", "7-4", "7-5"], year=2026,
        adjustments_by_fio=adjustments,
        hours_norm=0,  # нейтрализует доплату за часы — этот тест не про неё
    )
    row = result["rows"][0]
    assert row["penalty"] == 500
    assert row["premium"] == 200
    assert row["sum"] == 3000 - 500 + 200


def test_adjustment_applies_even_for_a_single_marked_week():
    # Раньше корректировки применялись ТОЛЬКО к stage="2" (фикс. 3 недели)
    # — теперь понятия "этап" нет вообще, корректировка работает для
    # любого количества отмеченных недель, включая одну.
    uploads = [{"id": "u7-1", "period_label": "7-1"}]
    ratings_by_upload = {"u7-1": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000}]}
    adjustments = {"Иванов И.И.": {"penalty": 500, "premium": 200}}

    result = build_flexible_payroll(
        uploads, ratings_by_upload, {}, periods=["7-1"], year=2026,
        adjustments_by_fio=adjustments, hours_norm=0,
    )
    row = result["rows"][0]
    assert row["penalty"] == 500
    assert row["premium"] == 200
    assert row["sum"] == 1000 - 500 + 200


def test_adjustment_defaults_to_zero_when_no_record():
    uploads = [{"id": "u7-3", "period_label": "7-3"}]
    ratings_by_upload = {"u7-3": [{"fio": "Без корректировки Б.Б.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 500}]}
    result = build_flexible_payroll(
        uploads, ratings_by_upload, {}, periods=["7-3"], year=2026,
        adjustments_by_fio={}, hours_norm=0,
    )
    row = result["rows"][0]
    assert row["penalty"] == 0
    assert row["premium"] == 0
    assert row["shift_pay"] == 0
    assert row["overtime_pay"] == 0
    assert row["sum"] == 500


def test_adjustment_reflects_latest_saved_value_after_upsert():
    # Эмулирует апсерт: PUT /payroll/adjustment перезаписывает запись по
    # (fio, periods_key) — второй расчёт с обновлённым значением должен
    # показать НОВОЕ значение, не накопленную сумму двух сохранений.
    uploads = [{"id": "u7-3", "period_label": "7-3"}]
    ratings_by_upload = {"u7-3": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000}]}

    first = build_flexible_payroll(
        uploads, ratings_by_upload, {}, periods=["7-3"], year=2026,
        adjustments_by_fio={"Иванов И.И.": {"penalty": 100, "premium": 0}},
        hours_norm=0,
    )
    assert first["rows"][0]["sum"] == 900

    second = build_flexible_payroll(
        uploads, ratings_by_upload, {}, periods=["7-3"], year=2026,
        adjustments_by_fio={"Иванов И.И.": {"penalty": 300, "premium": 50}},
        hours_norm=0,
    )
    assert second["rows"][0]["penalty"] == 300
    assert second["rows"][0]["premium"] == 50
    assert second["rows"][0]["sum"] == 750


# --- доплата за часы (overtime_pay) и оплата за смены (shift_pay) ---

def test_overtime_pay_positive_when_hours_exceed_norm():
    uploads = [{"id": "u7-3", "period_label": "7-3"}]
    ratings_by_upload = {
        "u7-3": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000, "work_hours": 45}],
    }
    result = build_flexible_payroll(
        uploads, ratings_by_upload, {}, periods=["7-3"], year=2026, hours_norm=40, overtime_rate=150,
    )
    row = result["rows"][0]
    assert row["overtime_pay"] == (45 - 40) * 150  # = 750
    assert row["sum"] == 1000 + 750


def test_overtime_pay_clamped_to_zero_when_hours_below_norm():
    # Недоработку по часам людям в минус не ставим — доплата просто 0,
    # itog не уменьшается (штраф за недоработку — отдельная ручная
    # история через поле "Штраф", не автоматика по часам).
    uploads = [{"id": "u7-3", "period_label": "7-3"}]
    ratings_by_upload = {
        "u7-3": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000, "work_hours": 30}],
    }
    result = build_flexible_payroll(
        uploads, ratings_by_upload, {}, periods=["7-3"], year=2026, hours_norm=40, overtime_rate=150,
    )
    row = result["rows"][0]
    assert row["overtime_pay"] == 0
    assert row["sum"] == 1000


def test_overtime_pay_zero_when_hours_exactly_match_norm():
    uploads = [{"id": "u7-3", "period_label": "7-3"}]
    ratings_by_upload = {
        "u7-3": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000, "work_hours": 40}],
    }
    result = build_flexible_payroll(
        uploads, ratings_by_upload, {}, periods=["7-3"], year=2026, hours_norm=40, overtime_rate=150,
    )
    row = result["rows"][0]
    assert row["overtime_pay"] == 0
    assert row["sum"] == 1000


def test_overtime_pay_sums_work_hours_across_marked_weeks_no_extra_hours_field():
    # hours_norm НЕ масштабируется по числу недель (см. докстринг модуля) —
    # сравнивается с СУММОЙ часов за все отмеченные недели как есть.
    # Ручного "extra_hours" в формуле больше нет вообще.
    uploads = [{"id": "u7-3", "period_label": "7-3"}, {"id": "u7-4", "period_label": "7-4"}]
    ratings_by_upload = {
        "u7-3": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 500, "work_hours": 20}],
        "u7-4": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 500, "work_hours": 25}],
    }
    result = build_flexible_payroll(
        uploads, ratings_by_upload, {}, periods=["7-3", "7-4"], year=2026, hours_norm=40, overtime_rate=150,
    )
    row = result["rows"][0]
    # 20 + 25 (по неделям) - 40 (норма, не масштабирована) = 5 -> 5*150 = 750
    assert row["overtime_pay"] == 750
    assert "extra_hours" not in row


def test_overtime_pay_works_across_periods_from_different_months():
    uploads = [{"id": "u7-5", "period_label": "7-5"}, {"id": "u8-1", "period_label": "8-1"}]
    ratings_by_upload = {
        "u7-5": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 500, "work_hours": 20}],
        "u8-1": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 500, "work_hours": 20}],
    }
    result = build_flexible_payroll(
        uploads, ratings_by_upload, {}, periods=["7-5", "8-1"], year=2026, hours_norm=30, overtime_rate=150,
    )
    row = result["rows"][0]
    assert row["overtime_pay"] == (40 - 30) * 150  # = 1500


def test_shift_pay_is_a_manual_total_not_a_rate_times_count_formula():
    # Ставка за смену разная у разных людей — оплата за смены это готовая
    # вручную введённая сумма, не считается формулой внутри системы.
    uploads = [{"id": "u7-3", "period_label": "7-3"}]
    ratings_by_upload = {
        "u7-3": [
            {"fio": "А. А.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000, "work_hours": 40},
            {"fio": "Б. Б.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000, "work_hours": 40},
        ],
    }
    result = build_flexible_payroll(
        uploads, ratings_by_upload, {}, periods=["7-3"], year=2026,
        adjustments_by_fio={
            "А. А.": {"shift_pay": 2000},
            "Б. Б.": {"shift_pay": 3500},
        },
        hours_norm=40, overtime_rate=150,
    )
    by_fio = {r["fio"]: r for r in result["rows"]}
    assert by_fio["А. А."]["shift_pay"] == 2000
    assert by_fio["А. А."]["sum"] == 1000 + 2000  # overtime_pay=0, (40-40)*150
    assert by_fio["Б. Б."]["shift_pay"] == 3500
    assert by_fio["Б. Б."]["sum"] == 1000 + 3500


def test_shift_count_is_automatic_from_file_and_informational_only():
    # shift_count больше не ручное поле корректировки — это сумма
    # kpi_ratings.shift_count по отмеченным неделям, и на "sum" не влияет.
    uploads = [{"id": "u7-3", "period_label": "7-3"}, {"id": "u7-4", "period_label": "7-4"}]
    ratings_by_upload = {
        "u7-3": [{"fio": "А. А.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 500, "shift_count": 2}],
        "u7-4": [{"fio": "А. А.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 500, "shift_count": 3}],
    }
    result = build_flexible_payroll(
        uploads, ratings_by_upload, {}, periods=["7-3", "7-4"], year=2026, hours_norm=0,
    )
    row = result["rows"][0]
    assert row["shift_count"] == 5  # 2 + 3, автосумма из файла
    assert row["sum"] == 1000  # shift_count не входит в формулу


def test_overtime_and_shift_use_default_rate_and_hours_norm_when_not_passed():
    # По умолчанию (без явных hours_norm/overtime_rate) используются
    # DEFAULT_HOURS_NORM (160, тот же параметр, что и в salary.py) и
    # DEFAULT_OVERTIME_RATE (150).
    from app.services.payroll import DEFAULT_OVERTIME_RATE
    from app.services.salary import DEFAULT_HOURS_NORM

    uploads = [{"id": "u7-3", "period_label": "7-3"}]
    ratings_by_upload = {
        "u7-3": [{"fio": "Иванов И.И.", "supervisor": "С", "status": "Профи", "is_novice": False, "salary": 1000, "work_hours": DEFAULT_HOURS_NORM + 1}],
    }
    result = build_flexible_payroll(uploads, ratings_by_upload, {}, periods=["7-3"], year=2026)
    row = result["rows"][0]
    assert row["overtime_pay"] == 1 * DEFAULT_OVERTIME_RATE
