from app.services.group_naming import (
    PEAKS_GROUP_RE,
    clean_supervisor_name,
    display_group_name,
    is_region_uk_or_peaks_supervisor,
)


def test_region_uk_and_peaks_are_both_detected():
    assert is_region_uk_or_peaks_supervisor("операторы без супервизора") is True
    assert is_region_uk_or_peaks_supervisor("операторы без супервизора [Пики-ПП]") is True
    assert is_region_uk_or_peaks_supervisor("операторы без супервизора [Пики-Увеличители]") is True


def test_normal_supervisor_is_not_region_uk():
    assert is_region_uk_or_peaks_supervisor("Супервайзер - Иванов Иван Иванович") is False
    assert is_region_uk_or_peaks_supervisor(None) is False
    assert is_region_uk_or_peaks_supervisor("") is False


def test_display_group_name_maps_virtual_groups():
    assert display_group_name("операторы без супервизора") == "Уволенные/Нераспределенные"
    assert display_group_name("операторы без супервизора [Пики-ПП]") == "ПП"
    assert display_group_name("операторы без супервизора [Пики-Увеличители]") == "Увеличители"


def test_display_group_name_is_case_insensitive():
    assert display_group_name("ОПЕРАТОРЫ БЕЗ СУПЕРВИЗОРА") == "Уволенные/Нераспределенные"
    assert display_group_name("Операторы Без Супервизора [пики-пп]") == "ПП"
    assert display_group_name("Операторы Без Супервизора [пики-увеличители]") == "Увеличители"


def test_clean_supervisor_name_strips_known_prefixes():
    assert clean_supervisor_name("Супервайзер - Курбанова Зарина Рахимджановна") == "Курбанова Зарина Рахимджановна"
    assert clean_supervisor_name("Супервайзер.- Клюйко Анатолий Анатольевич") == "Клюйко Анатолий Анатольевич"
    assert clean_supervisor_name("Супервизор Галина Элина Альфредовна") == "Галина Элина Альфредовна"


def test_clean_supervisor_name_handles_missing_and_plain_names():
    assert clean_supervisor_name(None) == ""
    assert clean_supervisor_name("") == ""
    assert clean_supervisor_name("Иванов Иван Иванович") == "Иванов Иван Иванович"


def test_peaks_group_re_matches_both_pp_and_uvelichiteli_not_region_uk():
    # PEAKS_GROUP_RE — общий признак ОБЕИХ бывших "Пики"-подгрупп,
    # используется например в salary.py для исключения часовой ставки.
    # НЕ должен матчить голое "Регион УК" (у него часовая ставка обычная).
    assert PEAKS_GROUP_RE.search("операторы без супервизора [Пики-ПП]")
    assert PEAKS_GROUP_RE.search("операторы без супервизора [Пики-Увеличители]")
    assert not PEAKS_GROUP_RE.search("операторы без супервизора")
    assert not PEAKS_GROUP_RE.search("Супервайзер - Иванов Иван Иванович")


def test_display_group_name_cleans_normal_supervisor_prefix():
    assert display_group_name("Супервайзер - Иванов Иван Иванович") == "Иванов Иван Иванович"
    assert display_group_name("Супервизор Галина Элина Альфредовна") == "Галина Элина Альфредовна"
