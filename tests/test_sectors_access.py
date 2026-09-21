"""
Руководители Секторов 2 и 3 (аккаунты Бочиус Е.М. / Сорокин Н.) — по
прямому запросу заказчика получают просмотр (НЕ запись) Ведомости ЗП,
ограниченный только группами своего сектора. См.
auth.py::CurrentUser.is_sector2_head/is_sector3_head и
routers/payroll.py::_restrict_to_sector/_sector_supervisors_for.
"""
from app.auth import CurrentUser
from app.routers.payroll import _restrict_to_sector, _sector_supervisors_for
from app.services.group_naming import SECTOR_2_SUPERVISORS, SECTOR_3_SUPERVISORS

SECTOR2_LIST = sorted(SECTOR_2_SUPERVISORS)
SECTOR3_LIST = sorted(SECTOR_3_SUPERVISORS)


def _user(role, supervisor_names):
    return CurrentUser(
        access_token="t", user_id="u", email="e@e.com",
        role=role, supervisor_names=supervisor_names, display_name="Test",
    )


def test_is_sector2_head_true_for_exact_match():
    user = _user("supervisor", list(SECTOR2_LIST))
    assert user.is_sector2_head is True


def test_is_sector2_head_true_regardless_of_order():
    user = _user("supervisor", list(reversed(SECTOR2_LIST)))
    assert user.is_sector2_head is True


def test_is_sector2_head_false_for_admin_even_with_matching_names():
    # Роль важна: admin/manager уже видят всё без ограничений, is_sector2_head
    # тут не должен неожиданно ЗАУЗИТЬ им доступ где-то ещё в коде.
    user = _user("admin", list(SECTOR2_LIST))
    assert user.is_sector2_head is False


def test_is_sector2_head_false_for_normal_supervisor():
    user = _user("supervisor", ["Супервайзер - Иванов И.И."])
    assert user.is_sector2_head is False


def test_is_sector2_head_false_for_partial_sector2_match():
    # Только 1 из 4 групп сектора — НЕ считается руководителем сектора
    # (это была бы обычная группа внутри сектора, не весь сектор).
    user = _user("supervisor", [SECTOR2_LIST[0]])
    assert user.is_sector2_head is False


def test_is_sector2_head_false_for_sector2_plus_extra_group():
    # 4 группы сектора + ещё одна ЛИШНЯЯ — тоже не считается: точное
    # совпадение множества, не "содержит сектор 2".
    user = _user("supervisor", list(SECTOR2_LIST) + ["Супервайзер - Иванов И.И."])
    assert user.is_sector2_head is False


def test_is_sector2_head_false_for_none_supervisor_names():
    user = _user("supervisor", None)
    assert user.is_sector2_head is False


def test_is_sector3_head_true_for_exact_match():
    user = _user("supervisor", list(SECTOR3_LIST))
    assert user.is_sector3_head is True


def test_is_sector3_head_false_for_sector2_head():
    # Руководитель Сектора 2 — не руководитель Сектора 3, и наоборот.
    user = _user("supervisor", list(SECTOR2_LIST))
    assert user.is_sector3_head is False
    user2 = _user("supervisor", list(SECTOR3_LIST))
    assert user2.is_sector2_head is False


def test_is_sector3_head_false_for_partial_match():
    user = _user("supervisor", [SECTOR3_LIST[0]])
    assert user.is_sector3_head is False


def test_sector_supervisors_for_picks_right_set():
    assert _sector_supervisors_for(_user("supervisor", list(SECTOR2_LIST))) == SECTOR_2_SUPERVISORS
    assert _sector_supervisors_for(_user("supervisor", list(SECTOR3_LIST))) == SECTOR_3_SUPERVISORS
    assert _sector_supervisors_for(_user("supervisor", ["Супервайзер - Иванов И.И."])) is None
    assert _sector_supervisors_for(_user("admin", None)) is None


def test_restrict_to_sector_filters_rows_by_supervisor():
    result = {
        "rows": [
            {"fio": "А", "supervisor": SECTOR2_LIST[0], "sum": 100},
            {"fio": "Б", "supervisor": "Супервайзер - Иванов И.И.", "sum": 200},
            {"fio": "В", "supervisor": SECTOR2_LIST[1], "sum": 300},
            {"fio": "Г", "supervisor": SECTOR3_LIST[0], "sum": 400},
        ],
        "month": 9, "year": 2026,
    }
    restricted_1 = _restrict_to_sector(dict(result), SECTOR_2_SUPERVISORS)
    assert {r["fio"] for r in restricted_1["rows"]} == {"А", "В"}
    assert restricted_1["month"] == 9  # остальные поля не трогаются
    assert restricted_1["year"] == 2026

    restricted_2 = _restrict_to_sector(dict(result), SECTOR_3_SUPERVISORS)
    assert {r["fio"] for r in restricted_2["rows"]} == {"Г"}
