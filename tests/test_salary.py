from app.services.rating_engine import EmployeeScore
from app.services.salary import DEFAULT_HOURS_NORM, DEFAULT_MONTHLY_BASE_RATE, assign_salary


def _score(fio, work_hours, bonus075=0, bonus2=0, is_na=False, supervisor="Супервайзер - Иванов И.И."):
    return EmployeeScore(
        fio=fio,
        raw={"work_hours": work_hours, "bonus075": bonus075, "bonus2": bonus2, "supervisor": supervisor},
        is_na=is_na,
    )


def test_salary_uses_previous_week_coefficient():
    # Коэффициент умножает ТОЛЬКО сумму бонусов, НЕ часовую ставку.
    results = [_score("Иванов И.И.", work_hours=40, bonus075=100, bonus2=50)]
    assign_salary(results, {"Иванов И.И.": 1.4}, hours_norm=160, monthly_base_rate=40000)
    week_base = (40000 / 160) * 40
    assert results[0].salary == week_base + (100 + 50) * 1.4


def test_salary_defaults_coefficient_to_one_when_no_previous_week_data():
    results = [_score("Новенький Н.Н.", work_hours=40)]
    assign_salary(results, {}, hours_norm=160, monthly_base_rate=40000)
    assert results[0].salary == (40000 / 160) * 40


def test_salary_uses_only_this_persons_coefficient_not_others():
    results = [_score("А", work_hours=40), _score("Б", work_hours=40)]
    assign_salary(results, {"А": 1.4}, hours_norm=160, monthly_base_rate=40000)  # "Б" отсутствует в карте
    week_base = (40000 / 160) * 40
    assert results[0].salary == week_base  # bonus=0 у обоих -> коэффициент ни на что не влияет здесь
    assert results[1].salary == week_base


def test_salary_scales_with_hours_norm():
    results_norm160 = [_score("А", work_hours=40)]
    results_norm159 = [_score("А", work_hours=40)]
    assign_salary(results_norm160, {}, hours_norm=160, monthly_base_rate=40000)
    assign_salary(results_norm159, {}, hours_norm=159, monthly_base_rate=40000)
    assert results_norm160[0].salary == (40000 / 160) * 40
    assert results_norm159[0].salary == (40000 / 159) * 40
    assert results_norm159[0].salary > results_norm160[0].salary  # меньше норма -> выше ставка/час


def test_salary_scales_with_work_hours():
    results = [_score("А", work_hours=20), _score("Б", work_hours=40)]
    assign_salary(results, {}, hours_norm=160, monthly_base_rate=40000)
    assert results[1].salary == results[0].salary * 2  # вдвое больше часов -> вдвое больше базы (bonus=0)


def test_coefficient_multiplies_only_bonuses_not_hourly_base():
    # Поправка от заказчика: было (база+бонусы)×коэфф., стало
    # база + (бонусы)×коэфф. — часовая ставка коэффициентом НЕ умножается.
    results = [_score("А", work_hours=40, bonus075=200, bonus2=300)]
    assign_salary(results, {"А": 1.4}, hours_norm=160, monthly_base_rate=40000)
    week_base = (40000 / 160) * 40  # = 10000
    expected = week_base + (200 + 300) * 1.4  # 10000 + 700 = 10700
    wrong_old_style = (week_base + 200 + 300) * 1.4  # старая (неверная для новой формулы) = 14700
    assert results[0].salary == expected
    assert results[0].salary != wrong_old_style


def test_salary_includes_bonuses_multiplied_by_coefficient():
    results = [_score("А", work_hours=40, bonus075=200, bonus2=300)]
    assign_salary(results, {"А": 0.5}, hours_norm=160, monthly_base_rate=40000)
    week_base = (40000 / 160) * 40
    assert results[0].salary == week_base + (200 + 300) * 0.5


