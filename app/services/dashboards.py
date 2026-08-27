"""
4 дашборда поверх одного периода (upload) + опционально предыдущего того
же типа (для дельт): сводка, воронка новичков, каналы, аномалии.

Чистые функции — принимают уже готовые списки строк kpi_ratings (не
upload_id), тестируются без сети. Какой upload_id считать "предыдущим
того же типа" — решает вызывающий (routers/dashboards.py принимает его
явным параметром previous_upload_id): у фронтенда уже есть список
периодов, мы это здесь не угадываем.

Направление "лучше/хуже" для дельт (см. _delta): для total_score,
time_per_contact, errors_pct — меньше значит лучше; для остального
(c1/lk/channel per_contact, salary) — больше значит лучше.
"""
from __future__ import annotations

import re

from app.services.group_naming import display_group_name, is_region_uk_or_peaks_supervisor
from app.services.payroll import is_weekly_period_label

LOWER_IS_BETTER = {"total_score", "time_per_contact", "errors_pct"}

STATUS_METRICS = ("c1_per_contact", "lk_per_contact", "ch_per_contact", "time_per_contact", "errors_pct")

# Классификация новичков по c1_per_contact — не путать с обычными
# категориями рейтинга, это отдельная бизнес-классификация только для
# контроля новичков (воронка + "новички по супервизорам" в сводке).
CONV_BANDS = [
    {"max": 1608, "label": "Прекращение сотрудничества"},
    {"max": 2144, "label": "Предупреждение + 1 неделя"},
    {"max": 2680, "label": "Норма 1-й недели"},
    {"max": 3860, "label": "Сверх нормы"},
    {"max": float("inf"), "label": "Мы искали Вас!"},
]
WORST_CONV_BAND = CONV_BANDS[0]["label"]


def conv_band(c1_per_contact: float | None) -> str:
    value = c1_per_contact or 0
    for band in CONV_BANDS:
        if value < band["max"]:
            return band["label"]
    return CONV_BANDS[-1]["label"]


