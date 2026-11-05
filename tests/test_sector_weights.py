"""
Веса категорий по секторам: чистая логика (services/sector_weights.py),
эндпоинты /sector-weights (права, заявки руководителей, подтверждение
админом) и применение весов в Python-расчёте (weekly_rating). Сеть
подменена фейковым клиентом Supabase.
"""
import math

import pytest
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user
from app.main import app
from app.routers import sector_weights as router_mod
from app.services.group_naming import SECTOR_2_SUPERVISORS, SECTOR_3_SUPERVISORS
from app.services.sector_weights import (
    DEFAULT_WEIGHTS,
    WEIGHT_KEYS,
    WeightsValidationError,
    effective_weights,
    parse_snapshot,
    sector_of_supervisor,
    snapshot_of,
    validate_weights,
    weights_equal,
)


def _w(**over):
    return {**DEFAULT_WEIGHTS, **over}


# ---------- чистая логика ----------

def test_default_weights_are_the_previous_hardcoded_ones():
    assert DEFAULT_WEIGHTS == {"c1": 3, "lk": 1.5, "radio": 2.5, "inet": 2.5, "time": 1, "errors": 1}
    assert set(DEFAULT_WEIGHTS) == set(WEIGHT_KEYS)


def test_sector_of_supervisor():
    assert sector_of_supervisor(next(iter(SECTOR_2_SUPERVISORS))) == 2
    assert sector_of_supervisor(next(iter(SECTOR_3_SUPERVISORS))) == 3
    assert sector_of_supervisor("Супервайзер - Иванов Иван Иванович") == 1
    assert sector_of_supervisor("операторы без супервизора [Пики-ПП]") == 1
    assert sector_of_supervisor(None) == 1


def test_validate_weights_accepts_and_rounds():
    assert validate_weights(_w(c1=3.456, lk=0)) == _w(c1=3.46, lk=0)
    assert validate_weights({k: 10 for k in WEIGHT_KEYS})["c1"] == 10.0


@pytest.mark.parametrize("bad", [
    None, [], "x",
    {k: v for k, v in DEFAULT_WEIGHTS.items() if k != "errors"},      # не хватает ключа
    {**DEFAULT_WEIGHTS, "extra": 1},                                  # лишний ключ
    _w(c1=-0.1), _w(c1=10.01), _w(time=math.nan), _w(time=math.inf),
    _w(c1="3"), _w(c1=True), _w(c1=None),
    {**{k: 0 for k in WEIGHT_KEYS}, "lk": 2},                         # всё, кроме ЛК, равно 0
])
def test_validate_weights_rejects(bad):
    with pytest.raises(WeightsValidationError):
        validate_weights(bad)


def test_effective_weights_default_then_latest_approved_ignoring_other_statuses():
    assert effective_weights([])[2] == {"weights": DEFAULT_WEIGHTS, "source": "default", "change_id": None, "decided_at": None}
    changes = [
        {"id": "a", "sector": 2, "weights": _w(c1=4), "status": "approved", "decided_at": "2026-10-01T00:00:00+00:00"},
        {"id": "b", "sector": 2, "weights": _w(c1=5), "status": "approved", "decided_at": "2026-10-08T00:00:00+00:00"},
        {"id": "c", "sector": 2, "weights": _w(c1=9), "status": "pending", "requested_at": "2026-10-09T00:00:00+00:00"},
        {"id": "d", "sector": 2, "weights": _w(c1=8), "status": "rejected", "decided_at": "2026-10-10T00:00:00+00:00"},
        {"id": "e", "sector": 2, "weights": _w(c1=7), "status": "cancelled", "decided_at": "2026-10-11T00:00:00+00:00"},
        {"id": "f", "sector": 3, "weights": _w(inet=0), "status": "approved", "decided_at": "2026-10-02T00:00:00+00:00"},
    ]
    eff = effective_weights(changes)
    assert eff[2]["weights"]["c1"] == 5 and eff[2]["change_id"] == "b" and eff[2]["source"] == "approved"
    assert eff[3]["weights"]["inet"] == 0
    assert eff[1]["source"] == "default"          # сектор 1 не менялся


