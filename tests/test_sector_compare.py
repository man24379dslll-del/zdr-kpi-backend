"""
Сравнение секторов/супервайзеров/операторов (services/sector_compare.py) и
GET /dashboards/sectors: единая формула с фиксированными весами, сырые
метрики, без денег, доступ только админу/менеджеру/руководителям секторов.
"""
import pytest
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user
from app.main import app
from app.routers import dashboards as dashboards_router
from app.services.group_naming import SECTOR_2_SUPERVISORS, SECTOR_3_SUPERVISORS
from app.services.sector_compare import (
    UNIFIED_WEIGHTS_DUAL,
    UNIFIED_WEIGHTS_LEGACY,
    build_sector_comparison,
    special_supervisor_label,
)

G1 = "Супервайзер - Иванов Иван Иванович"           # Сектор 1
G1B = "Супервайзер - Петрова Мария Сергеевна"       # Сектор 1
G2 = sorted(SECTOR_2_SUPERVISORS)[0]                 # Сектор 2
G3 = sorted(SECTOR_3_SUPERVISORS)[0]                 # Сектор 3


def _row(fio, supervisor, c1=100.0, radio=0.0, inet=0.0, time=5.0, errors=1.0, *, status="Профи",
         is_novice=False, is_na=False, radio_cards=None, inet_cards=None, radio_conv=10.0, inet_conv=10.0,
         dual=True, **extra):
    """Строка kpi_ratings. radio/inet — "сумма с контакта"; карточки по умолчанию
    есть (5), если сумма > 0. dual=False — период до двух категорий канала."""
    row = {
        "fio": fio, "supervisor": supervisor, "status": status, "is_novice": is_novice, "is_na": is_na,
        "c1_sum": 1000, "c1_per_contact": c1, "c1_conv": 20, "c1_cards": 5,
        "lk_sum": 0, "lk_per_contact": 0, "lk_cards": 0,
        "time_per_contact": time, "errors_pct": errors,
        "channel": "radio",
        "ch_sum": 1000 if radio else 0, "ch_cards": 5 if radio else 0, "ch_per_contact": radio, "ch_conv": radio_conv,
    }
    if dual:
        row.update({
            "radio_place": 1, "inet_place": 1,
            "radio_sum": 1000 if radio else 0, "radio_per_contact": radio, "radio_conv": radio_conv,
            "radio_cards": radio_cards if radio_cards is not None else (5 if radio else 0),
            "inet_sum": 800 if inet else 0, "inet_per_contact": inet, "inet_conv": inet_conv,
            "inet_cards": inet_cards if inet_cards is not None else (4 if inet else 0),
        })
    row.update(extra)
    return row


def _by_fio(result, level="operators"):
    return {e["fio"]: e for e in result[level]}


# ---------- отбор людей и уровни ----------

def test_three_levels_and_sector_assignment():
    rows = [
        _row("И1", G1, 100), _row("И2", G1B, 120), _row("Б1", G2, 90), _row("Б2", G2, 95), _row("К1", G3, 110),
    ]
    result = build_sector_comparison(rows)
    sectors = {s["sector"]: s for s in result["sectors"]}
    assert set(sectors) == {1, 2, 3}
    assert (sectors[1]["groups"], sectors[1]["people"]) == (2, 2)
    assert (sectors[2]["groups"], sectors[2]["people"]) == (1, 2)
    assert sectors[1]["name"].startswith("Сектор №1") and sectors[3]["name"] == "Сектор №3"
    assert result["totals"] == {"operators": 5, "groups": 4}
    assert {o["sector"] for o in result["operators"] if o["fio"] in ("Б1", "Б2")} == {2}


