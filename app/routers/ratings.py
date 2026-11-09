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

import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, UploadFile, status

from app.auth import CurrentUser, get_current_user
from app.services.excel_parsing import is_na_row, parse_weekly_rating_excel
from app.services.group_naming import SECTOR_2_AND_3_SUPERVISORS, restrict_to_sector_pair
from app.services.payroll import is_weekly_period_label
from app.services.periods import find_previous_period
from app.services.rating_engine import RatingCategory
from app.services.ratings_repository import maybe_save_weekly_rating, save_weekly_rating
from app.services.ratings_upload import (
    UploadValidationError,
    find_previous_upload,
    period_type_of,
    sanitize_rows,
)
from app.services.salary import DEFAULT_HOURS_NORM, DEFAULT_MONTHLY_BASE_RATE, assign_salary
from app.services.supervisor_stats import STATS_COLUMNS, sector_group_stats
from app.services.sector_weights import (
    SECTOR_NAMES,
    WeightsValidationError,
    load_effective,
    sector_of_supervisor,
    parse_snapshot,
    snapshot_of,
    weights_by_sector,
    weights_equal,
)
from app.services.weekly_rating import compute_weekly_rating
from app.supabase_client import as_service, as_user

router = APIRouter(prefix="/ratings", tags=["weekly-rating"])


@router.get("/by-upload")
async def get_ratings_by_upload(upload_id: str, user: CurrentUser = Depends(get_current_user)):
    """Строки kpi_ratings за upload_id — обычно фронтенд читает их
    напрямую из Supabase (RLS сам урезает до supervisor_names
    пользователя), этот эндпоинт нужен ТОЛЬКО для руководителей Секторов
    2 и 3 — та же "статистика групп друг друга", что у Ворониной (см.
    group_naming.restrict_to_sector_pair, тот же приём, что и в
    routers/dashboards.py). Для всех остальных ролей отдаёт ровно то же,
    что дал бы прямой запрос к Supabase (as_user, полный select), без
    изменения поведения."""
    if user.is_sector2_head or user.is_sector3_head:
        client = as_service()
        rows = await client.get("kpi_ratings", params={"upload_id": f"eq.{upload_id}", "select": "*"})
        return restrict_to_sector_pair(rows)
    client = as_user(user.access_token)
    return await client.get("kpi_ratings", params={"upload_id": f"eq.{upload_id}", "select": "*"})


def _require_sector_head(user: CurrentUser) -> None:
    if not (user.is_sector2_head or user.is_sector3_head):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Загрузка отчёта доступна только администратору и руководителям секторов",
        )


async def _all_rows(client, table: str, params: dict) -> list[dict]:
    """PostgREST отдаёт максимум 1000 строк за запрос — выбираем страницами."""
    out: list[dict] = []
    offset = 0
    while True:
        page = await client.get(table, params={**params, "limit": "1000", "offset": str(offset)})
        out.extend(page)
        if len(page) < 1000:
            return out
        offset += 1000


@router.get("/upload-context")
async def get_upload_context(period_label: str, user: CurrentUser = Depends(get_current_user)):
    """Контекст загрузки отчёта руководителем сектора: есть ли уже загрузка
    за этот период (повторная блокируется — иначе ЗП в Ведомости удвоилась
    бы) и данные ПРЕДЫДУЩЕГО периода ПО ВСЕЙ КОМПАНИИ (место/баллы/
    коэффициент по ФИО) — они нужны браузеру для коэффициента прошлой недели
    в ЗП и дельт, а RLS урезает его собственное чтение до своих групп (иначе
    у всех остальных коэффициент стал бы 1.0 и записался бы в базу).
    Возвращаются только поля, нужные для этого (см. buildPrevMap)."""
    _require_sector_head(user)
    period_type = period_type_of(period_label)
    if period_type is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректная метка периода")
    client = as_service()
    uploads = await _all_rows(
        client, "kpi_uploads",
        {"select": "id,period_label,uploaded_at,source_filename", "order": "uploaded_at.desc"},
    )
    existing = next((u for u in uploads if u.get("period_label") == period_label), None)
    prev = find_previous_upload(uploads, period_label, period_type)
    prev_rows: list[dict] = []
    if prev:
        prev_rows = await _all_rows(client, "kpi_ratings", {
            "upload_id": f"eq.{prev['id']}",
            "select": "fio,final_place,total_score,coefficient,is_na,is_novice",
            "order": "id.asc",
        })
    return {
        "existing": existing,
        "prev_upload": {"id": prev["id"], "period_label": prev["period_label"]} if prev else None,
        "prev_rows": prev_rows,
    }


def _supervisor_sees(user: CurrentUser, supervisor: str | None) -> bool:
    """Видит ли пользователь строки этой группы в kpi_ratings — как политика
    ratings_select (RLS): '*' в supervisor_names — все группы; руководитель
    сектора — обе группы секторов 2/3 (restrict_to_sector_pair); остальные —
    только свои группы."""
    names = user.supervisor_names or []
    if "*" in names:
        return True
    if user.is_sector2_head or user.is_sector3_head:
        return supervisor in SECTOR_2_AND_3_SUPERVISORS
    return supervisor in names


