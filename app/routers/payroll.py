"""
Ведомость ЗП — см. services/payroll.py (календарная структура: месяц,
недели 1-4). Читает kpi_uploads/kpi_ratings/payroll_penalties
(по-недельные штрафы) и payroll_stage_adjustments (штраф/премия/оплата
за смены один раз на весь период) из Supabase; сама агрегация — чистая
функция, тестируется без сети.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import CurrentUser, get_current_user
from app.services.payroll import (
    DEFAULT_GUARANTEED_BASE,
    DEFAULT_MONTH2_TRAINING_BONUS,
    DEFAULT_OVERTIME_RATE,
    build_half_payroll,
    build_month_close_payroll,
    half_payroll_periods,
    is_weekly_period_label,
    make_periods_key,
    month_close_periods,
)
from app.services.salary import DEFAULT_HOURS_NORM
from app.supabase_client import as_user

router = APIRouter(prefix="/payroll", tags=["payroll"])


async def _load_adjustments(client, periods_key: str) -> dict[str, dict]:
    rows = await client.get(
        "payroll_stage_adjustments",
        params={"periods_key": f"eq.{periods_key}", "select": "fio,penalty,premium,shift_pay"},
    )
    return {
        row["fio"]: {
            "penalty": row.get("penalty") or 0,
            "premium": row.get("premium") or 0,
            "shift_pay": row.get("shift_pay") or 0,
        }
        for row in rows
    }


async def _load_markers(client) -> dict[str, dict]:
    rows = await client.get("payroll_employee_markers", params={"select": "fio,work_month,weekly_pay"})
    return {row["fio"]: row for row in rows}


async def _load_uploads_and_ratings(client, periods: list[str]):
    """Общая часть для /payroll/half и /payroll/close: находит загрузки,
    чьи period_label входят в periods, и подтягивает их
    kpi_ratings/payroll_penalties."""
    all_uploads = await client.get("kpi_uploads", params={"select": "id,period_label"})
    period_set = set(periods)
    matching_uploads = [u for u in all_uploads if (u.get("period_label") or "") in period_set]

    ratings_by_upload_id: dict[str, list[dict]] = {}
    penalties_by_upload_id: dict[str, dict[str, float]] = {}
    for upload in matching_uploads:
        upload_id = upload["id"]
        ratings_by_upload_id[upload_id] = await client.get(
            "kpi_ratings",
            params={
                "upload_id": f"eq.{upload_id}",
                "select": "fio,supervisor,status,is_novice,salary,work_hours,shift_count",
            },
        )
        penalty_rows = await client.get(
            "payroll_penalties",
            params={"upload_id": f"eq.{upload_id}", "select": "fio,penalty"},
        )
        penalties_by_upload_id[upload_id] = {row["fio"]: row["penalty"] for row in penalty_rows}
    return matching_uploads, ratings_by_upload_id, penalties_by_upload_id


@router.get("/half")
async def get_half_payroll(
    month: int,
    year: int,
    hours_norm: float = DEFAULT_HOURS_NORM,
    overtime_rate: float = DEFAULT_OVERTIME_RATE,
    user: CurrentUser = Depends(get_current_user),
):
    """"Полу-ведомость" за недели 1-2 месяца (см. services/payroll.py::
    build_half_payroll) — сотрудники с "Еженедельная оплата"=Да
    (payroll_employee_markers.weekly_pay) исключены полностью."""
    if not user.is_admin_or_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только admin/manager могут смотреть ведомость ЗП")
    if not 1 <= month <= 12:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "month должен быть от 1 до 12")

    client = as_user(user.access_token)
    periods = half_payroll_periods(month)
    matching_uploads, ratings_by_upload_id, penalties_by_upload_id = await _load_uploads_and_ratings(client, periods)

    markers = await _load_markers(client)
    weekly_pay_fios = {fio for fio, m in markers.items() if m.get("weekly_pay")}

    periods_key = make_periods_key(periods)
    adjustments_by_fio = await _load_adjustments(client, periods_key)

    return build_half_payroll(
        matching_uploads, ratings_by_upload_id, penalties_by_upload_id, month, year,
        weekly_pay_fios=weekly_pay_fios, adjustments_by_fio=adjustments_by_fio,
        hours_norm=hours_norm, overtime_rate=overtime_rate,
    )


@router.get("/close")
async def get_month_close_payroll(
    month: int,
    year: int,
    hours_norm: float = DEFAULT_HOURS_NORM,
    overtime_rate: float = DEFAULT_OVERTIME_RATE,
    guaranteed_base: float = DEFAULT_GUARANTEED_BASE,
    month2_bonus: float = DEFAULT_MONTH2_TRAINING_BONUS,
    user: CurrentUser = Depends(get_current_user),
):
    """"Закрытие месяца" — недели 1-4 (см. services/payroll.py::
    build_month_close_payroll) — MAX(гарантия, по рейтингу) для work_month
    1/2, просто сумма по рейтингу для 3+; минус уже выплаченная полу-
    ведомость за недели 1-2 (для всех, кроме weekly_pay=true)."""
    if not user.is_admin_or_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только admin/manager могут смотреть ведомость ЗП")
    if not 1 <= month <= 12:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "month должен быть от 1 до 12")

    client = as_user(user.access_token)
    close_periods = month_close_periods(month)
    matching_uploads, ratings_by_upload_id, penalties_by_upload_id = await _load_uploads_and_ratings(client, close_periods)

    markers = await _load_markers(client)
    weekly_pay_fios = {fio for fio, m in markers.items() if m.get("weekly_pay")}

    # "Уже выплаченная полу-ведомость" — живой пересчёт build_half_payroll
    # на тех же уже загруженных данных (недели 1-2 — подмножество недель
    # 1-4), а не отдельный запрос к Supabase. У weekly_pay=true в этих rows
    # никого нет (build_half_payroll их сама исключает), поэтому вычет для
    # них естественно 0 — без отдельной ветки.
    half_periods = half_payroll_periods(month)
    half_adjustments_by_fio = await _load_adjustments(client, make_periods_key(half_periods))
    half_result = build_half_payroll(
        matching_uploads, ratings_by_upload_id, penalties_by_upload_id, month, year,
        weekly_pay_fios=weekly_pay_fios, adjustments_by_fio=half_adjustments_by_fio,
        hours_norm=hours_norm, overtime_rate=overtime_rate,
    )
    half_sum_by_fio = {row["fio"]: row["sum"] for row in half_result["rows"]}

    close_adjustments_by_fio = await _load_adjustments(client, make_periods_key(close_periods))

    return build_month_close_payroll(
        matching_uploads, ratings_by_upload_id, penalties_by_upload_id, month, year,
        markers_by_fio=markers, adjustments_by_fio=close_adjustments_by_fio,
        half_sum_by_fio=half_sum_by_fio,
        hours_norm=hours_norm, overtime_rate=overtime_rate,
        guaranteed_base=guaranteed_base, month2_bonus=month2_bonus,
    )


class AdjustmentIn(BaseModel):
    fio: str
    periods: list[str]
    penalty: float = 0
    premium: float = 0
    shift_pay: float = 0
    comment: str | None = None


@router.put("/adjustment")
async def upsert_adjustment(payload: AdjustmentIn, user: CurrentUser = Depends(get_current_user)):
    """Заводит новую запись или обновляет существующую (уникальность —
    fio+periods_key, см. app/db/schema.sql). periods_key вычисляется здесь
    из payload.periods (сортировка + склейка через запятую), не зависит от
    порядка, в котором фронтенд прислал отмеченные недели."""
    if not user.is_admin_or_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только admin/manager могут менять штраф/премию по ведомости")
    invalid = [p for p in payload.periods if not is_weekly_period_label(p)]
    if invalid:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"periods должен состоять из недельных period_label вида 'месяц-неделя', некорректные: {invalid}",
        )

    client = as_user(user.access_token)
    rows = await client.post(
        "payroll_stage_adjustments?on_conflict=fio,periods_key",
        {
            "fio": payload.fio,
            "periods_key": make_periods_key(payload.periods),
            "penalty": payload.penalty,
            "premium": payload.premium,
            "shift_pay": payload.shift_pay,
            "comment": payload.comment,
        },
        prefer="resolution=merge-duplicates,return=representation",
    )
    return rows[0]


class EmployeeMarkerOut(BaseModel):
    fio: str
    work_month: int
    weekly_pay: bool
    updated_at: str | None = None


class EmployeeMarkerIn(BaseModel):
    fio: str
    work_month: int = 1
    weekly_pay: bool = False


@router.get("/employee-markers", response_model=list[EmployeeMarkerOut])
async def list_employee_markers(user: CurrentUser = Depends(get_current_user)):
    """"Месяц работы"/"Еженедельная оплата" — маркеры ПО СОТРУДНИКУ (не по
    периоду, см. app/db/schema.sql), переносятся между периодами
    автоматически. Читает admin/manager, для отображения/редактирования
    в ведомости ЗП (недели 1-4 — MAX-логика; недели 1-2 — исключение
    weekly_pay=true, см. services/payroll.py)."""
    if not user.is_admin_or_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только admin/manager могут смотреть маркеры сотрудников")
    client = as_user(user.access_token)
    return await client.get("payroll_employee_markers", params={"select": "*"})


@router.put("/employee-marker", response_model=EmployeeMarkerOut)
async def upsert_employee_marker(payload: EmployeeMarkerIn, user: CurrentUser = Depends(get_current_user)):
    """Заводит новую запись или обновляет существующую (fio — ключ)."""
    if not user.is_admin_or_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только admin/manager могут менять маркеры сотрудников")
    if not 1 <= payload.work_month <= 3:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "work_month должен быть 1, 2 или 3")

    client = as_user(user.access_token)
    rows = await client.post(
        "payroll_employee_markers?on_conflict=fio",
        payload.model_dump(),
        prefer="resolution=merge-duplicates,return=representation",
    )
    return rows[0]
