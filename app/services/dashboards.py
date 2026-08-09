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

    statuses = sorted({r.get("status") for r in main if r.get("status")})
    by_status = []
    for status_value in statuses:
        rows = [r for r in main if r.get("status") == status_value]
        prev_rows = [r for r in prev_main if r.get("status") == status_value] if has_previous else []
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
    """ratings: строки kpi_ratings ОДНОГО периода; Н/О исключаются."""
    main = [r for r in ratings if not r.get("is_na")]
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


def build_anomalies_dashboard(ratings: list[dict], previous_ratings: list[dict] | None = None) -> list[dict]:
    """ratings: строки kpi_ratings ОДНОГО периода (не новички сравниваются
    с той же fio в previous_ratings, если она дана)."""
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
                    "reason": "0 продаж 2 периода подряд",
                })

        if (r.get("errors_pct") or 0) >= 10:
            anomalies.append({"fio": fio, "group": group, "severity": "err", "reason": "Высокий % ошибок"})

    return anomalies
