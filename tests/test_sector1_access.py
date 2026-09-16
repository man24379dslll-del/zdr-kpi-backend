"""
Руководитель Сектора 1 (аккаунт Бочиус Е.М.) — по прямому запросу
заказчика получает просмотр (НЕ запись) Ведомости ЗП, ограниченный
только 4 группами Сектора 1. См. auth.py::CurrentUser.is_sector1_head и
routers/payroll.py::_restrict_to_sector1.
"""
from app.auth import CurrentUser
from app.routers.payroll import _restrict_to_sector1
from app.services.group_naming import SECTOR_1_SUPERVISORS

SECTOR1_LIST = sorted(SECTOR_1_SUPERVISORS)


def _user(role, supervisor_names):
    return CurrentUser(
        access_token="t", user_id="u", email="e@e.com",
        role=role, supervisor_names=supervisor_names, display_name="Test",
    )


def test_is_sector1_head_true_for_exact_match():
    user = _user("supervisor", list(SECTOR1_LIST))
    assert user.is_sector1_head is True


def test_is_sector1_head_true_regardless_of_order():
    user = _user("supervisor", list(reversed(SECTOR1_LIST)))
    assert user.is_sector1_head is True


def test_is_sector1_head_false_for_admin_even_with_matching_names():
    # Роль важна: admin/manager уже видят всё без ограничений, is_sector1_head
    # тут не должен неожиданно ЗАУЗИТЬ им доступ где-то ещё в коде.
    user = _user("admin", list(SECTOR1_LIST))
    assert user.is_sector1_head is False


def test_is_sector1_head_false_for_normal_supervisor():
    user = _user("supervisor", ["Супервайзер - Иванов И.И."])
    assert user.is_sector1_head is False


def test_is_sector1_head_false_for_partial_sector1_match():
    # Только 1 из 4 групп сектора — НЕ считается руководителем сектора
    # (это была бы обычная группа внутри сектора, не весь сектор).
    user = _user("supervisor", [SECTOR1_LIST[0]])
    assert user.is_sector1_head is False


def test_is_sector1_head_false_for_sector1_plus_extra_group():
    # 4 группы сектора + ещё одна ЛИШНЯЯ — тоже не считается: точное
    # совпадение множества, не "содержит сектор 1".
    user = _user("supervisor", list(SECTOR1_LIST) + ["Супервайзер - Иванов И.И."])
    assert user.is_sector1_head is False


def test_is_sector1_head_false_for_none_supervisor_names():
    user = _user("supervisor", None)
    assert user.is_sector1_head is False


def test_restrict_to_sector1_filters_rows_by_supervisor():
    result = {
        "rows": [
            {"fio": "А", "supervisor": SECTOR1_LIST[0], "sum": 100},
            {"fio": "Б", "supervisor": "Супервайзер - Иванов И.И.", "sum": 200},
            {"fio": "В", "supervisor": SECTOR1_LIST[1], "sum": 300},
        ],
        "month": 9, "year": 2026,
    }
    restricted = _restrict_to_sector1(result)
    fios = {r["fio"] for r in restricted["rows"]}
    assert fios == {"А", "В"}
    # Остальные поля результата (month/year и т.п.) не трогаются
    assert restricted["month"] == 9
    assert restricted["year"] == 2026
