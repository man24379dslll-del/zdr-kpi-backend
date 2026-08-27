"""
4 дашборда поверх одного периода (+ опционально предыдущего для дельт):
сводка, воронка новичков, каналы, аномалии. Сама логика — в
services/dashboards.py (чистые функции, тестируются без сети); здесь —
HTTP-обвязка и чтение kpi_uploads/kpi_ratings из Supabase.

"Предыдущий период того же типа" выбирает вызывающий (передаёт
previous_upload_id) — у фронтенда уже есть список периодов, мы это тут
не угадываем.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import CurrentUser, get_current_user
from app.services.dashboards import (
    build_anomalies_dashboard,
    build_channels_dashboard,
    build_levels_dashboard,
    build_newcomer_funnel,
    build_summary_dashboard,
)
from app.supabase_client import as_user

router = APIRouter(prefix="/dashboards", tags=["dashboards"])


async def _load_ratings(client, upload_id: str) -> list[dict]:
    return await client.get("kpi_ratings", params={"upload_id": f"eq.{upload_id}", "select": "*"})


async def _load_period_label(client, upload_id: str) -> str | None:
    rows = await client.get("kpi_uploads", params={"id": f"eq.{upload_id}", "select": "period_label"})
    return rows[0]["period_label"] if rows else None


@router.get("/summary")
async def get_summary_dashboard(
    upload_id: str,
    previous_upload_id: str | None = None,
    user: CurrentUser = Depends(get_current_user),
):
    client = as_user(user.access_token)
    ratings = await _load_ratings(client, upload_id)
    period_label = await _load_period_label(client, upload_id)
    previous_ratings = await _load_ratings(client, previous_upload_id) if previous_upload_id else None
    return build_summary_dashboard(ratings, period_label, previous_ratings)


@router.get("/newcomer-funnel")
async def get_newcomer_funnel_dashboard(
    upload_id: str,
    previous_upload_id: str | None = None,
    user: CurrentUser = Depends(get_current_user),
):
    client = as_user(user.access_token)
    novices = [r for r in await _load_ratings(client, upload_id) if r.get("is_novice")]
    previous_novices = None
    if previous_upload_id:
        previous_novices = [r for r in await _load_ratings(client, previous_upload_id) if r.get("is_novice")]
    return build_newcomer_funnel(novices, previous_novices)


@router.get("/channels")
async def get_channels_dashboard(upload_id: str, user: CurrentUser = Depends(get_current_user)):
    client = as_user(user.access_token)
    return build_channels_dashboard(await _load_ratings(client, upload_id))


@router.get("/levels")
async def get_levels_dashboard(
    upload_id: str,
    previous_upload_id: str | None = None,
    user: CurrentUser = Depends(get_current_user),
):
    """Детальный срез "По уровням" — см. services/dashboards.py::
    build_levels_dashboard. Только для недельных периодов, вызывающая
    сторона (фронтенд) сама решает, какой upload_id передать."""
    client = as_user(user.access_token)
    ratings = await _load_ratings(client, upload_id)
    previous_ratings = await _load_ratings(client, previous_upload_id) if previous_upload_id else None
    return build_levels_dashboard(ratings, previous_ratings)


@router.get("/anomalies")
async def get_anomalies_dashboard(
    upload_id: str,
    previous_upload_id: str | None = None,
    user: CurrentUser = Depends(get_current_user),
):
    client = as_user(user.access_token)
    ratings = await _load_ratings(client, upload_id)
    period_label = await _load_period_label(client, upload_id)
    previous_ratings = None
    previous_period_label = None
    if previous_upload_id:
        previous_ratings = await _load_ratings(client, previous_upload_id)
        previous_period_label = await _load_period_label(client, previous_upload_id)
    return build_anomalies_dashboard(ratings, previous_ratings, period_label, previous_period_label)
