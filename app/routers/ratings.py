"""
Полный недельный расчёт рейтинга: приём Excel-файла → категории из
конструктора рейтинга (rating_categories) → тир ЛК → итоговое место →
распределение по ЛГ → ЗП недели (по коэффициенту ЛГ прошлой недели) →
запись в kpi_uploads/kpi_ratings. Сам расчёт — в services/weekly_rating.py,
разбор файла — в services/excel_parsing.py, ЗП — в services/salary.py,
запись результата — в services/ratings_repository.py; здесь только
HTTP-обвязка (приём файла, авторизация, чтение из Supabase).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from app.auth import CurrentUser, get_current_user
from app.services.excel_parsing import is_na_row, parse_weekly_rating_excel
from app.services.payroll import is_weekly_period_label
from app.services.periods import find_previous_period
from app.services.rating_engine import RatingCategory
from app.services.ratings_repository import save_weekly_rating
from app.services.salary import assign_salary
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


async def _load_previous_week_coefficients(user: CurrentUser, period_label: str) -> dict[str, float]:
    """Коэффициент ЛГ, который человек заработал НА ПРОШЛОЙ неделе, по fio.

    "Предыдущая неделя" — ближайший по period_sort_value (месяц*10+неделя)
    period_label СРЕДИ ВСЕХ недельных kpi_uploads, без ограничения "тот же
    месяц" (см. services/periods.py) — неделя 1 августа находит неделю 5
    июля как предыдущую. Если такой недели нет — пустой словарь, и дальше
    assign_salary естественно даёт всем коэффициент по умолчанию 1.0."""
    client = as_user(user.access_token)
    all_uploads = await client.get("kpi_uploads", params={"select": "id,period_label"})
    previous = find_previous_period(all_uploads, period_label, period_type="week")
    if previous is None:
        return {}

    rows = await client.get(
        "kpi_ratings",
        params={"upload_id": f"eq.{previous['id']}", "select": "fio,coefficient"},
    )
    return {row["fio"]: row["coefficient"] for row in rows if row.get("coefficient") is not None}


@router.post("/compute")
async def compute_weekly_rating_endpoint(
    file: UploadFile,
    period_label: str,
    weeks_in_month: int = 4,
    user: CurrentUser = Depends(get_current_user),
):
    """Считает полный недельный рейтинг, сохраняет его в kpi_uploads/kpi_ratings
    и возвращает посчитанные строки вместе с id загрузки.

    period_label — метка периода для kpi_uploads (например '7-1' на неделю
    или '2026-07-27' на день) — как в старой JS-версии, формат не проверяем.
    weeks_in_month — 4 или 5, сколько недель в текущем месяце (для формулы
    ЗП: MONTHLY_BASE_RATE / weeks_in_month); учитывается только для
    недельных периодов, ввод не автоматический — вручную задаёт вызывающий.
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

    if is_weekly_period_label(period_label):
        prev_coefficients = await _load_previous_week_coefficients(user, period_label)
        assign_salary(results, prev_coefficients, weeks_in_month)

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
                "salary": r.salary,
            }
            for r in results
        ],
    }
