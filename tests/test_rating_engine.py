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
