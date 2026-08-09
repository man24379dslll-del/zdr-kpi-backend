"""
"Конструктор рейтинга" — CRUD для таблицы rating_categories.
Только admin/manager могут менять; читать могут все залогиненные
(нужно, чтобы фронтенд знал текущую конфигурацию при отображении).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import CurrentUser, get_current_user
from app.supabase_client import as_user

router = APIRouter(prefix="/categories", tags=["rating-constructor"])


class CategoryIn(BaseModel):
    key: str
    label: str
    source_column: str
    weight: float
    direction: str  # 'desc' | 'asc'
    enabled: bool = True
    sort_order: int = 0


class CategoryOut(CategoryIn):
    id: str


@router.get("", response_model=list[CategoryOut])
async def list_categories(user: CurrentUser = Depends(get_current_user)):
    client = as_user(user.access_token)
    rows = await client.get("rating_categories", params={"select": "*", "order": "sort_order.asc"})
    return rows


@router.post("", response_model=CategoryOut)
async def create_category(payload: CategoryIn, user: CurrentUser = Depends(get_current_user)):
    if not user.is_admin_or_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только admin/manager могут менять конструктор рейтинга")
    if payload.direction not in ("asc", "desc"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "direction должен быть 'asc' или 'desc'")
    client = as_user(user.access_token)
    rows = await client.post("rating_categories", payload.model_dump())
    return rows[0]


@router.put("/{category_id}", response_model=CategoryOut)
async def update_category(category_id: str, payload: CategoryIn, user: CurrentUser = Depends(get_current_user)):
    if not user.is_admin_or_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только admin/manager могут менять конструктор рейтинга")
    client = as_user(user.access_token)
    rows = await client.patch(f"rating_categories?id=eq.{category_id}", payload.model_dump())
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Категория не найдена")
    return rows[0]


@router.delete("/{category_id}", status_code=204)
async def delete_category(category_id: str, user: CurrentUser = Depends(get_current_user)):
    if not user.is_admin_or_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только admin/manager могут менять конструктор рейтинга")
    client = as_user(user.access_token)
    await client.delete(f"rating_categories?id=eq.{category_id}")