def test_excludes_na_service_groups_and_counts_each_person_once():
    rows = [
        _row("Свой", G1, 100),
        _row("Н/О", G1, 100, is_na=True),
        _row("ЗДР Регион", "операторы без супервизора", 100),
        _row("ПП Пик", "операторы без супервизора [Пики-ПП]", 100),
        _row("Васько Сотр", "Супервайзер - Васько Иван", 100),
        # новичок: основная строка Н/О + дубль для общего списка — один человек
        _row("Новичок", G1, 100, status="Новичок", is_na=True),
        _row("Новичок", G1, 100, status="Новичок", is_novice=True),
        # новичок Сектора 2: обе строки оценены — берём основную, не дублируем
        _row("Новичок С2", G2, 100, status="Новичок"),
        _row("Новичок С2", G2, 100, status="Новичок", is_novice=True),
    ]
    result = build_sector_comparison(rows)
    assert sorted(o["fio"] for o in result["operators"]) == ["Новичок", "Новичок С2", "Свой"]
    assert result["totals"]["operators"] == 3


def test_no_money_or_ladder_fields_anywhere():
    rows = [_row("А", G1, 100, salary=9999, bonus075=11, bonus2=22, coefficient=1.3, tier=2, work_hours=40,
                 total_score=5, final_place=1)]
    text = str(build_sector_comparison(rows))
    for forbidden in ("salary", "bonus", "coefficient", "tier", "work_hours", "9999"):
        assert forbidden not in text


# ---------- единая формула ----------

def test_unified_score_uses_fixed_weights_and_places_across_all_sectors():
    # Два человека из РАЗНЫХ секторов сравниваются друг с другом (одна выборка).
    rows = [
        _row("Сильный", G2, c1=200, radio=300, inet=100, time=3, errors=0.5),
        _row("Слабый", G3, c1=100, radio=150, inet=50, time=6, errors=2),
    ]
    ops = _by_fio(build_sector_comparison(rows))
    assert ops["Сильный"]["places"] == {"c1": 1, "radio": 1, "inet": 1, "time": 1, "errors": 1}
    assert ops["Слабый"]["places"] == {"c1": 2, "radio": 2, "inet": 2, "time": 2, "errors": 2}
    assert ops["Сильный"]["score"] == 3 + 2.5 + 2.5 + 1 + 1 == 10
    assert ops["Слабый"]["score"] == 2 * 10
    assert (ops["Сильный"]["place"], ops["Слабый"]["place"]) == (1, 2)
    assert UNIFIED_WEIGHTS_DUAL == {"c1": 3, "radio": 2.5, "inet": 2.5, "time": 1, "errors": 1}


def test_score_ignores_stored_total_score_final_place_and_sector_rules():
    # Сохранённые в строке баллы/места (по весам и правилам СВОЕГО сектора) в
    # сравнении не участвуют — места считаются заново по всей выборке.
    rows = [
        _row("А", G2, c1=200, radio=300, inet=100, time=3, errors=0.5, total_score=999, final_place=50),
        _row("Б", G1, c1=100, radio=150, inet=50, time=6, errors=2, total_score=1, final_place=1),
    ]
    ops = _by_fio(build_sector_comparison(rows))
    assert ops["А"]["place"] == 1 and ops["Б"]["place"] == 2


def test_lk_is_shown_as_a_raw_metric_but_not_in_the_score():
    rows = [_row("А", G1, 100, radio=100, inet=50, lk_sum=500, lk_cards=4, lk_per_contact=80)]
    result = build_sector_comparison(rows)
    op = result["operators"][0]
    assert op["metrics"]["lk_pc"] == 80 and "lk" not in op["places"] and "lk" not in result["weights"]


def test_channel_places_use_tiers_like_the_rating():
    # Интернет: А — продавал (тир A), Б — карточек нет (тир Б), В — карточки
    # впустую (конверсия 0, тир В): А=1, Б=2, В=3 — не по сырой сумме с контакта.
    rows = [
        _row("А", G1, 100, radio=100, inet=50),
        _row("Б", G1, 100, radio=100, inet=0, inet_cards=0),
        _row("В", G1, 100, radio=100, inet=9999, inet_cards=20, inet_conv=0),
    ]
    ops = _by_fio(build_sector_comparison(rows))
    assert (ops["А"]["places"]["inet"], ops["Б"]["places"]["inet"], ops["В"]["places"]["inet"]) == (1, 2, 3)