def test_snapshot_roundtrip_and_validation():
    eff = effective_weights([])
    snap = snapshot_of(eff)
    assert set(snap) == {"1", "2", "3"}
    parsed = parse_snapshot(snap)
    assert all(weights_equal(parsed[s], DEFAULT_WEIGHTS) for s in (1, 2, 3))
    for bad in (None, {}, {"1": {}, "2": {}, "3": {}}, {**snap, "4": snap["1"]},
                {**snap, "2": {"weights": _w(c1=-1)}}, {**snap, "3": "x"}):
        with pytest.raises(WeightsValidationError):
            parse_snapshot(bad)


# ---------- эндпоинты ----------

class FakeClient:
    def __init__(self, changes=None):
        self.changes = [dict(c) for c in (changes or [])]
        self.patches = []
        self._seq = 0

    async def get(self, table, params=None):
        assert table == "sector_weight_changes"
        params = params or {}
        rows = self.changes
        if "id" in params:
            rows = [c for c in rows if c["id"] == params["id"].removeprefix("eq.")]
        if "status" in params:
            rows = [c for c in rows if c["status"] == params["status"].removeprefix("eq.")]
        return sorted(rows, key=lambda c: c.get("requested_at") or "", reverse=True)

    async def post(self, table, payload, prefer="return=representation"):
        assert table == "sector_weight_changes"
        self._seq += 1
        row = {"id": f"00000000-0000-0000-0000-{self._seq:012d}", "requested_at": f"2026-10-2{self._seq}T00:00:00+00:00",
               "decided_by_name": None, "decided_at": None, "comment": None, **payload}
        self.changes.append(row)
        return [row]

    async def patch(self, path, payload, prefer="return=representation"):
        table, query = path.split("?", 1)
        assert table == "sector_weight_changes"
        conds = dict(part.split("=eq.") for part in query.split("&"))
        matched = [c for c in self.changes
                   if all(str(c.get(k)) == v for k, v in conds.items())]
        for c in matched:
            c.update(payload)
        self.patches.append((conds, payload))
        return matched if prefer != "return=minimal" else []


def _user(role="supervisor", names=None, name="Тест Т."):
    return CurrentUser(access_token="t", user_id="user-1", email="e@e.com", role=role,
                       supervisor_names=names, display_name=name)


ADMIN = lambda: _user("admin", None, "Админ")
MANAGER = lambda: _user("manager", None, "Менеджер")
HEAD2 = lambda: _user("supervisor", sorted(SECTOR_2_SUPERVISORS), "Бочиус")
HEAD3 = lambda: _user("supervisor", sorted(SECTOR_3_SUPERVISORS), "Сорокин")
PLAIN = lambda: _user("supervisor", ["Супервайзер - Иванов Иван Иванович"], "Иванов")


@pytest.fixture
def api(monkeypatch):
    def make(user, fake):
        app.dependency_overrides[get_current_user] = lambda: user
        monkeypatch.setattr(router_mod, "as_service", lambda: fake)
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


def _pending(sector, **over):
    return {"id": f"11111111-1111-1111-1111-{sector:012d}", "sector": sector, "weights": _w(c1=5),
            "status": "pending", "requested_by_name": "Руководитель", "requested_at": "2026-10-05T00:00:00+00:00", **over}


def test_get_returns_effective_weights_for_everyone_and_scoped_pending_history(api):
    changes = [
        _pending(2),
        _pending(3, id="22222222-2222-2222-2222-000000000003"),
        {"id": "33333333-3333-3333-3333-000000000002", "sector": 2, "weights": _w(c1=4), "status": "approved",
         "decided_at": "2026-10-01T00:00:00+00:00", "requested_at": "2026-10-01T00:00:00+00:00"},
    ]
    admin = api(ADMIN(), FakeClient(changes)).get("/sector-weights").json()
    assert admin["sectors"]["2"]["weights"]["c1"] == 4 and admin["sectors"]["1"]["source"] == "default"
    assert len(admin["pending"]) == 2 and admin["can_approve"] is True and admin["editable_sectors"] == [1, 2, 3]

    head = api(HEAD2(), FakeClient(changes)).get("/sector-weights").json()
    assert [p["sector"] for p in head["pending"]] == [2] and head["editable_sectors"] == [2]
    assert head["can_approve"] is False and all(h["sector"] == 2 for h in head["history"])
    assert head["sectors"]["3"]["weights"] == DEFAULT_WEIGHTS          # действующие веса видны всем

    plain = api(PLAIN(), FakeClient(changes)).get("/sector-weights").json()
    assert plain["pending"] == [] and plain["history"] == [] and plain["editable_sectors"] == []
    assert plain["can_approve"] is False


