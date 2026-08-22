"""resolve_supervisor_names — чистая логика выбора supervisor_names
(массив, источник истины) vs supervisor_name (старое, одна строка,
фоллбэк) из профиля user_profiles. Сама фильтрация "кто что видит"
(один элемент = как раньше; несколько = видит все перечисленные, не
видит остальные) — на стороне RLS-политики "ratings_select" в Postgres
(см. app/db/schema.sql), не в Python-коде — это НЕ дублируется здесь и
не может быть проверено без реального Supabase."""
from app.auth import resolve_supervisor_names


def test_uses_supervisor_names_array_when_present():
    profile = {"supervisor_names": ["Супервайзер - Иванов И.И."], "supervisor_name": "Супервайзер - Иванов И.И."}
    assert resolve_supervisor_names(profile) == ["Супервайзер - Иванов И.И."]


def test_multiple_supervisor_names_all_kept():
    # Несколько РАЗНЫХ реальных групп у одного человека (не подгруппы одной
    # и той же группы — например, Курбанова Зарина ведёт свою группу И
    # видит группу другого супервайзера).
    profile = {
        "supervisor_names": [
            "Супервайзер - Курбанова Зарина Рахимджановна",
            "Супервайзер - Курбанова 2 Анастасия Анатольевна",
        ],
    }
    result = resolve_supervisor_names(profile)
    assert result == [
        "Супервайзер - Курбанова Зарина Рахимджановна",
        "Супервайзер - Курбанова 2 Анастасия Анатольевна",
    ]
    assert len(result) == 2


def test_falls_back_to_single_supervisor_name_when_array_missing():
    # Профиль ещё не тронут миграцией (supervisor_names=null/отсутствует) —
    # ведёт себя так же, как раньше: одна группа.
    profile = {"supervisor_name": "Супервайзер - Петров П.П."}
    assert resolve_supervisor_names(profile) == ["Супервайзер - Петров П.П."]


def test_falls_back_when_supervisor_names_is_explicitly_null():
    profile = {"supervisor_names": None, "supervisor_name": "Супервайзер - Петров П.П."}
    assert resolve_supervisor_names(profile) == ["Супервайзер - Петров П.П."]


def test_falls_back_when_supervisor_names_is_empty_list():
    profile = {"supervisor_names": [], "supervisor_name": "Супервайзер - Петров П.П."}
    assert resolve_supervisor_names(profile) == ["Супервайзер - Петров П.П."]


def test_none_when_neither_field_set():
    # admin/manager — видят всё, никакая группа не привязана
    profile = {"supervisor_names": None, "supervisor_name": None}
    assert resolve_supervisor_names(profile) is None


def test_none_when_fields_absent_entirely():
    assert resolve_supervisor_names({}) is None