def test_ties_share_the_place_and_order_is_stable():
    rows = [_row(f"О{i}", G1, 100, radio=100, inet=50) for i in range(3)] + [_row("Лучший", G1, 300, radio=500, inet=400, time=1, errors=0)]
    result = build_sector_comparison(rows)
    assert [o["place"] for o in result["operators"]] == [1, 2, 2, 2]
    assert result["operators"][0]["fio"] == "Лучший"


# ---------- супервайзеры и секторы ----------

def test_group_and_sector_metrics_are_averages_over_people_who_worked_the_channel():
    rows = [
        _row("Радио", G1, 100, radio=100, inet=0),                  # Интернет не обслуживал
        _row("Оба", G1, 200, radio=300, inet=400),
    ]
    result = build_sector_comparison(rows)
    group = result["supervisors"][0]["metrics"]
    assert group["c1_pc"] == 150 and group["time"] == 5
    assert group["radio_pc"] == 200 and group["radio_workers"] == 2
    assert group["inet_pc"] == 400 and group["inet_workers"] == 1            # только тот, кто работал
    assert group["c1_sum"] == 2000
    sector = result["sectors"][0]["metrics"]
    assert sector["inet_pc"] == 400 and sector["radio_pc"] == 200


def test_group_without_channel_workers_has_no_average_and_ranks_last_in_it():
    rows = [
        _row("А", G1, 100, radio=100, inet=50), _row("Б", G1B, 100, radio=100, inet=0),   # у группы Б Интернета нет вообще
    ]
    sups = {s["name"]: s for s in build_sector_comparison(rows)["supervisors"]}
    assert sups["Петрова Мария Сергеевна"]["metrics"]["inet_pc"] is None
    assert sups["Петрова Мария Сергеевна"]["places"]["inet"] == 2
    assert sups["Иванов Иван Иванович"]["places"]["inet"] == 1


def test_special_supervisors_are_listed_without_place_and_do_not_affect_others():
    lishtva = "Супервайзер - Лиштва Ольга Васильевна"
    base = [_row("А", G1, 100, radio=100, inet=50), _row("Б", G1B, 200, radio=200, inet=80)]
    with_special = base + [_row("Л", lishtva, 999, radio=999, inet=999, time=0.1, errors=0)]
    result = build_sector_comparison(with_special)
    sups = {s["name"]: s for s in result["supervisors"]}
    assert sups["Лиштва Ольга Васильевна"]["special_label"] == "Лидер"
    assert sups["Лиштва Ольга Васильевна"]["place"] is None and sups["Лиштва Ольга Васильевна"]["score"] is None
    assert result["supervisors"][-1]["name"] == "Лиштва Ольга Васильевна"          # внизу списка
    reference = {s["name"]: s["place"] for s in build_sector_comparison(base)["supervisors"]}
    assert {n: s["place"] for n, s in sups.items() if n in reference} == reference  # места остальных те же
    # но её человек учтён как оператор и в секторном среднем
    assert "Л" in _by_fio(result) and result["sectors"][0]["people"] == 3


def test_special_supervisor_label_matches_only_the_intended_surnames():
    assert special_supervisor_label("Супервайзер - Курбанова Зарина Рахимджановна") == "Лидер"
    assert special_supervisor_label("Супервайзер.- Клюйко Анатолий Анатольевич") == "Старший тренер"
    assert special_supervisor_label("Супервайзер - Курбанова 2 Анастасия Анатольевна") is None
    assert special_supervisor_label(G1) is None and special_supervisor_label(None) is None


def test_sector_places_are_ranked_among_sectors():
    rows = [
        _row("С1", G1, 100, radio=100, inet=50, time=6, errors=2),
        _row("С2", G2, 200, radio=300, inet=100, time=3, errors=0.5),
        _row("С3", G3, 150, radio=200, inet=75, time=4, errors=1),
    ]
    sectors = {s["sector"]: s for s in build_sector_comparison(rows)["sectors"]}
    assert (sectors[2]["place"], sectors[3]["place"], sectors[1]["place"]) == (1, 2, 3)
    assert sectors[2]["score"] == 10 and sectors[1]["score"] == 30