@router.get("/previous-for-viewer")
async def get_previous_for_viewer(upload_id: str, user: CurrentUser = Depends(get_current_user)):
    """Прошлый период для окна супервайзера: коэффициент ЛГ/место/баллы
    прошлой недели ПО ЛЮДЯМ, а не по группам. RLS оставляет супервайзеру в
    прошлом периоде только строки его нынешней группы, поэтому у перешедших из
    другой группы колонка "Коэфф. пред. недели (в ЗП)" показывала бы 1.0 "по
    умолчанию" и пропадала бы стрелка "Δ к пред. периоду" (в самой ЗП
    коэффициент уже следует за человеком — её считает админ, видящий всё).
    Отдаём прошлые строки ТОЛЬКО тех людей (по ФИО), что есть у пользователя в
    текущей таблице, — чужие группы и люди, которых он не видит, не
    раскрываются. Прошлый период — тот же выбор, что у фронтенда
    (fetchLatestUpload): ближайший строго более ранний того же типа."""
    if user.role != "supervisor" or not user.supervisor_names:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только для супервайзеров")
    try:
        upload_id = str(uuid.UUID(upload_id))
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Загрузка не найдена")
    client = as_service()
    uploads = await _all_rows(client, "kpi_uploads", {"select": "id,period_label,uploaded_at", "order": "uploaded_at.desc"})
    current = next((u for u in uploads if u["id"] == upload_id), None)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Загрузка не найдена")
    period_type = period_type_of(current["period_label"])
    prev = find_previous_upload(uploads, current["period_label"], period_type) if period_type else None
    if prev is None:
        return {"prev_upload": None, "rows": []}
    current_rows = await _all_rows(client, "kpi_ratings", {
        "upload_id": f"eq.{upload_id}", "select": "fio,supervisor", "order": "id.asc",
    })
    fios = {r["fio"] for r in current_rows if _supervisor_sees(user, r.get("supervisor"))}
    prev_rows = await _all_rows(client, "kpi_ratings", {
        "upload_id": f"eq.{prev['id']}", "select": "fio,final_place,total_score,is_na,coefficient,is_novice", "order": "id.asc",
    })
    return {
        "prev_upload": {"id": prev["id"], "period_label": prev["period_label"]},
        "rows": [r for r in prev_rows if r["fio"] in fios],
    }


@router.get("/sector-supervisor-stats")
async def get_sector_supervisor_stats(upload_id: str, user: CurrentUser = Depends(get_current_user)):
    """Для "Рейтинга супервайзеров сектора" в рабочем окне супервайзера: агрегаты
    по ВСЕМ группам сектора(ов), в который входят группы пользователя (у
    супервайзера RLS оставляет только его группу, а рейтинг нужен по сектору).
    Только средние/суммы по группам — без ФИО и без денег
    (services/supervisor_stats.py); места и баллы считает фронтенд."""
    if user.role != "supervisor" or not user.supervisor_names:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Рейтинг сектора доступен только супервайзерам")
    sectors = sorted({sector_of_supervisor(name) for name in user.supervisor_names})
    rows = await _all_rows(as_service(), "kpi_ratings", {
        "upload_id": f"eq.{upload_id}", "select": STATS_COLUMNS, "order": "id.asc",
    })
    return {
        "sectors": [
            {"sector": sector, "name": SECTOR_NAMES[sector], "stats": sector_group_stats(rows, sector)}
            for sector in sectors
        ],
    }


@router.post("/save-computed")
async def save_computed_ratings(
    payload: dict = Body(...),
    user: CurrentUser = Depends(get_current_user),
):
    """Запись рассчитанного в браузере рейтинга руководителем сектора
    (Бочиус/Сорокин) — у него нет прав записи в Supabase напрямую. Строки
    чистятся по белому списку колонок (services/ratings_upload.py).
    Повторная загрузка того же period_label блокируется (409). При ошибке
    записи созданная загрузка удаляется целиком — частичных записей не
    остаётся. Видит руководитель после этого только данные своего сектора
    (restrict_to_sector_pair), как и раньше."""
    _require_sector_head(user)
    period_label = payload.get("period_label")
    if period_type_of(period_label) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректная метка периода")
    source_filename = payload.get("source_filename")
    if source_filename is not None and (not isinstance(source_filename, str) or len(source_filename) > 300):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректное имя файла")
    try:
        rows = sanitize_rows(payload.get("rows"))
    except UploadValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    # Расчёт в браузере шёл с весами секторов — присылает их снимком. Если
    # веса с тех пор изменились (подтверждена заявка), записать устаревший
    # расчёт нельзя: итоговые места, ЛГ и ЗП были бы по старым весам.
    try:
        client_weights = parse_snapshot(payload.get("weights_snapshot"))
    except WeightsValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Нет корректного снимка весов: {exc}")

    client = as_service()
    effective = await load_effective(client)
    if any(not weights_equal(client_weights[s], effective[s]["weights"]) for s in effective):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Веса секторов изменились с момента расчёта — обновите страницу и посчитайте файл заново",
        )
    existing = await client.get(
        "kpi_uploads",
        params={"period_label": f"eq.{period_label}", "select": "id", "limit": "1"},
    )
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"За период {period_label} отчёт уже загружен — повторная загрузка заблокирована",
        )

    created = await client.post(
        "kpi_uploads",
        [{"period_label": period_label, "source_filename": source_filename, "weights_snapshot": snapshot_of(effective)}],
    )
    upload_id = created[0]["id"]
    try:
        for i in range(0, len(rows), 200):
            chunk = [{**r, "upload_id": upload_id} for r in rows[i:i + 200]]
            await client.post("kpi_ratings", chunk, prefer="return=minimal")
    except Exception:
        try:
            await client.delete(f"kpi_uploads?id=eq.{upload_id}")
        except Exception:
            pass
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Не удалось записать рейтинг, загрузка отменена")
    return {"upload_id": upload_id, "rows": len(rows)}


