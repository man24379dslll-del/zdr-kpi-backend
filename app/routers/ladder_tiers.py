"""
ЛГ-коэффициенты (1.4..0.25 по тирам 1..10) — настройка вместо
захардкоженного TIER_COEFFICIENTS в services/ladder_groups.py (таблица
ladder_tier_coefficients, см. app/db/schema.sql). Читать могут все
залогиненные (нужно фронтенду конструктора рейтинга), менять — только
admin/manager.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import CurrentUser, get_current_user
from app.supabase_client import as_user

router = APIRouter(prefix="/ladder-tiers", tags=["ladder-tiers"])


class LadderTierIn(BaseModel):
    coefficient: float


class LadderTierOut(BaseModel):
    tier_number: int
    coefficient: float
    updated_at: str | None = None


@router.get("", response_model=list[LadderTierOut])
async def list_ladder_tiers(user: CurrentUser = Depends(get_current_user)):
    client = as_user(user.access_token)
    return await client.get("ladder_tier_coefficients", params={"select": "*", "order": "tier_number.asc"})


@router.put("/{tier_number}", response_model=LadderTierOut)
async def update_ladder_tier(
    tier_number: int,
    payload: LadderTierIn,
    user: CurrentUser = Depends(get_current_user),
):
    if not user.is_admin_or_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только admin/manager могут менять коэффициенты ЛГ")
    if not 1 <= tier_number <= 10:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "tier_number должен быть от 1 до 10")

    client = as_user(user.access_token)
    rows = await client.patch(
        f"ladder_tier_coefficients?tier_number=eq.{tier_number}",
        {"coefficient": payload.coefficient},
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Тир не найден")
    return rows[0]
