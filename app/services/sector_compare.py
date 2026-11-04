"""
Сравнение секторов, супервайзеров и операторов между собой — БЕЗ денег (ни
ЗП, ни бонусов, ни ЛГ/коэффициентов). Видят админ, менеджер и руководители
секторов (routers/dashboards.py::GET /dashboards/sectors).

Три уровня и один способ счёта на всех:
  операторы     — каждый оценённый сотрудник всех секторов;
  супервайзеры  — группы (метрики = средние по оценённым людям группы);
  секторы       — Сектор №1 (все остальные обычные группы), №2, №3 (метрики =
                  средние по оценённым людям сектора).

Почему отдельная "единая формула", а не итоговые баллы из рейтинга: у
секторов разные правила (в Секторе 2 ЛК не в счёте, новички оцениваются
по-разному) и теперь РАЗНЫЕ ВЕСА (конструктор сектора, sector_weights.py) —
итоговые баллы разных секторов несопоставимы. Поэтому для сравнения места по
каждой категории считаются заново по ВСЕЙ выборке (все сектора разом), а
сумма берётся с ФИКСИРОВАННЫМИ весами, не зависящими от настроек секторов:

  1 обращение ×3, Радио+ТВ ×2.5, Интернет ×2.5, время ×1, ошибки ×1.

ЛК в единый балл НЕ входит (в Секторе 2 она не применима), но показывается
отдельной сырой метрикой. Чем МЕНЬШЕ балл, тем лучше место — как в рейтинге.

Периоды до перехода на две категории канала (нет radio_*/inet_*) считаются
в режиме "legacy": единый канал группы (ch_*) с весом 2.5 вместо двух
отдельных.

Отбор людей — evaluated_unique_rows (services/dashboards.py): не Н/О, без
Региона УК/ПП/Увеличителей/Васько, один человек = одна строка.
"""
from __future__ import annotations

import re

from app.services.dashboards import evaluated_unique_rows
from app.services.group_naming import display_group_name
from app.services.rating_engine import rank_standard
from app.services.sector_weights import SECTOR_NAMES, sector_of_supervisor
from app.services.tier_channel import compute_tiered_channel_places

UNIFIED_WEIGHTS_DUAL = {"c1": 3.0, "radio": 2.5, "inet": 2.5, "time": 1.0, "errors": 1.0}
UNIFIED_WEIGHTS_LEGACY = {"c1": 3.0, "ch": 2.5, "time": 1.0, "errors": 1.0}
CATEGORY_LABELS = {
    "c1": "1 обращение", "radio": "Радио+ТВ", "inet": "Интернет", "ch": "Канал группы",
    "time": "Время/контакт", "errors": "% ошибок",
}

# Те же "особые" супервайзеры, что в "Рейтинге супервайзеров" (JS:
# specialSupervisorLabel): в сравнении групп они показываются, но места не
# получают и в выборку для мест не входят; их люди в секторных средних и в
# списке операторов учитываются как обычно. "курбанова зарина", а не голое
# "курбанова" — есть другой супервайзер "Курбанова 2 Анастасия".
_SPECIAL_SUPERVISORS = (
    (re.compile(r"курбанова\s+зарина", re.IGNORECASE), "Лидер"),
    (re.compile(r"клюйко", re.IGNORECASE), "Старший тренер"),
    (re.compile(r"лиштва", re.IGNORECASE), "Лидер"),
)


def special_supervisor_label(supervisor: str | None) -> str | None:
    for pattern, label in _SPECIAL_SUPERVISORS:
        if pattern.search(supervisor or ""):
            return label
    return None


def _num(value) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _is_dual(row: dict) -> bool:
    return row.get("radio_place") is not None or row.get("inet_place") is not None


def _channels(mode: str) -> tuple[str, ...]:
    return ("radio", "inet") if mode == "dual" else ("ch",)


