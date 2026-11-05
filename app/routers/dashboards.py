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

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import CurrentUser, get_current_user
from app.services.dashboards import (
    build_anomalies_dashboard,
    build_channels_dashboard,
    build_levels_dashboard,
    build_newcomer_funnel,
    build_statuses_dashboard,
    build_summary_dashboard,
)
from app.services.group_naming import restrict_to_sector_pair
from app.services.sector_compare import build_sector_comparison
from app.services.sector_weights import lk_off_in_snapshot
from app.supabase_client import as_service, as_user

router = APIRouter(prefix="/dashboards", tags=["dashboards"])


def _client_for(user: CurrentUser):
    """Руководителям Секторов 2 и 3 — здесь идём в обход RLS через
    as_service(), см. group_naming.restrict_to_sector_pair (там же —
    почему supervisor_names не расширяем)."""
    if user.is_sector2_head or user.is_sector3_head:
        return as_service()
    return as_user(user.access_token)


async def _load_ratings(client, upload_id: str, user: CurrentUser) -> list[dict]:
    rows = await client.get("kpi_ratings", params={"upload_id": f"eq.{upload_id}", "select": "*"})
    if user.is_sector2_head or user.is_sector3_head:
        rows = restrict_to_sector_pair(rows)
    return rows


async def _load_period_label(client, upload_id: str) -> str | None:
    rows = await client.get("kpi_uploads", params={"id": f"eq.{upload_id}", "select": "period_label"})
    return rows[0]["period_label"] if rows else None


@router.get("/summary")
async def get_summary_dashboard(
    upload_id: str,
    previous_upload_id: str | None = None,
    user: CurrentUser = Depends(get_current_user),
):
    client = _client_for(user)
    ratings = await _load_ratings(client, upload_id, user)
    period_label = await _load_period_label(client, upload_id)
    previous_ratings = await _load_ratings(client, previous_upload_id, user) if previous_upload_id else None
    return build_summary_dashboard(ratings, period_label, previous_ratings)


@router.get("/newcomer-funnel")
async def get_newcomer_funnel_dashboard(
    upload_id: str,
    previous_upload_id: str | None = None,
    user: CurrentUser = Depends(get_current_user),
):
    client = _client_for(user)
    novices = [r for r in await _load_ratings(client, upload_id, user) if r.get("is_novice")]
    previous_novices = None
    if previous_upload_id:
        previous_novices = [r for r in await _load_ratings(client, previous_upload_id, user) if r.get("is_novice")]
    return build_newcomer_funnel(novices, previous_novices)


@router.get("/channels")
async def get_channels_dashboard(upload_id: str, user: CurrentUser = Depends(get_current_user)):
    client = _client_for(user)
    return build_channels_dashboard(await _load_ratings(client, upload_id, user))


@router.get("/levels")
async def get_levels_dashboard(
    upload_id: str,
    previous_upload_id: str | None = None,
    user: CurrentUser = Depends(get_current_user),
):
    """Детальный срез "По уровням" — см. services/dashboards.py::
    build_levels_dashboard. Только для недельных периодов, вызывающая
    сторона (фронтенд) сама решает, какой upload_id передать."""
    client = _client_for(user)
    ratings = await _load_ratings(client, upload_id, user)
    previous_ratings = await _load_ratings(client, previous_upload_id, user) if previous_upload_id else None
    return build_levels_dashboard(ratings, previous_ratings)


@router.get("/statuses")
async def get_statuses_dashboard(upload_id: str, user: CurrentUser = Depends(get_current_user)):
    """Срез "По статусам" для всех ролей — 1 обращение, Радио+ТВ, Интернет,
    время на контакт, ошибки (без денег/ЛГ), см. services/dashboards.py::
    build_statuses_dashboard. Данные — только те, что видит сам пользователь
    (RLS/сектор), как и у остальных дашбордов."""
    client = _client_for(user)
    return build_statuses_dashboard(await _load_ratings(client, upload_id, user))


async def _load_all_ratings(client, upload_id: str) -> list[dict]:
    """ВСЕ строки периода (PostgREST отдаёт максимум 1000 за запрос —
    выбираем страницами, порядок по id, чтобы страницы не пересекались)."""
    out: list[dict] = []
    offset = 0
    while True:
        page = await client.get("kpi_ratings", params={
            "upload_id": f"eq.{upload_id}", "select": "*", "order": "id.asc", "limit": "1000", "offset": str(offset),
        })
        out.extend(page)
        if len(page) < 1000:
            return out
        offset += 1000


@router.get("/sectors")
async def get_sector_comparison(upload_id: str, user: CurrentUser = Depends(get_current_user)):
    """Сравнение секторов, супервайзеров и операторов между собой — без денег
    (services/sector_compare.py). Админ, менеджер и руководители секторов:
    данные ВСЕХ секторов (в обход RLS, как и просмотр руководителей — см.
    _client_for), поэтому остальным ролям — 403."""
    if not (user.is_admin_or_manager or user.is_sector2_head or user.is_sector3_head):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Сравнение секторов доступно руководителям секторов, администратору и менеджеру",
        )
    client = as_service()
    ratings = await _load_all_ratings(client, upload_id)
    result = build_sector_comparison(ratings)
    uploads = await client.get(
        "kpi_uploads", params={"id": f"eq.{upload_id}", "select": "period_label,weights_snapshot"}
    )
    upload = uploads[0] if uploads else {}
    result["period_label"] = upload.get("period_label")
    # ЛК выключена у всех секторов периода (вес 0) — колонку ЛК не показываем
    result["lk_hidden"] = lk_off_in_snapshot(upload.get("weights_snapshot"))
    return result


@router.get("/anomalies")
async def get_anomalies_dashboard(
    upload_id: str,
    previous_upload_id: str | None = None,
    user: CurrentUser = Depends(get_current_user),
):
    client = _client_for(user)
    ratings = await _load_ratings(client, upload_id, user)
    period_label = await _load_period_label(client, upload_id)
    previous_ratings = None
    previous_period_label = None
    if previous_upload_id:
        previous_ratings = await _load_ratings(client, previous_upload_id, user)
        previous_period_label = await _load_period_label(client, previous_upload_id)
    return build_anomalies_dashboard(ratings, previous_ratings, period_label, previous_period_label)