def test_salary_is_none_when_work_hours_missing():
    # Колонки "Рабочее время, ч" не было в файле (или пустая ячейка для
    # конкретного человека) — ЗП честно посчитать нельзя: не 0 часов
    # (это была бы настоящая заниженная ЗП), а НЕИЗВЕСТНО, поэтому salary
    # целиком None, а не просто без базы.
    results = [_score("Без часов", work_hours=None, bonus075=100, bonus2=50)]
    assign_salary(results, {"Без часов": 1.4}, hours_norm=160, monthly_base_rate=40000)
    assert results[0].salary is None


def test_salary_defaults_match_documented_values():
    results = [_score("А", work_hours=DEFAULT_HOURS_NORM)]
    assign_salary(results, {})
    assert results[0].salary == DEFAULT_MONTHLY_BASE_RATE


# ---------- Н/О этой недели никогда не наказывается заниженным коэффициентом ----------
# По прямому запросу заказчика: если сотрудник Н/О ЭТОЙ недели (любая
# причина — отпуск, больничный, тренер, нулевые продажи, новичок), а на
# ПРОШЛОЙ неделе у него был коэффициент < 1.0 (низкий тир ЛГ), для ЗП этой
# недели он floor'ится до 1.0, а не применяется как есть.

def test_na_employee_low_previous_coefficient_is_floored_to_one():
    results = [_score("Отпускник О.", work_hours=40, bonus075=200, bonus2=300, is_na=True)]
    assign_salary(results, {"Отпускник О.": 0.7}, hours_norm=160, monthly_base_rate=40000)
    week_base = (40000 / 160) * 40
    assert results[0].salary == week_base + (200 + 300) * 1.0
    assert results[0].salary != week_base + (200 + 300) * 0.7


def test_non_na_employee_low_previous_coefficient_is_used_as_is():
    # Тот же низкий коэффициент 0.7, но сотрудник НЕ Н/О этой недели —
    # floor не применяется, используется реальный коэффициент.
    results = [_score("Обычный О.", work_hours=40, bonus075=200, bonus2=300, is_na=False)]
    assign_salary(results, {"Обычный О.": 0.7}, hours_norm=160, monthly_base_rate=40000)
    week_base = (40000 / 160) * 40
    assert results[0].salary == week_base + (200 + 300) * 0.7


def test_na_employee_high_previous_coefficient_is_not_lowered():
    # Floor работает только СНИЗУ — хороший коэффициент (>=1.0) не трогаем.
    results = [_score("Новичков Н.", work_hours=40, bonus075=200, bonus2=300, is_na=True)]
    assign_salary(results, {"Новичков Н.": 1.4}, hours_norm=160, monthly_base_rate=40000)
    week_base = (40000 / 160) * 40
    assert results[0].salary == week_base + (200 + 300) * 1.4


def test_na_employee_without_previous_period_data_still_defaults_to_one():
    results = [_score("Без истории Б.", work_hours=40, bonus075=200, bonus2=300, is_na=True)]
    assign_salary(results, {}, hours_norm=160, monthly_base_rate=40000)
    week_base = (40000 / 160) * 40
    assert results[0].salary == week_base + (200 + 300) * 1.0


# ---------- "ПП"/"Увеличители" (бывшая "Выходы на Пики"): часовой ставки нет вообще ----------
# По прямому запросу заказчика: для групп "операторы без супервизора
# [Пики-ПП]" и "операторы без супервизора [Пики-Увеличители]" (раньше —
# одна общая группа "Пики", разделена на две отдельные, но формула ЗП
# для обеих осталась той же) ЗП = (бонус075 + бонус2) × коэффициент —
# часовая ставка не компонент формулы вообще (не 0, а отсутствует),
# work_hours игнорируется полностью, даже если заполнено. Все остальные
# группы (включая "Регион УК") считаются как обычно, с часовой ставкой.

PEAKS_SUPERVISOR = "операторы без супервизора [Пики-ПП]"
PEAKS_UVELICHITELI_SUPERVISOR = "операторы без супервизора [Пики-Увеличители]"