async def _load_categories(user: CurrentUser) -> list[RatingCategory]:
    client = as_user(user.access_token)
    rows = await client.get("rating_categories", params={"select": "*", "order": "sort_order.asc"})
    fields = ("key", "label", "source_column", "weight", "direction", "enabled", "sort_order")
    return [RatingCategory(**{f: row[f] for f in fields}) for row in rows]


async def _load_supervisor_channels(user: CurrentUser) -> dict[str, str]:
    client = as_user(user.access_token)
    rows = await client.get("supervisor_channels", params={"select": "supervisor,channel"})
    return {row["supervisor"]: row["channel"] for row in rows}


async def _load_tier_coefficients(user: CurrentUser) -> list[float] | None:
    """10 чисел по тирам 1..10 из ladder_tier_coefficients. None, если
    таблица пустая/неполная — тогда ladder_groups сам подставит запасной
    вариант по умолчанию (TIER_COEFFICIENTS)."""
    client = as_user(user.access_token)
    rows = await client.get(
        "ladder_tier_coefficients",
        params={"select": "tier_number,coefficient", "order": "tier_number.asc"},
    )
    if len(rows) != 10:
        return None
    return [row["coefficient"] for row in rows]


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
    hours_norm: float = DEFAULT_HOURS_NORM,
    monthly_base_rate: float = DEFAULT_MONTHLY_BASE_RATE,
    dry_run: bool = False,
    user: CurrentUser = Depends(get_current_user),
):
    """Считает полный недельный рейтинг, сохраняет его в kpi_uploads/kpi_ratings
    и возвращает посчитанные строки вместе с id загрузки.

    period_label — метка периода для kpi_uploads (например '7-1' на неделю
    или '2026-07-27' на день) — как в старой JS-версии, формат не проверяем.
    hours_norm/monthly_base_rate — параметры формулы ЗП недели (см.
    services/salary.py: ставка_за_час = monthly_base_rate / hours_norm,
    база = ставка_за_час × "Рабочее время, ч" сотрудника из файла);
    учитываются только для недельных периодов, ввод не автоматический —
    вручную задаёт вызывающий (заменяет прежний weeks_in_month).
    dry_run — если true, считает всё как обычно (включая ЗП), но НИЧЕГО
    не пишет в kpi_uploads/kpi_ratings — только возвращает JSON. Для режима
    сравнения "старый JS vs новый backend" на реальных файлах, пока сам
    расчёт на проде не переключён. upload_id в ответе будет null.
    """
    if not user.is_admin_or_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только admin/manager могут считать недельный рейтинг")

    categories = await _load_categories(user)
    supervisor_channels = await _load_supervisor_channels(user)
    tier_coefficients = await _load_tier_coefficients(user)
    effective_weights = await load_effective(as_service())
    raw = await file.read()
    employees = parse_weekly_rating_excel(raw, supervisor_channels)
    if not employees:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не нашлось ни одной валидной строки в файле")

    try:
        results = compute_weekly_rating(
            employees, categories, na_predicate=is_na_row, tier_coefficients=tier_coefficients,
            sector_weights=weights_by_sector(effective_weights),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    warnings: list[str] = []
    if is_weekly_period_label(period_label):
        if all(e.get("work_hours") is None for e in employees):
            warnings.append(
                'Внимание: нет колонки "Рабочее время, ч" — ЗП не посчитана ни для кого этого периода.'
            )
        prev_coefficients = await _load_previous_week_coefficients(user, period_label)
        assign_salary(results, prev_coefficients, hours_norm, monthly_base_rate)

    client = as_user(user.access_token)
    upload_id = await maybe_save_weekly_rating(
        dry_run,
        lambda: save_weekly_rating(
            client, period_label, file.filename or "", results, snapshot_of(effective_weights)
        ),
    )

    return {
        "upload_id": upload_id,
        "dry_run": dry_run,
        "warnings": warnings,
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
