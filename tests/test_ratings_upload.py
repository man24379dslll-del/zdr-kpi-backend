"""
Загрузка отчёта руководителем сектора (Бочиус/Сорокин): GET /ratings/
upload-context и POST /ratings/save-computed, плюс чистая логика
services/ratings_upload.py. Сеть подменена фейковым клиентом Supabase.
"""
import pytest
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user
from app.main import app
from app.routers import ratings
from app.services.group_naming import SECTOR_2_SUPERVISORS, SECTOR_3_SUPERVISORS
from app.services.ratings_upload import (
    ALLOWED_FIELDS,
    UploadValidationError,
    find_previous_upload,
    period_type_of,
    sanitize_rows,
)


def _row(**over):
    base = {"fio": "ЗДР Иванов И. И.", "supervisor": "Супервайзер - А", "status": "Профи", "is_novice": False,
            "is_na": False, "c1_sum": 1000, "final_place": 1, "salary": 500.5, "channel": "radio"}
    base.update(over)
    return base


# ---------- чистая логика ----------

def test_period_type_of():
    assert period_type_of("10-2") == "week"
    assert period_type_of("2026-10-12") == "day"
    for bad in (None, "", "abc", "10-2; drop", "2026-1-1"):
        assert period_type_of(bad) is None


def test_sanitize_rows_keeps_only_whitelisted_columns():
    clean = sanitize_rows([_row(upload_id="evil", id="x", password="1", extra=123)])
    assert set(clean[0]) == set(ALLOWED_FIELDS)
    for forbidden in ("upload_id", "id", "password", "extra"):
        assert forbidden not in clean[0]


@pytest.mark.parametrize("bad", [
    _row(fio=""), _row(supervisor=None), _row(salary="500"), _row(is_na="yes"), _row(c1_sum=True), _row(fio=123),
])
def test_sanitize_rows_rejects_bad_types(bad):
    with pytest.raises(UploadValidationError):
        sanitize_rows([bad])


def test_sanitize_rows_rejects_empty_and_too_many():
    with pytest.raises(UploadValidationError):
        sanitize_rows([])
    with pytest.raises(UploadValidationError):
        sanitize_rows([_row()] * 5001)


def test_find_previous_upload_prefers_latest_period_then_freshest_upload():
    uploads = [
        {"period_label": "9-4", "uploaded_at": "2026-09-28T00:00:00"},
        {"period_label": "10-1", "uploaded_at": "2026-10-05T10:00:00", "id": "old"},
        {"period_label": "10-1", "uploaded_at": "2026-10-05T12:00:00", "id": "fresh"},
        {"period_label": "10-2", "uploaded_at": "2026-10-12T00:00:00"},
        {"period_label": "2026-10-04", "uploaded_at": "2026-10-05T00:00:00"},  # день — другого типа
    ]
    assert find_previous_upload(uploads, "10-2", "week")["id"] == "fresh"
    assert find_previous_upload(uploads, "9-4", "week") is None
    assert find_previous_upload(uploads, "2026-10-05", "day")["period_label"] == "2026-10-04"


# ---------- эндпоинты ----------

class FakeClient:
    def __init__(self, uploads=None, ratings_by_upload=None, fail_ratings=False):
        self.uploads = list(uploads or [])
        self.ratings = dict(ratings_by_upload or {})
        self.fail_ratings = fail_ratings
        self.deleted = []
        self.posted_rows = []

    async def get(self, table, params=None):
        params = params or {}
        if table == "kpi_uploads":
            rows = self.uploads
            if "period_label" in params:
                label = params["period_label"].removeprefix("eq.")
                rows = [u for u in rows if u["period_label"] == label]
            return rows
        if table == "kpi_ratings":
            upload_id = params["upload_id"].removeprefix("eq.")
            return self.ratings.get(upload_id, [])
        raise AssertionError(table)

    async def post(self, table, payload, prefer="return=representation"):
        if table == "kpi_uploads":
            new = {"id": "new-upload", **payload[0], "uploaded_at": "2026-10-13T00:00:00"}
            self.uploads.append(new)
            return [new]
        if table == "kpi_ratings":
            if self.fail_ratings:
                raise RuntimeError("boom")
            self.posted_rows.extend(payload)
            return []
        raise AssertionError(table)

    async def delete(self, path):
        self.deleted.append(path)
        self.uploads = [u for u in self.uploads if u["id"] != path.split("eq.")[1]]


