"""
Полный недельный расчёт рейтинга: приём Excel-файла → категории из
конструктора рейтинга (rating_categories) → тир ЛК → итоговое место →
распределение по ЛГ → запись в kpi_uploads/kpi_ratings. Сам расчёт — в
services/weekly_rating.py, разбор файла — в services/excel_parsing.py,
запись результата — в services/ratings_repository.py; здесь только
HTTP-обвязка (приём файла, авторизация, чтение категорий из Supabase).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from app.auth import CurrentUser, get_current_user
from app.services.excel_parsing import is_na_row, parse_weekly_rating_excel
from app.services.rating_engine import RatingCategory
from app.services.ratings_repository import save_weekly_rating
from app.services.weekly_rating import compute_weekly_rating
from app.supabase_client import as_user

router = APIRouter(prefix="/ratings", tags=["weekly-rating"])


async def _load_categories(user: CurrentUser) -> list[RatingCategory]:
    client = as_user(user.access_token)
    rows = await client.get("rating_categories", params={"select": "*", "order": "sort_order.asc"})
    fields = ("key", "label", "source_column", "weight", "direction", "enabled", "sort_order")
    return [RatingCategory(**{f: row[f] for f in fields}) for row in rows]


async def _load_supervisor_channels(user: CurrentUser) -> dict[str, str]:
    client = as_user(user.access_token)
    rows = await client.get("supervisor_channels", params={"select": "supervisor,channel"})
    return {row["supervisor"]: row["channel"] for row in rows}


@router.post("/compute")
async def compute_weekly_rating_endpoint(
    file: UploadFile,
    period_label: str,
    user: CurrentUser = Depends(get_current_user),
):
    """Считает полный недельный рейтинг, сохраняет его в kpi_uploads/kpi_ratings
    и возвращает посчитанные строки вместе с id загрузки.

    period_label — метка периода для kpi_uploads (например '7-1' на неделю
    или '2026-07-27' на день) — как в старой JS-версии, формат не проверяем.
    """
    if not user.is_admin_or_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только admin/manager могут считать недельный рейтинг")

    categories = await _load_categories(user)
    supervisor_channels = await _load_supervisor_channels(user)
    raw = await file.read()
    employees = parse_weekly_rating_excel(raw, supervisor_channels)
    if not employees:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не нашлось ни одной валидной строки в файле")

    try:
        results = compute_weekly_rating(employees, categories, na_predicate=is_na_row)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    client = as_user(user.access_token)
    upload_id = await save_weekly_rating(client, period_label, file.filename or "", results)

    return {
        "upload_id": upload_id,
        "rows": [
            {
                "fio": r.fio,
                "supervisor": r.raw.get("supervisor"),
                "channel": r.raw.get("channel"),
                "channel_is_guessed": r.raw.get("channel_is_guessed"),
                "places": r.places,
                "total_score": r.total_score,
                "final_place": r.final_place,
                "is_na": r.is_na,
                "tier": r.tier,
                "coefficient": r.coefficient,
            }
            for r in results
        ],
    }
