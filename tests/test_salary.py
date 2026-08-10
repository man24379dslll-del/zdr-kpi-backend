from app.services.rating_engine import EmployeeScore
from app.services.salary import DEFAULT_HOURS_NORM, DEFAULT_MONTHLY_BASE_RATE, assign_salary


def _score(fio, work_hours, bonus075=0, bonus2=0):
    return EmployeeScore(fio=fio, raw={"work_hours": work_hours, "bonus075": bonus075, "bonus2": bonus2})


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