def _user(role="supervisor", names=None):
    return CurrentUser(access_token="t", user_id="u", email="e@e.com", role=role,
                       supervisor_names=names, display_name="T")


@pytest.fixture
def api(monkeypatch):
    holder = {}

    def make(user, fake):
        app.dependency_overrides[get_current_user] = lambda: user
        monkeypatch.setattr(ratings, "as_service", lambda: fake)
        holder["fake"] = fake
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


SECTOR2_HEAD = lambda: _user("supervisor", sorted(SECTOR_2_SUPERVISORS))
SECTOR3_HEAD = lambda: _user("supervisor", sorted(SECTOR_3_SUPERVISORS))


def test_save_computed_writes_upload_and_rows(api):
    fake = FakeClient()
    client = api(SECTOR2_HEAD(), fake)
    body = {"period_label": "10-3", "source_filename": "f.xlsx", "rows": [_row(), _row(fio="ЗДР Петров П. П.", is_novice=True)]}
    r = client.post("/ratings/save-computed", json=body)
    assert r.status_code == 200 and r.json() == {"upload_id": "new-upload", "rows": 2}
    assert [x["upload_id"] for x in fake.posted_rows] == ["new-upload", "new-upload"]
    assert fake.uploads[0]["period_label"] == "10-3" and fake.uploads[0]["source_filename"] == "f.xlsx"


def test_save_computed_blocks_duplicate_period_with_409(api):
    fake = FakeClient(uploads=[{"id": "u1", "period_label": "10-3", "uploaded_at": "x"}])
    client = api(SECTOR3_HEAD(), fake)
    r = client.post("/ratings/save-computed", json={"period_label": "10-3", "rows": [_row()]})
    assert r.status_code == 409
    assert fake.posted_rows == [] and len(fake.uploads) == 1


def test_save_computed_forbidden_for_non_sector_heads(api):
    for user in (_user("supervisor", ["Супервайзер - А"]), _user("admin", None), _user("manager", None)):
        fake = FakeClient()
        client = api(user, fake)
        assert client.post("/ratings/save-computed", json={"period_label": "10-3", "rows": [_row()]}).status_code == 403
        assert client.get("/ratings/upload-context", params={"period_label": "10-3"}).status_code == 403
        assert fake.uploads == []


def test_save_computed_rejects_bad_label_and_rows(api):
    client = api(SECTOR2_HEAD(), FakeClient())
    assert client.post("/ratings/save-computed", json={"period_label": "x", "rows": [_row()]}).status_code == 400
    assert client.post("/ratings/save-computed", json={"period_label": "10-3", "rows": []}).status_code == 422
    assert client.post("/ratings/save-computed", json={"period_label": "10-3", "rows": [_row(salary="9")]}).status_code == 422


def test_save_computed_rolls_back_upload_on_write_error(api):
    fake = FakeClient(fail_ratings=True)
    client = api(SECTOR2_HEAD(), fake)
    r = client.post("/ratings/save-computed", json={"period_label": "10-3", "rows": [_row()]})
    assert r.status_code == 502
    assert fake.deleted == ["kpi_uploads?id=eq.new-upload"] and fake.uploads == []


def test_upload_context_returns_company_wide_prev_rows_and_existing(api):
    prev_rows = [{"fio": "А", "coefficient": 1.3}, {"fio": "Б", "coefficient": 1.1}]
    fake = FakeClient(
        uploads=[
            {"id": "p", "period_label": "10-1", "uploaded_at": "2026-10-05T00:00:00"},
            {"id": "c", "period_label": "10-2", "uploaded_at": "2026-10-12T00:00:00"},
        ],
        ratings_by_upload={"p": prev_rows},
    )
    client = api(SECTOR3_HEAD(), fake)
    r = client.get("/ratings/upload-context", params={"period_label": "10-2"}).json()
    assert r["existing"]["id"] == "c"
    assert r["prev_upload"] == {"id": "p", "period_label": "10-1"}
    assert r["prev_rows"] == prev_rows
    r2 = client.get("/ratings/upload-context", params={"period_label": "10-3"}).json()
    assert r2["existing"] is None and r2["prev_upload"]["id"] == "c"
    r3 = client.get("/ratings/upload-context", params={"period_label": "9-1"}).json()
    assert r3["prev_upload"] is None and r3["prev_rows"] == []
