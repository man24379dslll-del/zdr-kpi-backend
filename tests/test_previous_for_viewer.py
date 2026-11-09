"""
GET /ratings/previous-for-viewer: прошлая неделя ПО ЛЮДЯМ для окна супервайзера
(коэффициент ЛГ и места следуют за человеком при переходе между группами),
без раскрытия людей, которых пользователь не видит.
"""
import pytest
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user
from app.main import app
from app.routers import ratings
from app.services.group_naming import SECTOR_2_SUPERVISORS, SECTOR_3_SUPERVISORS

G_NEW = "Супервайзер Марченко Елена Владимировна"      # группа, куда перешёл человек
G_OLD = "Супервизор Галина Элина Альфредовна"            # группа, где он был на прошлой неделе
G_OTHER = "Супервайзер - Иванов Иван Иванович"           # посторонняя группа

CUR, PREV, OLDER, DAY = (f"00000000-0000-0000-0000-00000000000{i}" for i in (1, 2, 3, 4))
UPLOADS = [
    {"id": CUR, "period_label": "11-1", "uploaded_at": "2026-11-09T07:00:00"},
    {"id": PREV, "period_label": "10-5", "uploaded_at": "2026-11-02T07:23:00"},
    {"id": "00000000-0000-0000-0000-000000000005", "period_label": "10-5", "uploaded_at": "2026-11-02T07:04:00"},   # дубль 10-5, раньше
    {"id": OLDER, "period_label": "10-4", "uploaded_at": "2026-10-26T08:00:00"},
    {"id": DAY, "period_label": "2026-11-04", "uploaded_at": "2026-11-05T08:00:00"},
]


def _r(fio, supervisor, coefficient=None, final_place=None, is_na=False, is_novice=False, total_score=10.0):
    return {"fio": fio, "supervisor": supervisor, "coefficient": coefficient, "final_place": final_place,
            "is_na": is_na, "is_novice": is_novice, "total_score": total_score}


RATINGS = {
    CUR: [_r("Перешедший", G_NEW), _r("Свой", G_NEW), _r("Чужой", G_OTHER), _r("Новичок", G_NEW)],
    PREV: [
        _r("Перешедший", G_OLD, coefficient=1.2, final_place=6),          # прошлая неделя — в другой группе
        _r("Свой", G_NEW, coefficient=1.3, final_place=1),
        _r("Чужой", G_OTHER, coefficient=0.9, final_place=9),
        _r("Коллега по прошлой группе", G_OLD, coefficient=1.1, final_place=7),   # в нынешней таблице его нет
        _r("Новичок", G_NEW, is_na=True, coefficient=1.05),
        _r("Новичок", G_NEW, is_novice=True, coefficient=None, final_place=203),
    ],
    OLDER: [_r("Перешедший", G_OLD, coefficient=0.5)],
    "00000000-0000-0000-0000-000000000005": [_r("Перешедший", G_OLD, coefficient=0.1)],   # дубль — не должен выбираться
}


class FakeClient:
    def __init__(self, uploads=UPLOADS, ratings_=RATINGS):
        self.uploads, self.ratings = uploads, ratings_
        self.calls = []

    async def get(self, table, params=None):
        params = params or {}
        self.calls.append((table, dict(params)))
        if table == "kpi_uploads":
            return self.uploads[int(params["offset"]):int(params["offset"]) + int(params["limit"])]
        upload_id = params["upload_id"].removeprefix("eq.")
        rows = self.ratings.get(upload_id, [])
        select = params["select"].split(",")
        rows = [{k: r[k] for k in select} for r in rows]
        return rows[int(params["offset"]):int(params["offset"]) + int(params["limit"])]


def _user(role="supervisor", names=None):
    return CurrentUser(access_token="t", user_id="u", email="e@e.com", role=role, supervisor_names=names, display_name="T")


@pytest.fixture
def api(monkeypatch):
    def make(user, fake=None):
        app.dependency_overrides[get_current_user] = lambda: user
        monkeypatch.setattr(ratings, "as_service", lambda: fake or FakeClient())
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


def _get(client, upload_id=CUR):
    return client.get("/ratings/previous-for-viewer", params={"upload_id": upload_id})


