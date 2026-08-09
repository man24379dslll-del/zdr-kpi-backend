"""
Двухэтапная ведомость ЗП — см. services/payroll.py. Читает kpi_uploads/
kpi_ratings/payroll_penalties из Supabase; сама агрегация — чистая
функция, тестируется без сети.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import CurrentUser, get_current_user
from app.services.payroll import build_two_stage_payroll, filter_uploads_for_stage
from app.supabase_client import as_user

router = APIRouter(prefix="/payroll", tags=["payroll"])


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
        # TODO: колонки (upload_id, fio, amount) — по аналогии с остальными
        # таблицами, не сверено с реальной схемой payroll_penalties.
        penalty_rows = await client.get(
            "payroll_penalties",
            params={"upload_id": f"eq.{upload_id}", "select": "fio,amount"},
        )
        penalties_by_upload_id[upload_id] = {row["fio"]: row["amount"] for row in penalty_rows}

    return build_two_stage_payroll(matching_uploads, ratings_by_upload_id, penalties_by_upload_id, month, stage, year)
