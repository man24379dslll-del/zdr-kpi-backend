"""
Внешний доступ только на чтение (X-API-Key, GET /external/operators) —
см. routers/external.py, services/api_keys.py. Сеть не нужна: доступ к
Supabase подменяется на уровне функций роутера.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers import external
from app.services.api_keys import RateLimiter, client_ip, generate_key, hash_key, ip_allowed

KEY = "test-key-value"
GOOD = {"id": "k1", "name": "Force", "key_hash": hash_key(KEY), "scope": "operators_read",
        "allowed_ips": None, "revoked_at": None}

ROWS = [
    {"fio": "ЗДР Иванов И. И.", "supervisor": "Супервайзер - Петров", "work_hours": 40, "shift_count": 5,
     "final_place": 3,
     # поля, которых наружу быть не должно, даже если строка пришла «лишней»
     "salary": 9999, "coefficient": 1.3, "bonus075": 10, "bonus2": 20, "tier": 2, "is_novice": False},
    {"fio": "ЗДР Сидоров С. С.", "supervisor": "Супервайзер - Петров", "work_hours": None, "shift_count": None,
     "final_place": None},
]


@pytest.fixture
def client(monkeypatch):
    state = {"record": dict(GOOD), "touched": []}

    async def find_key(key_hash):
        r = state["record"]
        return r if r and r["key_hash"] == key_hash else None

    async def touch(key_id):
        state["touched"].append(key_id)

    async def latest_upload(period):
        return {"id": "u1", "period_label": period} if period in ("7-1", "2026-07-27") else None

    async def load_ratings(upload_id):
        return ROWS

    monkeypatch.setattr(external, "_find_key", find_key)
    monkeypatch.setattr(external, "_touch_last_used", touch)
    monkeypatch.setattr(external, "_load_latest_upload", latest_upload)
    monkeypatch.setattr(external, "_load_ratings", load_ratings)
    monkeypatch.setattr(external, "_key_limiter", RateLimiter(limit=60))
    monkeypatch.setattr(external, "_fail_limiter", RateLimiter(limit=20))
    c = TestClient(app)
    c.state = state
    return c


def _get(client, headers=None, period="7-1", type_="week"):
    return client.get("/external/operators", params={"period": period, "type": type_},
                      headers={"X-API-Key": KEY, **(headers or {})})


# ---------------- ключ ----------------

def test_missing_key_is_401(client):
    r = client.get("/external/operators", params={"period": "7-1", "type": "week"})
    assert r.status_code == 401


def test_wrong_key_is_401(client):
    r = client.get("/external/operators", params={"period": "7-1", "type": "week"},
                   headers={"X-API-Key": "nope"})
    assert r.status_code == 401


def test_revoked_key_is_401(client):
    client.state["record"]["revoked_at"] = "2026-10-01T00:00:00+00:00"
    assert _get(client).status_code == 401


def test_valid_key_ok_and_last_used_touched(client):
    r = _get(client)
    assert r.status_code == 200
    assert client.state["touched"] == ["k1"]


def test_foreign_scope_is_403(client):
    client.state["record"]["scope"] = "something_else"
    assert _get(client).status_code == 403


def test_key_on_other_path_is_403(client):
    # Внешний ключ не открывает ничего, кроме /external/*.
    for path in ("/ratings/by-upload?upload_id=x", "/health", "/dashboards/summary", "/"):
        r = client.get(path, headers={"X-API-Key": KEY})
        assert r.status_code == 403, path


def test_post_not_allowed_on_external(client):
    r = client.post("/external/operators", headers={"X-API-Key": KEY})
    assert r.status_code == 405


def test_failed_attempts_are_limited_per_ip(client):
    for _ in range(20):
        assert client.get("/external/operators", params={"period": "7-1", "type": "week"},
                          headers={"X-API-Key": "bad"}).status_code == 401
    r = client.get("/external/operators", params={"period": "7-1", "type": "week"},
                   headers={"X-API-Key": "bad"})
    assert r.status_code == 429


# ---------------- IP ----------------

def test_ip_outside_allowlist_is_403(client):
    client.state["record"]["allowed_ips"] = ["203.0.113.5"]
    assert _get(client, {"X-Forwarded-For": "198.51.100.7"}).status_code == 403


def test_ip_in_allowlist_and_subnet_ok(client):
    client.state["record"]["allowed_ips"] = ["10.0.0.0/24", "203.0.113.5"]
    assert _get(client, {"X-Forwarded-For": "203.0.113.5"}).status_code == 200
    assert _get(client, {"X-Forwarded-For": "10.0.0.77"}).status_code == 200


def test_empty_allowlist_means_no_ip_restriction(client):
    client.state["record"]["allowed_ips"] = []
    assert _get(client, {"X-Forwarded-For": "198.51.100.7"}).status_code == 200


def test_forged_leading_xff_entry_does_not_bypass_allowlist(client):
    # Клиент сам приписывает разрешённый адрес слева; прокси Railway
    # дописывает настоящий справа — решает последний.
    client.state["record"]["allowed_ips"] = ["203.0.113.5"]
    r = _get(client, {"X-Forwarded-For": "203.0.113.5, 198.51.100.7"})
    assert r.status_code == 403


def test_client_ip_uses_trusted_hop_from_the_right():
    assert client_ip("1.1.1.1, 2.2.2.2", "9.9.9.9", 1) == "2.2.2.2"
    assert client_ip("1.1.1.1, 2.2.2.2", "9.9.9.9", 2) == "1.1.1.1"
    assert client_ip("1.1.1.1", "9.9.9.9", 2) == "9.9.9.9"   # цепочка короче доверенной
    assert client_ip("1.1.1.1", "9.9.9.9", 0) == "9.9.9.9"   # заголовку не доверяем
    assert client_ip(None, "9.9.9.9", 1) == "9.9.9.9"


def test_ip_allowed_fail_closed():
    assert ip_allowed("1.2.3.4", None) is True
    assert ip_allowed("not-an-ip", ["1.2.3.4"]) is False
    assert ip_allowed(None, ["1.2.3.4"]) is False
    assert ip_allowed("1.2.3.4", ["garbage"]) is False
    assert ip_allowed("2001:db8::1", ["2001:db8::/32"]) is True


# ---------------- данные ----------------

def test_response_contains_only_whitelisted_fields(client):
    body = _get(client).json()
    assert body["period"] == "7-1" and body["type"] == "week" and body["count"] == 2
    allowed = {"fio", "supervisor", "period_label", "work_hours", "shift_count", "final_place"}
    for op in body["operators"]:
        assert set(op) == allowed
    assert body["operators"][0] == {
        "fio": "ЗДР Иванов И. И.", "supervisor": "Супервайзер - Петров", "period_label": "7-1",
        "work_hours": 40, "shift_count": 5, "final_place": 3,
    }
    assert body["operators"][1]["final_place"] is None
    text = str(body)
    for forbidden in ("salary", "coefficient", "bonus", "tier", "9999"):
        assert forbidden not in text


def test_type_must_match_period_label(client):
    assert _get(client, period="7-1", type_="day").status_code == 400
    assert _get(client, period="2026-07-27", type_="week").status_code == 400
    assert _get(client, period="2026-07-27", type_="day").status_code == 200


def test_bad_type_and_bad_period_rejected(client):
    assert _get(client, type_="month").status_code == 422
    assert _get(client, period="7-1;drop", type_="week").status_code == 400


def test_unknown_period_is_404(client):
    assert _get(client, period="9-9", type_="week").status_code == 404


def test_load_ratings_selects_only_whitelist_and_main_rows_and_paginates(monkeypatch):
    calls = []

    class FakeClient:
        async def get(self, path, params=None):
            calls.append(params)
            n = external.PAGE_SIZE if len(calls) == 1 else 3
            return [{"fio": f"F{len(calls)}-{i}"} for i in range(n)]

    monkeypatch.setattr(external, "as_service", lambda: FakeClient())
    rows = asyncio.run(external._load_ratings("u1"))
    assert len(rows) == external.PAGE_SIZE + 3
    assert [c["offset"] for c in calls] == ["0", str(external.PAGE_SIZE)]
    for c in calls:
        assert c["select"] == "fio,supervisor,work_hours,shift_count,final_place"
        assert c["is_novice"] == "eq.false"


# ---------------- лимит ----------------

def test_rate_limit_per_key(client, monkeypatch):
    monkeypatch.setattr(external, "_key_limiter", RateLimiter(limit=3))
    codes = [_get(client).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_rate_limiter_window_expires():
    now = [0.0]
    rl = RateLimiter(limit=2, window=60, clock=lambda: now[0])
    assert rl.allow("k") and rl.allow("k") and not rl.allow("k")
    assert rl.peek("k") is False
    now[0] = 61
    assert rl.allow("k") is True
    assert rl.allow("other") is True  # лимит per-key


# ---------------- ключи ----------------

def test_generated_key_is_long_random_and_hash_is_sha256():
    k1, k2 = generate_key(), generate_key()
    assert k1 != k2 and len(k1) >= 43
    h = hash_key(k1)
    assert len(h) == 64 and h != k1 and h == hash_key(k1)
    assert settings.trusted_proxy_hops >= 0