def test_peaks_group_salary_ignores_hourly_rate_entirely():
    results = [
        _score("Пиковый П.", work_hours=40, bonus075=200, bonus2=300, supervisor=PEAKS_SUPERVISOR),
    ]
    assign_salary(results, {"Пиковый П.": 1.4}, hours_norm=160, monthly_base_rate=40000)
    assert results[0].salary == (200 + 300) * 1.4  # БЕЗ week_base


def test_peaks_group_salary_ignores_work_hours_even_when_filled():
    # work_hours=999 намеренно большое — если бы часовая ставка каким-то
    # образом участвовала, ЗП была бы огромной. Она игнорируется целиком.
    with_hours = [_score("А", work_hours=999, bonus075=100, bonus2=50, supervisor=PEAKS_SUPERVISOR)]
    without_hours = [_score("А", work_hours=None, bonus075=100, bonus2=50, supervisor=PEAKS_SUPERVISOR)]
    assign_salary(with_hours, {"А": 1.0}, hours_norm=160, monthly_base_rate=40000)
    assign_salary(without_hours, {"А": 1.0}, hours_norm=160, monthly_base_rate=40000)
    assert with_hours[0].salary == (100 + 50) * 1.0
    assert with_hours[0].salary == without_hours[0].salary  # work_hours ни на что не влияет


def test_peaks_group_salary_is_not_none_when_work_hours_missing():
    # Для обычных групп work_hours=None -> salary=None. Для Пиков это
    # правило не применяется (часы для них вообще не нужны).
    results = [_score("Б", work_hours=None, bonus075=100, bonus2=50, supervisor=PEAKS_SUPERVISOR)]
    assign_salary(results, {"Б": 1.4}, hours_norm=160, monthly_base_rate=40000)
    assert results[0].salary == (100 + 50) * 1.4
    assert results[0].salary is not None


def test_uvelichiteli_group_salary_also_ignores_hourly_rate():
    # Вторая бывшая "Пики"-подгруппа — та же формула, тот же признак
    # PEAKS_GROUP_RE, отдельная проверка на случай регрессии одной из двух.
    results = [
        _score("Увеличитель У.", work_hours=40, bonus075=200, bonus2=300, supervisor=PEAKS_UVELICHITELI_SUPERVISOR),
    ]
    assign_salary(results, {"Увеличитель У.": 1.4}, hours_norm=160, monthly_base_rate=40000)
    assert results[0].salary == (200 + 300) * 1.4  # БЕЗ week_base


def test_non_peaks_group_salary_still_uses_hourly_rate():
    # Контроль: "Регион УК" (тот же "операторы без супервизора", но БЕЗ
    # суффикса " [Пики-ПП]"/" [Пики-Увеличители]") и обычные группы —
    # формула не меняется.
    region_uk = [_score("В", work_hours=40, bonus075=200, bonus2=300, supervisor="операторы без супервизора")]
    regular = [_score("Г", work_hours=40, bonus075=200, bonus2=300, supervisor="Супервайзер - Петров П.П.")]
    assign_salary(region_uk, {"В": 1.4}, hours_norm=160, monthly_base_rate=40000)
    assign_salary(regular, {"Г": 1.4}, hours_norm=160, monthly_base_rate=40000)
    week_base = (40000 / 160) * 40
    assert region_uk[0].salary == week_base + (200 + 300) * 1.4
    assert regular[0].salary == week_base + (200 + 300) * 1.4


def test_peaks_group_respects_na_coefficient_floor():
    # Пики — не исключение из floor-правила (Н/О этой недели -> коэфф >= 1.0).
    results = [
        _score("Отпускник Пиков", work_hours=40, bonus075=200, bonus2=300, is_na=True, supervisor=PEAKS_SUPERVISOR),
    ]
    assign_salary(results, {"Отпускник Пиков": 0.7}, hours_norm=160, monthly_base_rate=40000)
    assert results[0].salary == (200 + 300) * 1.0
