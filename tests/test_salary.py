from app.services.ladder_groups import MONTHLY_BASE_RATE
from app.services.rating_engine import EmployeeScore
from app.services.salary import assign_salary


def _score(fio, bonus075=0, bonus2=0):
    return EmployeeScore(fio=fio, raw={"bonus075": bonus075, "bonus2": bonus2})


def test_salary_uses_previous_week_coefficient():
    results = [_score("Иванов И.И.", bonus075=100, bonus2=50)]
    assign_salary(results, {"Иванов И.И.": 1.4}, weeks_in_month=4)
    week_base = MONTHLY_BASE_RATE / 4
    assert results[0].salary == (week_base + 100 + 50) * 1.4


def test_salary_defaults_coefficient_to_one_when_no_previous_week_data():
    results = [_score("Новенький Н.Н.")]
    assign_salary(results, {}, weeks_in_month=4)
    assert results[0].salary == MONTHLY_BASE_RATE / 4


def test_salary_uses_only_this_persons_coefficient_not_others():
    results = [_score("А"), _score("Б")]
    assign_salary(results, {"А": 1.4}, weeks_in_month=4)  # "Б" отсутствует в карте
    week_base = MONTHLY_BASE_RATE / 4
    assert results[0].salary == week_base * 1.4
    assert results[1].salary == week_base * 1.0


def test_salary_respects_weeks_in_month_parameter():
    results_4 = [_score("А")]
    results_5 = [_score("А")]
    assign_salary(results_4, {}, weeks_in_month=4)
    assign_salary(results_5, {}, weeks_in_month=5)
    assert results_4[0].salary == MONTHLY_BASE_RATE / 4
    assert results_5[0].salary == MONTHLY_BASE_RATE / 5
    assert results_4[0].salary > results_5[0].salary


def test_salary_includes_bonuses_before_multiplying_by_coefficient():
    results = [_score("А", bonus075=200, bonus2=300)]
    assign_salary(results, {"А": 0.5}, weeks_in_month=4)
    week_base = MONTHLY_BASE_RATE / 4
    assert results[0].salary == (week_base + 200 + 300) * 0.5
