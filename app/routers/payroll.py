"""
Двухэтапная ведомость ЗП — см. services/payroll.py. Читает kpi_uploads/
kpi_ratings/payroll_penalties (по-недельные штрафы) и, для stage="2",
payroll_stage_adjustments (штраф/премия/доп.часы/оплата за смены один
раз на весь этап) из Supabase; сама агрегация — чистая функция,
тестируется без сети.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import CurrentUser, get_current_user
from app.services.payroll import DEFAULT_OVERTIME_RATE, build_two_stage_payroll, filter_uploads_for_stage
from app.services.salary import DEFAULT_HOURS_NORM
from app.supabase_client import as_user

router = APIRouter(prefix="/payroll", tags=["payroll"])


async def _load_stage_adjustments(client, month: int, year: int) -> dict[str, dict]:
    rows = await client.get(
        "payroll_stage_adjustments",
        params={
            "month": f"eq.{month}", "year": f"eq.{year}",
            "select": "fio,penalty,premium,extra_hours,shift_count,shift_pay",
        },
    )
    return {
        row["fio"]: {
            "penalty": row.get("penalty") or 0,
            "premium": row.get("premium") or 0,
            "extra_hours": row.get("extra_hours") or 0,
            "shift_count": row.get("shift_count") or 0,
            "shift_pay": row.get("shift_pay") or 0,
        }
        for row in rows
    }


@router.get("/two-stage")
async def get_two_stage_payroll(
    month: int,
    stage: str,
    year: int,
    hours_norm: float = DEFAULT_HOURS_NORM,
    overtime_rate: float = DEFAULT_OVERTIME_RATE,
    user: CurrentUser = Depends(get_current_user),
):
    """month: 1..12, stage: '1' (аванс, недели 1-2) | '2' (расчёт, недели 3-5).
    year — только для текста периода начисления, period_label его не содержит.
    hours_norm/overtime_rate — параметры доплаты за переработку/недоработку
    часов (см. services/payroll.py), учитываются только для stage="2"."""
    if not user.is_admin_or_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только admin/manager могут смотреть ведомость ЗП")
    if stage not in ("1", "2"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "stage должен быть '1' или '2'")

    client = as_user(user.access_token)
    all_uploads = await client.get("kpi_uploads", params={"select": "id,period_label"})
    matching_uploads = filter_uploads_for_stage(all_uploads, month, stage)

    ratings_by_upload_id: dict[str, list[dict]] = {}
    penalties_by_upload_id: dict[str, dict[str, float]] = {}
    for upload in matching_uploads:
        upload_id = upload["id"]
        ratings_by_upload_id[upload_id] = await client.get(
            "kpi_ratings",
            params={"upload_id": f"eq.{upload_id}", "select": "fio,supervisor,status,is_novice,salary,work_hours"},
        )
        penalty_rows = await client.get(
            "payroll_penalties",
            params={"upload_id": f"eq.{upload_id}", "select": "fio,penalty"},
        )
        penalties_by_upload_id[upload_id] = {row["fio"]: row["penalty"] for row in penalty_rows}

    # Штраф/премия/доп.часы/оплата за смены за этап — не по неделям, только
    # для "Расчёт" (см. services/payroll.py)
    stage_adjustments_by_fio = await _load_stage_adjustments(client, month, year) if stage == "2" else None

    return build_two_stage_payroll(
        matching_uploads, ratings_by_upload_id, penalties_by_upload_id, month, stage, year,
        stage_adjustments_by_fio=stage_adjustments_by_fio,
        hours_norm=hours_norm, overtime_rate=overtime_rate,
    )


class StageAdjustmentIn(BaseModel):
    month: int
    year: int
    fio: str
    penalty: float = 0
    premium: float = 0
    extra_hours: float = 0
    shift_count: float = 0
    shift_pay: float = 0
    comment: str | None = None


@router.put("/stage-adjustment")
async def upsert_stage_adjustment(payload: StageAdjustmentIn, user: CurrentUser = Depends(get_current_user)):
    """Заводит новую запись или обновляет существующую (уникальность —
    month+year+fio, см. app/db/schema.sql)."""
    if not user.is_admin_or_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только admin/manager могут менять штраф/премию по ведомости")
    if not 1 <= payload.month <= 12:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "month должен быть от 1 до 12")

    client = as_user(user.access_token)
    rows = await client.post(
        "payroll_stage_adjustments?on_conflict=month,year,fio",
        payload.model_dump(),
        prefer="resolution=merge-duplicates,return=representation",
    )
    return rows[0]
