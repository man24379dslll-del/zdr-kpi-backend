from app.services.group_naming import display_group_name, is_region_uk_or_peaks_supervisor


def test_region_uk_and_peaks_are_both_detected():
    assert is_region_uk_or_peaks_supervisor("операторы без супервизора") is True
    assert is_region_uk_or_peaks_supervisor("операторы без супервизора [Пики]") is True


def test_normal_supervisor_is_not_region_uk():
    assert is_region_uk_or_peaks_supervisor("Супервайзер - Иванов Иван Иванович") is False
    assert is_region_uk_or_peaks_supervisor(None) is False
    assert is_region_uk_or_peaks_supervisor("") is False


def test_display_group_name_maps_virtual_groups():
    assert display_group_name("операторы без супервизора") == "Регион УК"
    assert display_group_name("операторы без супервизора [Пики]") == "Выходы на Пики"


def test_display_group_name_passes_through_normal_supervisor():
    assert display_group_name("Супервайзер - Иванов Иван Иванович") == "Супервайзер - Иванов Иван Иванович"


def test_display_group_name_is_case_insensitive():
    assert display_group_name("ОПЕРАТОРЫ БЕЗ СУПЕРВИЗОРА") == "Регион УК"
    assert display_group_name("Операторы Без Супервизора [пики]") == "Выходы на Пики"