def _row_metrics(row: dict, mode: str) -> dict:
    m = {
        "c1_sum": _num(row.get("c1_sum")), "c1_pc": _num(row.get("c1_per_contact")), "c1_conv": _num(row.get("c1_conv")),
        "lk_sum": _num(row.get("lk_sum")), "lk_cards": _num(row.get("lk_cards")), "lk_pc": _num(row.get("lk_per_contact")),
        "time": _num(row.get("time_per_contact")), "errors_pct": _num(row.get("errors_pct")),
    }
    for ch in _channels(mode):
        m[f"{ch}_sum"] = _num(row.get(f"{ch}_sum"))
        m[f"{ch}_cards"] = _num(row.get(f"{ch}_cards"))
        m[f"{ch}_pc"] = _num(row.get(f"{ch}_per_contact"))
        m[f"{ch}_conv"] = _num(row.get(f"{ch}_conv"))
    return m


def _worked(m: dict, prefix: str) -> bool:
    """Работал по каналу/ЛК: оборот или карточки > 0 (нули тех, кто канал не
    обслуживает, не должны занижать среднее "с контакта")."""
    return m.get(f"{prefix}_sum", 0) > 0 or m.get(f"{prefix}_cards", 0) > 0


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _aggregate(rows: list[dict], mode: str) -> dict:
    """Метрики группы/сектора: средние по оценённым людям. По каналу и ЛК —
    среднее только по тем, кто с ними работал (None, если таких нет)."""
    ms = [_row_metrics(r, mode) for r in rows]
    out = {
        "c1_sum": sum(m["c1_sum"] for m in ms),
        "c1_pc": _mean([m["c1_pc"] for m in ms]),
        "c1_conv": _mean([m["c1_conv"] for m in ms]),
        "time": _mean([m["time"] for m in ms]),
        "errors_pct": _mean([m["errors_pct"] for m in ms]),
    }
    lk = [m for m in ms if _worked(m, "lk")]
    out["lk_pc"] = _mean([m["lk_pc"] for m in lk])
    for ch in _channels(mode):
        workers = [m for m in ms if _worked(m, ch)]
        out[f"{ch}_sum"] = sum(m[f"{ch}_sum"] for m in ms)
        out[f"{ch}_workers"] = len(workers)
        out[f"{ch}_pc"] = _mean([m[f"{ch}_pc"] for m in workers])
        out[f"{ch}_conv"] = _mean([m[f"{ch}_conv"] for m in workers])
    return out


def _flat_places(metrics: list[dict], mode: str) -> list[dict]:
    """Места среди групп/секторов: обычный спортивный ранг по каждой категории
    (у кого по каналу нет работавших — значение 0, то есть последнее место)."""
    places: list[dict] = [{} for _ in metrics]
    series = {"c1": ([m["c1_pc"] or 0 for m in metrics], "desc")}
    for ch in _channels(mode):
        series[ch] = ([m[f"{ch}_pc"] or 0 for m in metrics], "desc")
    series["time"] = ([m["time"] or 0 for m in metrics], "asc")
    series["errors"] = ([m["errors_pct"] or 0 for m in metrics], "asc")
    for key, (values, direction) in series.items():
        for i, v in enumerate(values):
            places[i][key] = rank_standard(values, v, direction)
    return places


def _operator_places(metrics: list[dict], mode: str) -> list[dict]:
    """Места операторов по всей выборке. Канал — с тиром A/Б/В (карточки и
    конверсия), как в рейтинге (tier_channel.py): у кого карточек нет, делят
    одно место после тех, кто продавал; впустую потраченные — последние."""
    places: list[dict] = [{} for _ in metrics]
    c1 = [m["c1_pc"] for m in metrics]
    time_values = [m["time"] for m in metrics]
    errors = [m["errors_pct"] for m in metrics]
    for i, m in enumerate(metrics):
        places[i]["c1"] = rank_standard(c1, m["c1_pc"], "desc")
        places[i]["time"] = rank_standard(time_values, m["time"], "asc")
        places[i]["errors"] = rank_standard(errors, m["errors_pct"], "asc")
    for ch in _channels(mode):
        tiered = compute_tiered_channel_places([
            {"ch_cards": m[f"{ch}_cards"], "ch_conv": m[f"{ch}_conv"], "ch_per_contact": m[f"{ch}_pc"]}
            for m in metrics
        ])
        for i, place in enumerate(tiered):
            places[i][ch] = int(place)
    return places


