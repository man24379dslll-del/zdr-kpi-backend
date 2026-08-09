"""
Двухэтапная ведомость ЗП — см. services/payroll.py. Читает kpi_uploads/
kpi_ratings/payroll_penalties (по-недельные штрафы) и, для stage="2",
payroll_stage_adjustments (штраф/премия один раз на весь этап) из
Supabase; сама агрегация — чистая функция, тестируется без сети.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import CurrentUser, get_current_user
from app.services.payroll import build_two_stage_payroll, filter_uploads_for_stage
from app.supabase_client import as_user

router = APIRouter(prefix="/payroll", tags=["payroll"])


async def _load_stage_adjustments(client, month: int, year: int) -> dict[str, dict]:
    rows = await client.get(
        "payroll_stage_adjustments",
        params={"month": f"eq.{month}", "year": f"eq.{year}", "select": "fio,penalty,premium"},
    )
    return {row["fio"]: {"penalty": row.get("penalty") or 0, "premium": row.get("premium") or 0} for row in rows}


@router.get("/two-stage")
async def get_two_stage_payroll(
    month: int,
    stage: str,
    year: int,
    user: CurrentUser = Depends(get_current_user),
):
    """month: 1..12, stage: '1' (аванс, недели 1-2) | '2' (расчёт, недели 3-5).
    year — только для текста периода начисления, period_label его не содержит."""
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
            params={"upload_id": f"eq.{upload_id}", "select": "fio,supervisor,status,is_novice,salary"},
        )
        penalty_rows = await client.get(
            "payroll_penalties",
            params={"upload_id": f"eq.{upload_id}", "select": "fio,penalty"},
        )
        penalties_by_upload_id[upload_id] = {row["fio"]: row["penalty"] for row in penalty_rows}

    # Штраф/премия за этап — не по неделям, только для "Расчёт" (см. services/payroll.py)
    stage_adjustments_by_fio = await _load_stage_adjustments(client, month, year) if stage == "2" else None

    return build_two_stage_payroll(
        matching_uploads, ratings_by_upload_id, penalties_by_upload_id, month, stage, year,
        stage_adjustments_by_fio=stage_adjustments_by_fio,
    )


class StageAdjustmentIn(BaseModel):
    month: int
    year: int
    fio: str
    penalty: float = 0
    premium: float = 0
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
