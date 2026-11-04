"""
Показатели групп сектора для рейтинга супервайзеров в рабочем окне
супервайзера (services/supervisor_stats.py + GET /ratings/sector-supervisor-stats).
"""
import pytest
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user
from app.main import app
from app.routers import ratings
from app.services.group_naming import SECTOR_2_SUPERVISORS, SECTOR_3_SUPERVISORS
from app.services.supervisor_stats import STATS_COLUMNS, sector_group_stats

G1A = "Супервайзер - Иванов Иван Иванович"           # Сектор 1
G1B = "Супервайзер - Петрова Мария Сергеевна"       # Сектор 1
G2 = sorted(SECTOR_2_SUPERVISORS)[0]                 # Сектор 2
G2B = sorted(SECTOR_2_SUPERVISORS)[1]
G3 = sorted(SECTOR_3_SUPERVISORS)[0]                 # Сектор 3


def _row(fio, supervisor, c1=100.0, *, status="Профи", is_na=False, is_novice=False, c1_sum=1000, channel="radio", **over):
    row = {
        "fio": fio, "supervisor": supervisor, "status": status, "is_na": is_na, "is_novice": is_novice, "channel": channel,
        "c1_sum": c1_sum, "c1_check": 10.0, "c1_conv": 20.0, "c1_per_contact": c1, "c1_cards": 5,
        "lk_sum": 0, "lk_check": 0, "lk_conv": 0, "lk_per_contact": 0, "lk_cards": 0,
        "ch_sum": 500, "ch_check": 50.0, "ch_conv": 15.0, "ch_per_contact": c1 * 2, "ch_cards": 3,
        "time_per_contact": 5.0, "errors_pct": 1.0,
    }
    row.update(over)
    return row


def _by_sup(stats):
    return {s["supervisor"]: s for s in stats}


# ---------- агрегаты ----------

def test_group_aggregates_are_averages_and_sums_over_evaluated_people():
    rows = [
        _row("А", G1A, c1=100, time_per_contact=4.0, errors_pct=2.0),
        _row("Б", G1A, c1=200, time_per_contact=6.0, errors_pct=0.0, c1_sum=3000, c1_cards=10),
        _row("Н/О", G1A, c1=9999, is_na=True),                        # не оценён — в средних нет, в n_total есть
    ]
    g = _by_sup(sector_group_stats(rows, 1))[G1A]
    assert (g["n_evaluated"], g["n_total"]) == (2, 3)
    assert g["c1_pc"] == 150 and g["c1_sum"] == 4000 and g["c1_cards"] == 15
    assert g["time"] == 5.0 and g["errors_pct"] == 1.0
    assert g["ch_pc"] == 300 and g["ch_sum"] == 1000 and g["channel"] == "radio"
    assert g["lk_pc"] == 0 and g["lk_sum"] == 0


def test_none_values_count_as_zero_like_the_frontend():
    rows = [_row("А", G1A, c1=100, c1_cards=None, lk_per_contact=None), _row("Б", G1A, c1=200, c1_cards=4)]
    g = _by_sup(sector_group_stats(rows, 1))[G1A]
    assert g["c1_cards"] == 4 and g["lk_pc"] == 0


def test_sector_filter_excludes_other_sectors_and_service_groups():
    rows = [
        _row("И", G1A), _row("К", G3), _row("Б", G2),
        _row("ЗДР", "операторы без супервизора"), _row("ПП", "операторы без супервизора [Пики-ПП]"),
        _row("Васько", "Супервайзер - Васько Иван"),
    ]
    assert set(_by_sup(sector_group_stats(rows, 1))) == {G1A}              # Сектор 3 в сектор 1 не входит
    assert set(_by_sup(sector_group_stats(rows, 2))) == {G2}
    assert set(_by_sup(sector_group_stats(rows, 3))) == {G3}


def test_sector_1_evaluates_by_na_flag_and_novice_duplicates_are_ignored():
    rows = [
        _row("Новичок", G1A, status="Новичок", is_na=True),                 # основная строка Н/О
        _row("Новичок", G1A, status="Новичок", is_novice=True, c1=9999),    # дубль общего списка — не сотрудник группы
        _row("Профи", G1A, c1=100),
    ]
    g = _by_sup(sector_group_stats(rows, 1))[G1A]
    assert (g["n_evaluated"], g["n_total"], g["c1_pc"]) == (1, 2, 100)


def test_sectors_2_and_3_evaluate_novices_but_not_trainers_vacation_or_zero_sales():
    rows = [
        _row("Новичок", G2, c1=100, status="Новичок", is_na=True),          # в секторе 2 новички оцениваются (is_na не смотрим)
        _row("Профи", G2, c1=200),
        _row("Тренер", G2, c1=9999, status="Тренер"),
        _row("Отпуск", G2, c1=9999, status="Отпуск"),
        _row("Больничный", G2, c1=9999, status="Больничный"),
        _row("Руководитель", G2, c1=9999, status="руководитель"),
        _row("Без продаж", G2, c1=9999, c1_sum=0),
    ]
    g = _by_sup(sector_group_stats(rows, 2))[G2]
    assert (g["n_evaluated"], g["n_total"]) == (2, 7) and g["c1_pc"] == 150