def test_admin_and_manager_change_weights_immediately_and_supersede_pending(api):
    for make_user in (ADMIN, MANAGER):
        fake = FakeClient([_pending(2)])
        r = api(make_user(), fake).put("/sector-weights/2", json={"weights": _w(c1=6), "comment": "по итогам недели"})
        assert r.status_code == 200 and r.json()["applied"] is True
        created = fake.changes[-1]
        assert created["status"] == "approved" and created["weights"]["c1"] == 6
        assert created["decided_by"] == "user-1" and created["decided_at"]
        assert created["comment"] == "по итогам недели"
        # висевшая заявка сектора заменена
        assert fake.changes[0]["status"] == "cancelled"


def test_sector_head_can_only_submit_a_pending_request_for_own_sector(api):
    fake = FakeClient()
    client = api(HEAD2(), fake)
    r = client.put("/sector-weights/2", json={"weights": _w(lk=2)})
    assert r.status_code == 200 and r.json()["applied"] is False
    assert fake.changes[-1]["status"] == "pending" and fake.changes[-1]["requested_by_name"] == "Бочиус"
    # на действующие веса заявка не влияет, пока её не подтвердили
    assert effective_weights(fake.changes)[2]["source"] == "default"
    # чужой сектор и сектор 1 — нельзя
    assert client.put("/sector-weights/3", json={"weights": _w(lk=2)}).status_code == 403
    assert client.put("/sector-weights/1", json={"weights": _w(lk=2)}).status_code == 403
    assert len(fake.changes) == 1


def test_head3_is_limited_to_sector_3_and_plain_supervisor_cannot_change_anything(api):
    fake = FakeClient()
    assert api(HEAD3(), fake).put("/sector-weights/3", json={"weights": _w(inet=0)}).status_code == 200
    assert api(HEAD3(), fake).put("/sector-weights/2", json={"weights": _w(inet=0)}).status_code == 403
    assert api(PLAIN(), fake).put("/sector-weights/1", json={"weights": _w(inet=0)}).status_code == 403
    assert len(fake.changes) == 1


def test_new_request_replaces_the_previous_pending_one(api):
    fake = FakeClient([_pending(2)])
    r = api(HEAD2(), fake).put("/sector-weights/2", json={"weights": _w(time=2)})
    assert r.status_code == 200
    assert [c["status"] for c in fake.changes] == ["cancelled", "pending"]


def test_put_validates_weights_sector_and_no_change(api):
    fake = FakeClient()
    client = api(ADMIN(), fake)
    assert client.put("/sector-weights/4", json={"weights": _w()}).status_code == 404
    assert client.put("/sector-weights/2", json={"weights": _w(c1=11)}).status_code == 422
    assert client.put("/sector-weights/2", json={"weights": {"c1": 1}}).status_code == 422
    assert client.put("/sector-weights/2", json={"weights": _w(), "comment": "x" * 501}).status_code == 400
    same = client.put("/sector-weights/2", json={"weights": _w()})
    assert same.status_code == 400 and "менять нечего" in same.json()["detail"]
    assert fake.changes == []