def test_coefficient_follows_the_person_not_the_group(api):
    body = _get(api(_user("supervisor", [G_NEW]))).json()
    by_fio = {r["fio"]: r for r in body["rows"]}
    # перешедший из другой группы: его прошлый коэффициент и место доступны
    assert by_fio["Перешедший"]["coefficient"] == 1.2 and by_fio["Перешедший"]["final_place"] == 6
    assert by_fio["Свой"]["coefficient"] == 1.3
    assert body["prev_upload"] == {"id": PREV, "period_label": "10-5"}


def test_only_people_from_the_current_table_are_returned(api):
    fios = {r["fio"] for r in _get(api(_user("supervisor", [G_NEW]))).json()["rows"]}
    assert "Чужой" not in fios                              # человек из чужой группы
    assert "Коллега по прошлой группе" not in fios          # был в той же прошлой группе, но в нынешней таблице его нет
    assert fios == {"Перешедший", "Свой", "Новичок"}


def test_both_rows_of_a_novice_come_back_so_the_main_one_can_be_preferred(api):
    rows = [r for r in _get(api(_user("supervisor", [G_NEW]))).json()["rows"] if r["fio"] == "Новичок"]
    assert sorted(r["is_novice"] for r in rows) == [False, True]


def test_previous_period_is_the_nearest_earlier_one_and_ties_take_the_latest_upload(api):
    # у 10-5 две загрузки: берётся более поздняя (07:23), не дубль (07:04) и не 10-4
    rows = _get(api(_user("supervisor", [G_NEW]))).json()["rows"]
    assert {r["fio"]: r["coefficient"] for r in rows}["Перешедший"] == 1.2


def test_day_period_uses_the_previous_day_and_period_without_previous_is_empty(api):
    body = _get(api(_user("supervisor", [G_NEW])), upload_id=DAY).json()
    assert body == {"prev_upload": None, "rows": []}                    # раньше 2026-11-04 дней в базе нет
    first = _get(api(_user("supervisor", [G_NEW])), upload_id=OLDER).json()
    assert first["prev_upload"] is None


def test_wildcard_sees_everyone_and_sector_head_sees_the_sector_pair(api):
    g2, g3 = sorted(SECTOR_2_SUPERVISORS)[0], sorted(SECTOR_3_SUPERVISORS)[0]
    ratings_ = {
        CUR: [_r("Из Сектора 2", g2), _r("Из Сектора 3", g3), _r("Из Сектора 1", G_OTHER)],
        PREV: [_r("Из Сектора 2", G_OTHER, coefficient=1.3), _r("Из Сектора 3", g3, coefficient=1.2), _r("Из Сектора 1", G_OTHER, coefficient=1.1)],
    }
    star = _get(api(_user("supervisor", ["*"]), FakeClient(ratings_=ratings_))).json()
    assert {r["fio"] for r in star["rows"]} == {"Из Сектора 2", "Из Сектора 3", "Из Сектора 1"}
    head = _get(api(_user("supervisor", sorted(SECTOR_2_SUPERVISORS)), FakeClient(ratings_=ratings_))).json()
    assert {r["fio"] for r in head["rows"]} == {"Из Сектора 2", "Из Сектора 3"}          # пара секторов, Сектор 1 — нет
    # и сотрудник, ПЕРЕШЕДШИЙ в сектор из чужой группы, получает свой прошлый коэффициент
    assert {r["fio"]: r["coefficient"] for r in head["rows"]}["Из Сектора 2"] == 1.3


def test_forbidden_for_non_supervisors_and_profiles_without_groups(api):
    for user in (_user("admin"), _user("manager"), _user("supervisor", None), _user("supervisor", [])):
        assert _get(api(user)).status_code == 403


def test_unknown_and_malformed_upload_ids_are_404(api):
    client = api(_user("supervisor", [G_NEW]))
    assert _get(client, "00000000-0000-0000-0000-0000000000ff").status_code == 404
    assert _get(client, "not-a-uuid").status_code == 404
    assert _get(client, "1;drop").status_code == 404


def test_reads_all_pages_of_large_periods(api):
    cur = [_r(f"Ф{i}", G_NEW) for i in range(2300)]
    prev = [_r(f"Ф{i}", G_OLD, coefficient=1.1) for i in range(2300)]
    fake = FakeClient(ratings_={CUR: cur, PREV: prev})
    body = _get(api(_user("supervisor", [G_NEW]), fake)).json()
    assert len(body["rows"]) == 2300
    offsets = [c[1]["offset"] for c in fake.calls if c[0] == "kpi_ratings"]
    assert offsets == ["0", "1000", "2000", "0", "1000", "2000"]
