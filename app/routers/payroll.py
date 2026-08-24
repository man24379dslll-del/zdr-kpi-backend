"""
Гибкая ведомость ЗП — см. services/payroll.py. Читает kpi_uploads/
kpi_ratings/payroll_penalties (по-недельные штрафы) и
payroll_stage_adjustments (штраф/премия/оплата за смены один раз на весь
набор отмеченных недель) из Supabase; сама агрегация — чистая функция,
тестируется без сети.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import CurrentUser, get_current_user
from app.services.payroll import (
    DEFAULT_OVERTIME_RATE,
    build_flexible_payroll,
    is_weekly_period_label,
    make_periods_key,
)
from app.services.salary import DEFAULT_HOURS_NORM
from app.supabase_client import as_user

router = APIRouter(prefix="/payroll", tags=["payroll"])


def _parse_periods(periods: str) -> list[str]:
    parsed = [p.strip() for p in periods.split(",") if p.strip()]
    if not parsed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "periods не должен быть пустым")
    invalid = [p for p in parsed if not is_weekly_period_label(p)]
    if invalid:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"periods должен состоять из недельных period_label вида 'месяц-неделя', некорректные: {invalid}",
        )
    return parsed


async def _load_adjustments(client, periods_key: str) -> dict[str, dict]:
    rows = await client.get(
        "payroll_stage_adjustments",
        params={"periods_key": f"eq.{periods_key}", "select": "fio,penalty,premium,shift_pay"},
    )
    return {
        row["fio"]: {
            "penalty": row.get("penalty") or 0,
            "premium": row.get("premium") or 0,
            "shift_pay": row.get("shift_pay") or 0,
        }
        for row in rows
    }


@router.get("/flexible")
async def get_flexible_payroll(
    periods: str,
    year: int,
    hours_norm: float = DEFAULT_HOURS_NORM,
    overtime_rate: float = DEFAULT_OVERTIME_RATE,
    user: CurrentUser = Depends(get_current_user),
):
    """periods: недельные period_label через запятую, например "7-5,8-1,8-2"
    (любое количество, из любых месяцев). year — только для текста периода
    начисления, period_label его не содержит. hours_norm/overtime_rate —
    параметры доплаты за переработку/недоработку часов (см.
    services/payroll.py) — применяются всегда, ко всему набору недель."""
    if not user.is_admin_or_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только admin/manager могут смотреть ведомость ЗП")

    parsed_periods = _parse_periods(periods)

    client = as_user(user.access_token)
    all_uploads = await client.get("kpi_uploads", params={"select": "id,period_label"})
    period_set = set(parsed_periods)
    matching_uploads = [u for u in all_uploads if (u.get("period_label") or "") in period_set]

    ratings_by_upload_id: dict[str, list[dict]] = {}
    penalties_by_upload_id: dict[str, dict[str, float]] = {}
    for upload in matching_uploads:
        upload_id = upload["id"]
        ratings_by_upload_id[upload_id] = await client.get(
            "kpi_ratings",
            params={
                "upload_id": f"eq.{upload_id}",
                "select": "fio,supervisor,status,is_novice,salary,work_hours,shift_count",
            },
        )
        penalty_rows = await client.get(
            "payroll_penalties",
            params={"upload_id": f"eq.{upload_id}", "select": "fio,penalty"},
        )
        penalties_by_upload_id[upload_id] = {row["fio"]: row["penalty"] for row in penalty_rows}

    periods_key = make_periods_key(parsed_periods)
    adjustments_by_fio = await _load_adjustments(client, periods_key)

    return build_flexible_payroll(
        matching_uploads, ratings_by_upload_id, penalties_by_upload_id, parsed_periods, year,
        adjustments_by_fio=adjustments_by_fio,
        hours_norm=hours_norm, overtime_rate=overtime_rate,
    )


class AdjustmentIn(BaseModel):
    fio: str
    periods: list[str]
    penalty: float = 0
    premium: float = 0
    shift_pay: float = 0
    comment: str | None = None


@router.put("/adjustment")
async def upsert_adjustment(payload: AdjustmentIn, user: CurrentUser = Depends(get_current_user)):
    """Заводит новую запись или обновляет существующую (уникальность —
    fio+periods_key, см. app/db/schema.sql). periods_key вычисляется здесь
    из payload.periods (сортировка + склейка через запятую), не зависит от
    порядка, в котором фронтенд прислал отмеченные недели."""
    if not user.is_admin_or_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только admin/manager могут менять штраф/премию по ведомости")
    invalid = [p for p in payload.periods if not is_weekly_period_label(p)]
    if invalid:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"periods должен состоять из недельных period_label вида 'месяц-неделя', некорректные: {invalid}",
        )

    client = as_user(user.access_token)
    rows = await client.post(
        "payroll_stage_adjustments?on_conflict=fio,periods_key",
        {
            "fio": payload.fio,
            "periods_key": make_periods_key(payload.periods),
            "penalty": payload.penalty,
            "premium": payload.premium,
            "shift_pay": payload.shift_pay,
            "comment": payload.comment,
        },
        prefer="resolution=merge-duplicates,return=representation",
    )
    return rows[0]