def test_admin_approves_or_rejects_pending_request_head_cannot(api):
    change = _pending(2)
    fake = FakeClient([change])
    cid = change["id"]
    assert api(HEAD2(), fake).post(f"/sector-weights/changes/{cid}/approve").status_code == 403
    assert fake.changes[0]["status"] == "pending"

    r = api(ADMIN(), fake).post(f"/sector-weights/changes/{cid}/approve")
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert fake.changes[0]["decided_by_name"] == "Админ" and fake.changes[0]["decided_at"]
    assert effective_weights(fake.changes)[2]["weights"]["c1"] == 5          # вступило в силу
    # повторное решение — 409, ничего не меняется
    assert api(ADMIN(), fake).post(f"/sector-weights/changes/{cid}/reject").status_code == 409

    other = _pending(3, id="44444444-4444-4444-4444-000000000003")
    fake2 = FakeClient([other])
    r = api(MANAGER(), fake2).post(f"/sector-weights/changes/{other['id']}/reject", json={"comment": "рано"})
    assert r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["comment"] == "рано"
    assert effective_weights(fake2.changes)[3]["source"] == "default"        # отклонённая не действует


def test_decision_unknown_or_malformed_id_is_404(api):
    client = api(ADMIN(), FakeClient())
    assert client.post("/sector-weights/changes/00000000-0000-0000-0000-000000000009/approve").status_code == 404
    assert client.post("/sector-weights/changes/not-a-uuid/approve").status_code == 404
    assert client.post("/sector-weights/changes/1%3Bdrop/approve").status_code == 404


def test_corrupt_weights_in_pending_request_cannot_be_approved(api):
    bad = _pending(2, weights={"c1": 99})
    fake = FakeClient([bad])
    r = api(ADMIN(), fake).post(f"/sector-weights/changes/{bad['id']}/approve")
    assert r.status_code == 422 and fake.changes[0]["status"] == "pending"


# ---------- применение в расчёте ----------

def _employee(fio, supervisor, c1_pc, time_pc=5.0, errors_pct=1.0, lk_pc=0.0, radio_pc=100.0, inet_pc=50.0):
    return {
        "fio": fio, "supervisor": supervisor, "status": "", "is_region_uk": False, "is_novice": False,
        "c1_sum": 1000, "c1_per_contact": c1_pc, "c1_cards": 5, "c1_conv": 10,
        "lk_sum": 0, "lk_per_contact": lk_pc, "lk_cards": 0, "lk_conv": 0,
        "radio_sum": 1000, "radio_per_contact": radio_pc, "radio_cards": 4, "radio_conv": 10,
        "inet_sum": 500, "inet_per_contact": inet_pc, "inet_cards": 3, "inet_conv": 10,
        "ch_sum": 1000, "ch_per_contact": radio_pc, "ch_cards": 4, "ch_conv": 10, "channel": "radio",
        "time_per_contact": time_pc, "errors_pct": errors_pct,
    }


def _categories():
    from app.services.rating_engine import RatingCategory
    return [
        RatingCategory(key="c1", label="1", source_column="c1_per_contact", weight=3, direction="desc", sort_order=1),
        RatingCategory(key="lk", label="ЛК", source_column="lk_per_contact", weight=1.5, direction="desc", sort_order=2),
        RatingCategory(key="channel", label="канал", source_column="ch_per_contact", weight=2.5, direction="desc", sort_order=3),
        RatingCategory(key="time", label="время", source_column="time_per_contact", weight=1, direction="asc", sort_order=4),
        RatingCategory(key="errors", label="ошибки", source_column="errors_pct", weight=1, direction="asc", sort_order=5),
    ]


def test_calculation_uses_the_weights_of_each_groups_own_sector():
    from app.services.weekly_rating import compute_weekly_rating

    g1 = "Супервайзер - Иванов Иван Иванович"                         # Сектор 1
    g2 = next(iter(SECTOR_2_SUPERVISORS))                            # Сектор 2
    employees = [_employee(f"{tag} {i}", g, c1_pc=100 + 10 * i) for g, tag in ((g1, "С1"), (g2, "С2")) for i in range(3)]
    weights = {1: _w(), 2: _w(c1=7, radio=0, inet=4.5, time=2, errors=0.5), 3: _w()}
    by_fio = {r.fio: r for r in compute_weekly_rating(employees, _categories(), sector_weights=weights)}

    a = by_fio["С1 0"]                                               # Сектор 1 — стандартные веса
    assert a.scores["c1"] == a.places["c1"] * 3 and a.scores["radio"] == a.places["radio"] * 2.5
    b = by_fio["С2 0"]                                               # Сектор 2 — свои веса
    assert b.scores["c1"] == b.places["c1"] * 7
    assert b.scores["radio"] == 0 and b.scores["inet"] == b.places["inet"] * 4.5
    assert b.scores["time"] == b.places["time"] * 2 and b.scores["errors"] == b.places["errors"] * 0.5
    # у Сектора 2 ЛК в сумму не входит (кроме 3 исключений), а место по ЛК всегда 1-е
    assert "lk" not in b.scores and b.places["lk"] == 1
    assert b.total_score == sum(b.scores.values())