def _score(places: dict, weights: dict) -> float:
    return sum(weights[key] * places[key] for key in weights)


def _assign_place(entries: list[dict]) -> None:
    """entries с полем score (None — не участвует): place = спортивный ранг
    по возрастанию балла."""
    scores = [e["score"] for e in entries if e["score"] is not None]
    for e in entries:
        e["place"] = rank_standard(scores, e["score"], "asc") if e["score"] is not None else None


def _sort_key(entry: dict, tie_value: float):
    return (entry["place"] is None, entry["place"] or 0, -tie_value)


def build_sector_comparison(ratings: list[dict]) -> dict:
    """ratings — строки kpi_ratings ОДНОГО периода (все сектора). Возвращает
    {mode, weights, labels, sectors, supervisors, operators, totals} — без
    денег и ЛГ."""
    rows = evaluated_unique_rows(ratings)
    mode = "dual" if any(_is_dual(r) for r in rows) else "legacy"
    weights = UNIFIED_WEIGHTS_DUAL if mode == "dual" else UNIFIED_WEIGHTS_LEGACY

    # ---- операторы
    op_metrics = [_row_metrics(r, mode) for r in rows]
    op_places = _operator_places(op_metrics, mode) if rows else []
    operators = []
    for r, m, p in zip(rows, op_metrics, op_places):
        operators.append({
            "fio": r.get("fio"),
            "group": display_group_name(r.get("supervisor")),
            "sector": sector_of_supervisor(r.get("supervisor")),
            "status": r.get("status"),
            "metrics": m,
            "places": p,
            "score": _score(p, weights),
        })
    _assign_place(operators)
    operators.sort(key=lambda e: (*_sort_key(e, e["metrics"]["c1_pc"]), e["fio"] or ""))

    # ---- супервайзеры (группы)
    by_group: dict[str, list[dict]] = {}
    for r in rows:
        by_group.setdefault(r.get("supervisor"), []).append(r)
    supervisors = []
    for supervisor, group_rows in by_group.items():
        label = special_supervisor_label(supervisor)
        supervisors.append({
            "name": display_group_name(supervisor),
            "sector": sector_of_supervisor(supervisor),
            "people": len(group_rows),
            "metrics": _aggregate(group_rows, mode),
            "special_label": label,
            "places": None,
            "score": None,
        })
    ranked = [s for s in supervisors if not s["special_label"]]
    for s, p in zip(ranked, _flat_places([s["metrics"] for s in ranked], mode)):
        s["places"] = p
        s["score"] = _score(p, weights)
    _assign_place(supervisors)
    supervisors.sort(key=lambda e: (*_sort_key(e, e["metrics"]["c1_pc"] or 0), e["name"]))

    # ---- секторы
    sectors = []
    for sector in sorted({sector_of_supervisor(sup) for sup in by_group}):
        sector_rows = [r for r in rows if sector_of_supervisor(r.get("supervisor")) == sector]
        sectors.append({
            "sector": sector,
            "name": SECTOR_NAMES[sector],
            "groups": sum(1 for sup in by_group if sector_of_supervisor(sup) == sector),
            "people": len(sector_rows),
            "metrics": _aggregate(sector_rows, mode),
        })
    for s, p in zip(sectors, _flat_places([s["metrics"] for s in sectors], mode)):
        s["places"] = p
        s["score"] = _score(p, weights)
    _assign_place(sectors)
    sectors.sort(key=lambda e: (*_sort_key(e, e["metrics"]["c1_pc"] or 0), e["sector"]))

    return {
        "mode": mode,
        "weights": weights,
        "labels": {k: CATEGORY_LABELS[k] for k in weights},
        "sectors": sectors,
        "supervisors": supervisors,
        "operators": operators,
        "totals": {"operators": len(operators), "groups": len(supervisors)},
    }


__all__ = ["build_sector_comparison", "special_supervisor_label", "UNIFIED_WEIGHTS_DUAL", "UNIFIED_WEIGHTS_LEGACY"]
