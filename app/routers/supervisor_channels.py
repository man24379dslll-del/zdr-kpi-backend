"""
Соответствие "супервайзер → канал" (Радио+ТВ / Интернет). Канал нельзя
вычислить из сумм в файле надёжно (см. app/db/schema.sql), поэтому это
настройка, которую вводит admin/manager — примерно как rating_categories,
только читать могут все залогиненные, чтобы фронтенд мог подсветить
непокрытых супервайзеров (см. excel_parsing.channel_is_guessed).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import CurrentUser, get_current_user
from app.supabase_client import as_user

router = APIRouter(prefix="/supervisor-channels", tags=["supervisor-channels"])


class SupervisorChannelIn(BaseModel):
    supervisor: str
    channel: str  # 'radio' | 'inet'


class SupervisorChannelOut(SupervisorChannelIn):
    updated_at: str | None = None


@router.get("", response_model=list[SupervisorChannelOut])
async def list_supervisor_channels(user: CurrentUser = Depends(get_current_user)):
    client = as_user(user.access_token)
    return await client.get("supervisor_channels", params={"select": "*", "order": "supervisor.asc"})


@router.post("", response_model=SupervisorChannelOut)
async def upsert_supervisor_channel(payload: SupervisorChannelIn, user: CurrentUser = Depends(get_current_user)):
    """Заводит новую запись или обновляет существующую (supervisor — ключ)."""
    if not user.is_admin_or_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только admin/manager могут менять соответствие супервайзер → канал")
    if payload.channel not in ("radio", "inet"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "channel должен быть 'radio' или 'inet'")

    client = as_user(user.access_token)
    rows = await client.post(
        "supervisor_channels?on_conflict=supervisor",
        payload.model_dump(),
        prefer="resolution=merge-duplicates,return=representation",
    )
    return rows[0]