def _avg(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _sum(rows: list[dict], field: str) -> float:
    return sum((r.get(field) or 0) for r in rows)


def _delta(current: float | None, previous: float | None, metric: str) -> dict | None:
    if current is None or previous is None:
        return None
    diff = current - previous
    is_improvement = diff < 0 if metric in LOWER_IS_BETTER else diff > 0
    return {"diff": diff, "is_improvement": is_improvement}


def build_summary_dashboard(
    ratings: list[dict],
    period_label: str | None = None,
    previous_ratings: list[dict] | None = None,
) -> dict:
    """ratings/previous_ratings: строки kpi_ratings ОДНОГО периода (все —
    и новички, и основной состав; фильтрация по is_novice/is_na — внутри)."""
    main = [r for r in ratings if not r.get("is_novice")]
    evaluated = [r for r in main if not r.get("is_na")]
    novices = [r for r in ratings if r.get("is_novice")]

    has_previous = previous_ratings is not None
    prev_main = [r for r in (previous_ratings or []) if not r.get("is_novice")]
    prev_evaluated = [r for r in prev_main if not r.get("is_na")]

    avg_score = _avg([r.get("total_score") for r in evaluated])
    prev_avg_score = _avg([r.get("total_score") for r in prev_evaluated]) if has_previous else None

    is_weekly = is_weekly_period_label(period_label)
    salary_fund = sum((r.get("salary") or 0) for r in main) if is_weekly else None
    prev_salary_fund = sum((r.get("salary") or 0) for r in prev_main) if (is_weekly and has_previous) else None

    tier_distribution = {tier: 0 for tier in range(1, 11)}
    for r in evaluated:
        tier = r.get("tier")
        if tier in tier_distribution:
            tier_distribution[tier] += 1

    # По evaluated (не main!) — Н/О (тренеры/отпускники/больничные и т.п.)
    # искажали бы средние показатели статуса, если бы считались тут.
    statuses = sorted({r.get("status") for r in evaluated if r.get("status")})
    by_status = []
    for status_value in statuses:
        rows = [r for r in evaluated if r.get("status") == status_value]
        prev_rows = [r for r in prev_evaluated if r.get("status") == status_value] if has_previous else []
        entry: dict = {"status": status_value, "count": len(rows)}
        for metric in STATUS_METRICS:
            avg_now = _avg([r.get(metric) for r in rows])
            entry[f"avg_{metric}"] = avg_now
            if has_previous:
                entry[f"{metric}_delta"] = _delta(avg_now, _avg([r.get(metric) for r in prev_rows]), metric)
        by_status.append(entry)

    status_counts: dict[str, int] = {}
    for r in main:
        status_value = r.get("status") or "—"
        status_counts[status_value] = status_counts.get(status_value, 0) + 1

    by_supervisor: dict[str, dict] = {}
    for r in novices:
        supervisor = r.get("supervisor")
        if is_region_uk_or_peaks_supervisor(supervisor):
            continue
        entry = by_supervisor.setdefault(supervisor, {"supervisor": supervisor, "total": 0, "bad_count": 0})
        entry["total"] += 1
        if conv_band(r.get("c1_per_contact")) == WORST_CONV_BAND:
            entry["bad_count"] += 1
    novices_by_supervisor = sorted(by_supervisor.values(), key=lambda e: e["supervisor"] or "")
    for entry in novices_by_supervisor:
        entry["bad_pct"] = (entry["bad_count"] / entry["total"] * 100) if entry["total"] else 0.0

    return {
        "total_in_rating": len(main),
        "without_region_uk": sum(1 for r in main if not is_region_uk_or_peaks_supervisor(r.get("supervisor"))),
        "evaluated_count": len(evaluated),
        "avg_score": avg_score,
        "avg_score_delta": _delta(avg_score, prev_avg_score, "total_score") if has_previous else None,
        "salary_fund": salary_fund,
        "salary_fund_delta": _delta(salary_fund, prev_salary_fund, "salary") if has_previous else None,
        "tier_distribution": tier_distribution,
        "by_status": by_status,
        "status_counts": status_counts,
        "novices_by_supervisor": novices_by_supervisor,
    }


def build_newcomer_funnel(novices: list[dict], previous_novices: list[dict] | None = None) -> dict:
    """novices/previous_novices: строки kpi_ratings с is_novice=true."""
    grouped: dict[str, list[dict]] = {band["label"]: [] for band in CONV_BANDS}
    for r in novices:
        grouped[conv_band(r.get("c1_per_contact"))].append(r)

    prev_counts = None
    if previous_novices is not None:
        prev_counts = {band["label"]: 0 for band in CONV_BANDS}
        for r in previous_novices:
            prev_counts[conv_band(r.get("c1_per_contact"))] += 1

    bands_out = []
    for band in CONV_BANDS:
        label = band["label"]
        rows = sorted(grouped[label], key=lambda r: r.get("c1_per_contact") or 0, reverse=True)
        entry = {
            "label": label,
            "count": len(rows),
            "employees": [
                {
                    "fio": r.get("fio"),
                    "c1_per_contact": r.get("c1_per_contact"),
                    "group": display_group_name(r.get("supervisor")),
                }
                for r in rows
            ],
        }
        if prev_counts is not None:
            entry["count_delta"] = len(rows) - prev_counts[label]
        bands_out.append(entry)

    return {"bands": bands_out}


def build_channels_dashboard(ratings: list[dict]) -> dict:
    """ratings: строки kpi_ratings ОДНОГО периода; новички и Н/О исключаются."""
    main = [r for r in ratings if not r.get("is_novice") and not r.get("is_na")]
    by_channel: dict[str, list[dict]] = {}
    for r in main:
        by_channel.setdefault(r.get("channel") or "unknown", []).append(r)

    channels = []
    for channel, rows in by_channel.items():
        channels.append({
            "channel": channel,
            "count": len(rows),
            "avg_ch_per_contact": _avg([r.get("ch_per_contact") for r in rows]),
            "avg_ch_conv": _avg([r.get("ch_conv") for r in rows]),
            "sum_ch_sum": sum((r.get("ch_sum") or 0) for r in rows),
        })
    channels.sort(key=lambda c: c["channel"])
    return {"channels": channels}


def build_anomalies_dashboard(
    ratings: list[dict],
    previous_ratings: list[dict] | None = None,
    period_label: str | None = None,
    previous_period_label: str | None = None,
) -> list[dict]:
    """ratings: строки kpi_ratings ОДНОГО периода (не новички сравниваются
    с той же fio в previous_ratings, если она дана). period_label/
    previous_period_label — только для текста сообщения о нулевых продажах,
    на саму логику не влияют."""
    main = [r for r in ratings if not r.get("is_novice")]
    prev_by_fio = {r.get("fio"): r for r in (previous_ratings or [])}

    anomalies = []
    for r in main:
        fio = r.get("fio")
        group = display_group_name(r.get("supervisor"))
        prev = prev_by_fio.get(fio)

        if prev is not None:
            final_place = r.get("final_place")
            prev_final_place = prev.get("final_place")
            if (
                final_place is not None
                and prev_final_place is not None
                and not r.get("is_na")
                and not prev.get("is_na")
                and (final_place - prev_final_place) >= 10
            ):
                anomalies.append({
                    "fio": fio,
                    "group": group,
                    "severity": "err",
                    "reason": (
                        f"Резкое падение: было место {prev_final_place}, "
                        f"стало {final_place} (−{final_place - prev_final_place})"
                    ),
                })

            if (r.get("c1_sum") or 0) == 0 and (prev.get("c1_sum") or 0) == 0:
                anomalies.append({
                    "fio": fio, "group": group, "severity": "warn",
                    "reason": (
                        f"0 продаж по 1 обращению два периода подряд "
                        f"({previous_period_label} и {period_label})"
                    ),
                })

        errors_pct = r.get("errors_pct") or 0
        if errors_pct >= 10:
            anomalies.append({
                "fio": fio, "group": group, "severity": "err",
                "reason": f"Высокий % ошибок: {errors_pct}%",
            })

    return anomalies


# ============================================================
# "По уровням" — детальный срез по статусу/уровню, ТОЛЬКО для недельных
# периодов (ЛГ/коэффициенты/часы/бонусы/ЗП — понятия, которых не
# существует для дневных отчётов, см. showTier в static/index.html).
# ============================================================

# Особый случай ТОЛЬКО для этого среза: Регион УК/ПП/Увеличители (уже
# исключены везде через is_region_uk_or_peaks_supervisor) ПЛЮС "Васько" —
# обычная группа, НЕ входящая в isSpecialGroup/is_region_uk_or_peaks_
# supervisor нигде больше в проекте (JS: static/index.html::isSpecialGroup
# её тоже не матчит) — этот срез единственное место, где её тоже убираем,
# по прямому запросу. Не трогаем group_naming.py, чтобы не задеть её
# поведение в остальных местах (сортировка/рейтинг супервайзеров и т.д.).
_VASKO_RE = re.compile(r"васько", re.IGNORECASE)


def _is_excluded_from_levels(supervisor: str | None) -> bool:
    return bool(supervisor) and (
        is_region_uk_or_peaks_supervisor(supervisor) or bool(_VASKO_RE.search(supervisor))
    )


# Фиксированный порядок прогрессии уровней (не алфавитный — алфавитный дал
# бы "Квалифицированный, Лидер, Новичок..." что не соответствует реальному
# прогрессу). Статусы, которых нет в этом списке, идут после — по алфавиту.
LEVEL_STATUS_ORDER = [
    "Новичок",
    "Новичок, 1-й уровень",
    "Новичок, 2-й уровень",
    "Новичок, 3-й уровень",
    "Перспективный",
    "Перспективный 2",
    "Квалифицированный",
    "Профи",
    "Лидер",
]


def _level_sort_key(status_value: str):
    try:
        return (0, LEVEL_STATUS_ORDER.index(status_value))
    except ValueError:
        return (1, status_value)


def _aggregate_level_group(rows: list[dict], prev_by_fio: dict) -> dict:
    """Агрегаты по одному набору строк (один уровень, либо ВСЕ уровни
    разом для итоговой строки) — карточки/сумма/часы/бонусы/ЗП СУММОЙ,
    ср.чек/конв./с контакта/место/ЛГ/коэффициенты — СРЕДНИМ (по тем, у
    кого поле реально заполнено — None пропускается _avg())."""

    def category(cards_f, sum_f, check_f, conv_f, pc_f, place_f):
        return {
            "cards": _sum(rows, cards_f),
            "sum": _sum(rows, sum_f),
            "check": _avg([r.get(check_f) for r in rows]),
            "conv": _avg([r.get(conv_f) for r in rows]),
            "pc": _avg([r.get(pc_f) for r in rows]),
            "place": _avg([r.get(place_f) for r in rows]),
        }

    return {
        "count": len(rows),
        "c1": category("c1_cards", "c1_sum", "c1_check", "c1_conv", "c1_per_contact", "c1_place"),
        "lk": category("lk_cards", "lk_sum", "lk_check", "lk_conv", "lk_per_contact", "lk_place"),
        "ch": category("ch_cards", "ch_sum", "ch_check", "ch_conv", "ch_per_contact", "ch_place"),
        "time": {
            "avg": _avg([r.get("time_per_contact") for r in rows]),
            "place": _avg([r.get("time_place") for r in rows]),
        },
        "errors": {
            "count": _sum(rows, "errors_count"),
            "pct": _avg([r.get("errors_pct") for r in rows]),
            "place": _avg([r.get("errors_place") for r in rows]),
        },
        "total_score": _sum(rows, "total_score"),
        # final_place: среднее только по тем, у кого он есть — у новичков
        # final_place всегда null (даже если есть "теневой" коэффициент),
        # они естественно не участвуют в среднем.
        "final_place_avg": _avg([r.get("final_place") for r in rows]),
        "tier_avg": _avg([r.get("tier") for r in rows]),
        "coefficient_avg": _avg([r.get("coefficient") for r in rows]),
        # "Коэфф. пред. недели" не хранится как отдельное поле — сопоставляем
        # людей этого уровня с их же строкой из ПРЕДЫДУЩЕГО периода по fio
        # (prev_by_fio) и берём их coefficient оттуда; среднее по тем, у
        # кого нашлось совпадение.
        "prev_week_coefficient_avg": _avg([
            (prev_by_fio.get(r.get("fio")) or {}).get("coefficient") for r in rows
        ]),
        "work_hours": _sum(rows, "work_hours"),
        "shift_count": _sum(rows, "shift_count"),
        "bonus075": _sum(rows, "bonus075"),
        "bonus2": _sum(rows, "bonus2"),
        "salary": _sum(rows, "salary"),
    }


def _compute_level_deltas(entry: dict, prev_entry: dict | None) -> dict:
    """Дельты только по метрикам, явно запрошенным для сравнения: кол-во
    чел., сумма баллов, ЗП, средний % ошибок, средняя "с контакта" по
    каждой из 3 категорий."""
    if prev_entry is None:
        return {}
    return {
        "count": _delta(entry["count"], prev_entry["count"], "count"),
        "total_score": _delta(entry["total_score"], prev_entry["total_score"], "total_score"),
        "salary": _delta(entry["salary"], prev_entry["salary"], "salary"),
        "errors_pct": _delta(entry["errors"]["pct"], prev_entry["errors"]["pct"], "errors_pct"),
        "c1_pc": _delta(entry["c1"]["pc"], prev_entry["c1"]["pc"], "c1_per_contact"),
        "lk_pc": _delta(entry["lk"]["pc"], prev_entry["lk"]["pc"], "lk_per_contact"),
        "ch_pc": _delta(entry["ch"]["pc"], prev_entry["ch"]["pc"], "ch_per_contact"),
    }


def build_levels_dashboard(ratings: list[dict], previous_ratings: list[dict] | None = None) -> dict:
    """ratings/previous_ratings: строки kpi_ratings ОДНОГО (недельного)
    периода — новички и основной состав вместе, is_na фильтруется тут
    (единственное отличие от build_summary_dashboard: там новички
    исключаются отдельным условием ДО is_na, тут — нет, новички со своим
    статусом участвуют как самостоятельные строки-уровни)."""
    included = [
        r for r in ratings
        if not r.get("is_na") and not _is_excluded_from_levels(r.get("supervisor"))
    ]
    included_groups = sorted({
        display_group_name(r.get("supervisor")) for r in included if r.get("supervisor")
    })

    prev_by_fio = {r.get("fio"): r for r in (previous_ratings or [])}
    prev_included = None
    if previous_ratings is not None:
        prev_included = [
            r for r in previous_ratings
            if not r.get("is_na") and not _is_excluded_from_levels(r.get("supervisor"))
        ]

    statuses = sorted({r.get("status") for r in included if r.get("status")}, key=_level_sort_key)

    levels = []
    for status_value in statuses:
        rows = [r for r in included if r.get("status") == status_value]
        entry = _aggregate_level_group(rows, prev_by_fio)
        entry["status"] = status_value
        if prev_included is not None:
            prev_rows = [r for r in prev_included if r.get("status") == status_value]
            prev_entry = _aggregate_level_group(prev_rows, {}) if prev_rows else None
            entry["deltas"] = _compute_level_deltas(entry, prev_entry)
        levels.append(entry)

    total_entry = _aggregate_level_group(included, prev_by_fio)
    total_entry["status"] = "ИТОГО — ВСЕ УРОВНИ"
    if prev_included is not None:
        prev_total_entry = _aggregate_level_group(prev_included, {}) if prev_included else None
        total_entry["deltas"] = _compute_level_deltas(total_entry, prev_total_entry)

    return {
        "included_groups": included_groups,
        "levels": levels,
        "total": total_entry,
    }

    return anomalies
