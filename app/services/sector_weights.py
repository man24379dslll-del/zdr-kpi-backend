"""
Веса категорий рейтинга ПО СЕКТОРАМ — чистая логика без сети; ходит в
Supabase только routers/sector_weights.py.

Раньше в расчёте были зашиты веса 3 / 1.5 / 2.5 / 1 / 1 (то же в JS и в
Python), а "Конструктор рейтинга" (rating_categories) на расчёт в браузере
не влиял. Теперь у каждого сектора свои веса шести категорий:

  c1      — 1 обращение          lk     — ЛК
  radio   — Радио+ТВ             inet   — Интернет
  time    — время на контакт     errors — % ошибок

Сектор 1 — все обычные группы, не вошедшие в Сектор 2 и 3 (и виртуальные
группы Регион УК/ПП/Увеличители: их набор категорий в сумме урезан отдельно,
см. group_naming.REGION_UK_SCORE_KEYS/PEAKS_SCORE_KEYS, а веса — сектора 1).
Вес 0 выключает категорию в итоговой сумме (место по ней всё равно
считается и показывается). Для Сектора 2 вес ЛК, как и раньше, действует
только на 3 сотрудников-исключений (group_naming.SECTOR_2_LK_WEIGHT_EXCEPTIONS_FIO).

Изменение весов — запись в журнал sector_weight_changes (кто, когда, какие
значения). Руководитель сектора создаёт заявку (pending), админ/менеджер
подтверждает; админ/менеджер может поменять сразу. Действующие веса
сектора = значения последней подтверждённой (approved) записи, иначе
DEFAULT_WEIGHTS. Применяются только к будущим загрузкам; веса, по которым
посчитан каждый период, сохраняются в kpi_uploads.weights_snapshot.
"""
from __future__ import annotations

import math

from app.services.group_naming import SECTOR_2_SUPERVISORS, SECTOR_3_SUPERVISORS

SECTOR_NUMBERS = (1, 2, 3)
SECTOR_NAMES = {1: "Сектор №1 (остальные группы)", 2: "Сектор №2", 3: "Сектор №3"}

WEIGHT_KEYS = ("c1", "lk", "radio", "inet", "time", "errors")
WEIGHT_LABELS = {
    "c1": "1 обращение", "lk": "ЛК", "radio": "Радио+ТВ", "inet": "Интернет",
    "time": "Время/контакт", "errors": "% ошибок",
}
DEFAULT_WEIGHTS = {"c1": 3.0, "lk": 1.5, "radio": 2.5, "inet": 2.5, "time": 1.0, "errors": 1.0}
MAX_WEIGHT = 10.0

STATUSES = ("pending", "approved", "rejected", "cancelled")


class WeightsValidationError(ValueError):
    pass


def sector_of_supervisor(supervisor: str | None) -> int:
    """Сектор группы: 2 или 3 — по точному названию группы, иначе 1."""
    if supervisor in SECTOR_2_SUPERVISORS:
        return 2
    if supervisor in SECTOR_3_SUPERVISORS:
        return 3
    return 1


def validate_weights(weights) -> dict[str, float]:
    """Ровно шесть ключей, числа 0..MAX_WEIGHT (округляем до сотых), и хотя
    бы одна категория кроме ЛК с положительным весом (иначе итоговая сумма
    у всех нулевая, а в Секторе 2 ЛК вообще не в счёте)."""
    if not isinstance(weights, dict):
        raise WeightsValidationError("weights должен быть объектом")
    if set(weights) != set(WEIGHT_KEYS):
        raise WeightsValidationError(f"Нужны ровно категории: {', '.join(WEIGHT_KEYS)}")
    clean: dict[str, float] = {}
    for key in WEIGHT_KEYS:
        value = weights[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise WeightsValidationError(f"Вес «{WEIGHT_LABELS[key]}» должен быть числом")
        if value < 0 or value > MAX_WEIGHT:
            raise WeightsValidationError(f"Вес «{WEIGHT_LABELS[key]}» должен быть от 0 до {MAX_WEIGHT:g}")
        clean[key] = round(float(value), 2)
    if not any(clean[key] > 0 for key in WEIGHT_KEYS if key != "lk"):
        raise WeightsValidationError("Хотя бы одна категория, кроме ЛК, должна иметь вес больше 0")
    return clean


def weights_equal(a: dict, b: dict) -> bool:
    return all(abs(float(a[k]) - float(b[k])) < 1e-9 for k in WEIGHT_KEYS)


def effective_weights(changes: list[dict]) -> dict[int, dict]:
    """Действующие веса по секторам. changes — строки sector_weight_changes
    (любые статусы): берётся подтверждённая запись с самой поздней датой
    решения; нет такой — стандартные веса (source 'default')."""
    result: dict[int, dict] = {}
    for sector in SECTOR_NUMBERS:
        approved = [c for c in changes if c.get("sector") == sector and c.get("status") == "approved"]
        approved.sort(key=lambda c: (c.get("decided_at") or c.get("requested_at") or ""))
        if approved:
            last = approved[-1]
            result[sector] = {
                "weights": validate_weights(last["weights"]),
                "source": "approved",
                "change_id": last.get("id"),
                "decided_at": last.get("decided_at"),
            }
        else:
            result[sector] = {"weights": dict(DEFAULT_WEIGHTS), "source": "default", "change_id": None, "decided_at": None}
    return result


def snapshot_of(effective: dict[int, dict]) -> dict[str, dict]:
    """Что пишем в kpi_uploads.weights_snapshot: веса каждого сектора на
    момент расчёта (и id подтверждённой записи — для разбора спорных случаев)."""
    return {
        str(sector): {"weights": eff["weights"], "change_id": eff.get("change_id")}
        for sector, eff in effective.items()
    }


def parse_snapshot(snapshot) -> dict[int, dict[str, float]]:
    """Проверка снимка, пришедшего от клиента (save-computed). Возвращает
    {сектор: веса}; любое нарушение формата — WeightsValidationError."""
    if not isinstance(snapshot, dict) or set(snapshot) != {str(s) for s in SECTOR_NUMBERS}:
        raise WeightsValidationError("Снимок весов должен содержать все три сектора")
    parsed: dict[int, dict[str, float]] = {}
    for sector in SECTOR_NUMBERS:
        item = snapshot[str(sector)]
        if not isinstance(item, dict):
            raise WeightsValidationError("Некорректный снимок весов")
        parsed[sector] = validate_weights(item.get("weights"))
    return parsed


def lk_off_in_snapshot(snapshot) -> bool:
    """ЛК выключена (вес 0) у ВСЕХ секторов периода — по снимку весов
    kpi_uploads.weights_snapshot. Нет снимка (период до конструктора
    секторов) или он некорректен — ЛК считалась, False."""
    try:
        parsed = parse_snapshot(snapshot)
    except WeightsValidationError:
        return False
    return all(parsed[sector]["lk"] == 0 for sector in SECTOR_NUMBERS)


def weights_by_sector(effective: dict[int, dict]) -> dict[int, dict[str, float]]:
    return {sector: eff["weights"] for sector, eff in effective.items()}


async def load_effective(client) -> dict[int, dict]:
    """Действующие веса из Supabase (client — SupabaseClient; тип не
    импортируем, чтобы чистая логика выше не требовала .env)."""
    changes = await client.get(
        "sector_weight_changes",
        params={"select": "*", "status": "eq.approved", "order": "decided_at.desc", "limit": "300"},
    )
    return effective_weights(changes)
