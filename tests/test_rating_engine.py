from app.services.rating_engine import RatingCategory, compute_ratings


def test_basic_two_category_ranking():
    categories = [
        RatingCategory(key="sales", label="Продажи", source_column="sales", weight=2, direction="desc"),
        RatingCategory(key="errors", label="Ошибки", source_column="errors", weight=1, direction="asc"),
    ]
    employees = [
        {"fio": "A", "sales": 100, "errors": 5},
        {"fio": "B", "sales": 200, "errors": 1},
        {"fio": "C", "sales": 50, "errors": 10},
    ]
    results = compute_ratings(employees, categories)
    by_fio = {r.fio: r for r in results}

    # B: sales место=1 (200 макс) *2=2 ; errors место=1 (1 мин) *1=1 ; total=3
    assert by_fio["B"].places["sales"] == 1
    assert by_fio["B"].places["errors"] == 1
    assert by_fio["B"].total_score == 3
    assert by_fio["B"].final_place == 1

    # A: sales место=2 *2=4 ; errors место=2 *1=2 ; total=6
    assert by_fio["A"].total_score == 6

    # C: sales место=3 *2=6 ; errors место=3 *1=3 ; total=9 (худший)
    assert by_fio["C"].final_place == 3


def test_ties_share_the_same_place():
    categories = [RatingCategory(key="s", label="S", source_column="s", weight=1, direction="desc")]
    employees = [{"fio": "A", "s": 10}, {"fio": "B", "s": 10}, {"fio": "C", "s": 5}]
    results = compute_ratings(employees, categories)
    by_fio = {r.fio: r for r in results}
    assert by_fio["A"].places["s"] == 1
    assert by_fio["B"].places["s"] == 1  # делят первое место
    assert by_fio["C"].places["s"] == 3  # следующее место со сдвигом


def test_na_excluded_from_final_place():
    categories = [RatingCategory(key="s", label="S", source_column="s", weight=1, direction="desc")]
    employees = [{"fio": "A", "s": 10}, {"fio": "B", "s": 0}]
    results = compute_ratings(employees, categories, na_predicate=lambda row: row["s"] == 0)
    by_fio = {r.fio: r for r in results}
    assert by_fio["A"].final_place == 1
    assert by_fio["B"].is_na is True
    assert by_fio["B"].final_place is None


def test_na_employee_with_zero_value_does_not_win_asc_category():
    """Реальный сбой на проде: ОП, которых не было в линии в этот день
    (0 обращений -> Н/О), получали место 1 по "время/контакт" (asc,
    меньше = лучше) — 0 формально наименьшее число, но означает "нет
    данных", а не "мгновенное обслуживание". Сотрудник Н/О должен
    получать место ХУЖЕ любого реального исполнителя, а не 1-е."""
    categories = [
        RatingCategory(key="time", label="Время", source_column="time", weight=1, direction="asc"),
    ]
    employees = [
        {"fio": "Реальный медленный", "c1_sum": 1000, "time": 20},
        {"fio": "Реальный быстрый", "c1_sum": 1000, "time": 5},
        {"fio": "Не было в линии", "c1_sum": 0, "time": 0},
    ]
    results = compute_ratings(employees, categories, na_predicate=lambda row: row["c1_sum"] == 0)
    by_fio = {r.fio: r for r in results}

    # Реальные исполнители ранжируются МЕЖДУ СОБОЙ, как будто "нулевого"
    # сотрудника нет вообще — их места не сдвинуты его присутствием.
    assert by_fio["Реальный быстрый"].places["time"] == 1
    assert by_fio["Реальный медленный"].places["time"] == 2
    # "Нулевой" — строго хуже обоих, а не 1-е место.
    assert by_fio["Не было в линии"].places["time"] == 3


def test_na_employee_does_not_shift_desc_category_either():
    # Для "desc"-категорий 0 у Н/О и так естественно ранжируется хуже
    # всех — исключение из пула не должно ничего ломать (тот же
    # результат, что и раньше).
    categories = [
        RatingCategory(key="sales", label="Продажи", source_column="sales", weight=1, direction="desc"),
    ]
    employees = [
        {"fio": "A", "c1_sum": 1000, "sales": 100},
        {"fio": "B", "c1_sum": 1000, "sales": 50},
        {"fio": "C", "c1_sum": 0, "sales": 0},
    ]
    results = compute_ratings(employees, categories, na_predicate=lambda row: row["c1_sum"] == 0)
    by_fio = {r.fio: r for r in results}
    assert by_fio["A"].places["sales"] == 1
    assert by_fio["B"].places["sales"] == 2
    assert by_fio["C"].places["sales"] == 3