def test_group_without_evaluated_people_is_not_listed():
    rows = [_row("Н/О", G1A, is_na=True), _row("Оценён", G1B)]
    assert set(_by_sup(sector_group_stats(rows, 1))) == {G1B}


def test_channel_is_taken_from_the_first_evaluated_row():
    rows = [_row("Н/О", G1A, is_na=True, channel="radio"), _row("А", G1A, channel="inet")]
    assert _by_sup(sector_group_stats(rows, 1))[G1A]["channel"] == "inet"
    assert _by_sup(sector_group_stats([_row("А", G1A, channel=None)], 1))[G1A]["channel"] == "radio"


def test_output_has_no_person_names_and_no_money():
    rows = [_row("Секретное Имя", G1A, salary=9999, bonus075=11, bonus2=22, coefficient=1.3, tier=2, work_hours=40)]
    text = str(sector_group_stats(rows, 1))
    for forbidden in ("Секретное", "fio", "salary", "bonus", "coefficient", "tier", "work_hours", "9999"):
        assert forbidden not in text
    for column in ("fio", "salary", "bonus075", "coefficient", "tier", "work_hours"):
        assert column not in STATS_COLUMNS.split(",")


# ---------- эндпоинт ----------

class FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def get(self, table, params=None):
        assert table == "kpi_ratings"
        self.calls.append(dict(params))
        offset, limit = int(params["offset"]), int(params["limit"])
        return self.rows[offset:offset + limit]


def _user(role="supervisor", names=None):
    return CurrentUser(access_token="t", user_id="u", email="e@e.com", role=role, supervisor_names=names, display_name="T")


@pytest.fixture
def api(monkeypatch):
    def make(user, fake):
        app.dependency_overrides[get_current_user] = lambda: user
        monkeypatch.setattr(ratings, "as_service", lambda: fake)
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


ROWS = [_row("И", G1A), _row("П", G1B), _row("Б1", G2), _row("Б2", G2B), _row("К", G3)]


def test_supervisor_gets_stats_of_all_groups_of_own_sector_only(api):
    fake = FakeClient(ROWS)
    r = api(_user("supervisor", [G2]), fake).get("/ratings/sector-supervisor-stats", params={"upload_id": "u1"})
    assert r.status_code == 200
    body = r.json()
    assert [s["sector"] for s in body["sectors"]] == [2]
    assert {s["supervisor"] for s in body["sectors"][0]["stats"]} == {G2, G2B}      # коллеги по сектору — да, чужие сектора — нет
    # читаются только нужные колонки (без ФИО), страницами и по порядку
    assert fake.calls[0]["select"] == STATS_COLUMNS and "fio" not in fake.calls[0]["select"]
    assert fake.calls[0]["order"] == "id.asc"


def test_supervisor_of_sector_1_sees_only_sector_1_groups(api):
    r = api(_user("supervisor", [G1A]), FakeClient(ROWS)).get("/ratings/sector-supervisor-stats", params={"upload_id": "u1"})
    body = r.json()
    assert [s["sector"] for s in body["sectors"]] == [1] and body["sectors"][0]["name"].startswith("Сектор №1")
    assert {s["supervisor"] for s in body["sectors"][0]["stats"]} == {G1A, G1B}


def test_supervisor_with_groups_in_two_sectors_gets_both(api):
    r = api(_user("supervisor", [G1A, G3]), FakeClient(ROWS)).get("/ratings/sector-supervisor-stats", params={"upload_id": "u1"})
    assert [s["sector"] for s in r.json()["sectors"]] == [1, 3]


def test_sector_head_gets_own_sector(api):
    r = api(_user("supervisor", sorted(SECTOR_3_SUPERVISORS)), FakeClient(ROWS)).get("/ratings/sector-supervisor-stats", params={"upload_id": "u1"})
    assert [s["sector"] for s in r.json()["sectors"]] == [3]


def test_non_supervisors_and_profiles_without_groups_are_forbidden(api):
    for user in (_user("admin"), _user("manager"), _user("supervisor", None), _user("supervisor", [])):
        r = api(user, FakeClient(ROWS)).get("/ratings/sector-supervisor-stats", params={"upload_id": "u1"})
        assert r.status_code == 403


def test_endpoint_reads_all_pages(api):
    rows = [_row(f"И{i}", G1A) for i in range(2300)]
    fake = FakeClient(rows)
    r = api(_user("supervisor", [G1A]), fake).get("/ratings/sector-supervisor-stats", params={"upload_id": "u1"})
    assert r.json()["sectors"][0]["stats"][0]["n_total"] == 2300
    assert [c["offset"] for c in fake.calls] == ["0", "1000", "2000"]