# ---------- старые периоды ----------

def test_legacy_period_uses_single_group_channel_with_its_own_weights():
    rows = [
        _row("А", G1, 200, radio=300, dual=False, time=3, errors=0.5),
        _row("Б", G1, 100, radio=150, dual=False, time=6, errors=2),
    ]
    result = build_sector_comparison(rows)
    assert result["mode"] == "legacy" and result["weights"] == UNIFIED_WEIGHTS_LEGACY == {"c1": 3, "ch": 2.5, "time": 1, "errors": 1}
    ops = _by_fio(result)
    assert ops["А"]["metrics"]["ch_pc"] == 300 and "radio_pc" not in ops["А"]["metrics"]
    assert ops["А"]["places"] == {"c1": 1, "ch": 1, "time": 1, "errors": 1} and ops["А"]["score"] == 7.5
    assert result["labels"]["ch"] == "Канал группы"


def test_empty_period():
    result = build_sector_comparison([])
    assert result["sectors"] == result["supervisors"] == result["operators"] == []
    assert result["totals"] == {"operators": 0, "groups": 0}


# ---------- эндпоинт ----------

class FakeClient:
    def __init__(self, ratings, period_label="10-5"):
        self.ratings = ratings
        self.period_label = period_label
        self.calls = []

    async def get(self, table, params=None):
        params = params or {}
        self.calls.append((table, dict(params)))
        if table == "kpi_uploads":
            return [{"period_label": self.period_label}]
        offset, limit = int(params["offset"]), int(params["limit"])
        return self.ratings[offset:offset + limit]


def _user(role="supervisor", names=None):
    return CurrentUser(access_token="t", user_id="u", email="e@e.com", role=role, supervisor_names=names, display_name="T")


@pytest.fixture
def api(monkeypatch):
    def make(user, fake):
        app.dependency_overrides[get_current_user] = lambda: user
        monkeypatch.setattr(dashboards_router, "as_service", lambda: fake)
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


def test_endpoint_allows_admin_manager_and_sector_heads_and_forbids_others(api):
    rows = [_row("А", G1, 100, radio=100, inet=50)]
    for user in (_user("admin"), _user("manager"), _user("supervisor", sorted(SECTOR_2_SUPERVISORS)),
                 _user("supervisor", sorted(SECTOR_3_SUPERVISORS))):
        r = api(user, FakeClient(rows)).get("/dashboards/sectors", params={"upload_id": "u1"})
        assert r.status_code == 200 and r.json()["period_label"] == "10-5" and r.json()["totals"]["operators"] == 1
    r = api(_user("supervisor", [G1]), FakeClient(rows)).get("/dashboards/sectors", params={"upload_id": "u1"})
    assert r.status_code == 403


def test_endpoint_reads_all_pages_and_returns_all_sectors_to_a_sector_head(api):
    # 2300 строк > 1000 за страницу; руководитель Сектора 2 видит ВСЕ сектора
    rows = [_row(f"И{i}", G1, 100 + i % 50, radio=100, inet=50) for i in range(1500)]
    rows += [_row(f"Б{i}", G2, 100 + i % 50, radio=100, inet=50) for i in range(800)]
    fake = FakeClient(rows)
    r = api(_user("supervisor", sorted(SECTOR_2_SUPERVISORS)), fake).get("/dashboards/sectors", params={"upload_id": "u1"})
    body = r.json()
    assert body["totals"]["operators"] == 2300
    assert {s["sector"] for s in body["sectors"]} == {1, 2}
    pages = [c[1]["offset"] for c in fake.calls if c[0] == "kpi_ratings"]
    assert pages == ["0", "1000", "2000"] and all(c[1]["order"] == "id.asc" for c in fake.calls if c[0] == "kpi_ratings")