def test_without_sector_weights_calculation_is_unchanged():
    from app.services.weekly_rating import compute_weekly_rating

    employees = [_employee(f"Сотр {i}", "Супервайзер - Иванов Иван Иванович", c1_pc=100 + 10 * i) for i in range(3)]
    plain = {r.fio: r.total_score for r in compute_weekly_rating(employees, _categories())}
    explicit = {r.fio: r.total_score for r in compute_weekly_rating(employees, _categories(), sector_weights={1: _w(), 2: _w(), 3: _w()})}
    assert plain == explicit


def test_lk_weight_of_the_sector_applies_to_sector2_exceptions_only():
    from app.services.group_naming import SECTOR_2_LK_WEIGHT_EXCEPTIONS_FIO
    from app.services.weekly_rating import compute_weekly_rating

    g2 = next(iter(SECTOR_2_SUPERVISORS))
    exception = next(iter(SECTOR_2_LK_WEIGHT_EXCEPTIONS_FIO))
    employees = [_employee(exception, g2, 150), _employee("Обычный", g2, 120)]
    by_fio = {r.fio: r for r in compute_weekly_rating(employees, _categories(), sector_weights={1: _w(), 2: _w(lk=4), 3: _w()})}
    assert by_fio[exception].scores["lk"] == 1 * 4                    # место 1 × вес ЛК сектора
    assert "lk" not in by_fio["Обычный"].scores


def test_lk_off_in_snapshot_needs_zero_weight_in_all_three_sectors():
    from app.services.sector_weights import lk_off_in_snapshot

    def snap(*lk):
        return {str(s): {"weights": _w(lk=w), "change_id": None} for s, w in zip((1, 2, 3), lk)}

    assert lk_off_in_snapshot(snap(0, 0, 0)) is True
    assert lk_off_in_snapshot(snap(0, 0, 1.5)) is False
    assert lk_off_in_snapshot(snap(1.5, 1.5, 1.5)) is False
    assert lk_off_in_snapshot(None) is False and lk_off_in_snapshot({}) is False


def test_lk_weight_zero_takes_lk_out_of_the_total_in_every_group_type():
    from app.services.weekly_rating import compute_weekly_rating

    sector_weights = {n: _w(lk=0) for n in (1, 2, 3)}
    g1, g3 = "Супервайзер - Иванов Иван Иванович", next(iter(SECTOR_3_SUPERVISORS))
    region = {**_employee("Регион", "операторы без супервизора", 150, lk_pc=80), "is_region_uk": True}
    employees = [_employee(f"О{i}", g, 100 + 10 * i, lk_pc=50 + i) for g in (g1, g3) for i in range(3)] + [region]
    with_lk = {r.fio: r for r in compute_weekly_rating(employees, _categories())}
    no_lk = {r.fio: r for r in compute_weekly_rating(employees, _categories(), sector_weights=sector_weights)}

    for fio in ("О0", "О2", "Регион"):
        assert no_lk[fio].scores["lk"] == 0                                     # место по ЛК считается, балл нулевой
        assert no_lk[fio].total_score == sum(v for k, v in no_lk[fio].scores.items() if k != "lk")
        assert no_lk[fio].places["lk"] == with_lk[fio].places["lk"]
    assert with_lk["О0"].total_score > no_lk["О0"].total_score                    # с ЛК балл был больше
    # Регион УК: в сумме остались только 1 обращение и время
    assert set(no_lk["Регион"].scores) == {"c1", "lk", "time"}
    assert no_lk["Регион"].total_score == no_lk["Регион"].scores["c1"] + no_lk["Регион"].scores["time"]
