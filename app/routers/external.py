"""
Внешний доступ ТОЛЬКО НА ЧТЕНИЕ (аффилейт-направление Force): отдельный от
токенов пользователей Supabase тип доступа — заголовок X-API-Key.

Ключ открывает только GET /external/* со scope 'operators_read'. Эндпоинт
читает данные через service-ключ, поэтому набор полей ответа — явный
whitelist (OPERATOR_FIELDS), строки kpi_ratings целиком наружу не отдаются.
Штрафы/премии/ЗП/бонусы/коэффициенты/реквизиты не включаются намеренно.
Ключи хранятся в api_keys только как SHA-256 хэш (см. schema.sql,
scripts/create_api_key.py).
"""
from __future__ import annotations

import hmac
import logging
import re
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.config import settings
from app.services.api_keys import SCOPE_OPERATORS_READ, RateLimiter, client_ip, hash_key, ip_allowed
from app.services.payroll import is_weekly_period_label
from app.supabase_client import as_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/external", tags=["external"])

# Единственные поля kpi_ratings, которые уходят наружу (period_label берётся
# из kpi_uploads).
OPERATOR_FIELDS = ("fio", "supervisor", "work_hours", "shift_count", "final_place")

PAGE_SIZE = 1000  # лимит строк PostgREST за запрос
PERIOD_RE = re.compile(r"^[0-9A-Za-z._-]{1,32}$")
LAST_USED_TOUCH_INTERVAL = 60.0  # секунд между обновлениями last_used_at

_key_limiter = RateLimiter(limit=settings.external_rate_limit_per_minute)
# Неудачные попытки с одного IP (мусорные ключи) не должны долбить базу.
_fail_limiter = RateLimiter(limit=20)
_last_touch: dict[str, float] = {}


async def _find_key(key_hash: str) -> dict | None:
    rows = await as_service().get(
        "api_keys",
        params={
            "key_hash": f"eq.{key_hash}",
            "select": "id,name,key_hash,scope,allowed_ips,revoked_at",
            "limit": "1",
        },
    )
    return rows[0] if rows else None


async def _touch_last_used(key_id: str) -> None:
    now = time.monotonic()
    if now - _last_touch.get(key_id, -LAST_USED_TOUCH_INTERVAL) < LAST_USED_TOUCH_INTERVAL:
        return
    _last_touch[key_id] = now
    try:
        await as_service().patch(
            f"api_keys?id=eq.{key_id}",
            {"last_used_at": datetime.now(timezone.utc).isoformat()},
            prefer="return=minimal",
        )
    except Exception:  # best-effort: статистика не должна ронять запрос
        logger.warning("не удалось обновить last_used_at для ключа %s", key_id)


async def require_operators_key(request: Request) -> dict:
    ip = client_ip(
        request.headers.get("x-forwarded-for"),
        request.client.host if request.client else None,
        settings.trusted_proxy_hops,
    )
    ip_bucket = ip or "unknown"

    presented = request.headers.get("x-api-key")
    if not presented:
        raise HTTPException(status_code=401, detail="Требуется заголовок X-API-Key")
    if not _fail_limiter.peek(ip_bucket):
        raise HTTPException(status_code=429, detail="Слишком много неудачных попыток", headers={"Retry-After": "60"})

    presented_hash = hash_key(presented)
    try:
        record = await _find_key(presented_hash)
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Хранилище ключей недоступно")

    valid = (
        record is not None
        and hmac.compare_digest(str(record.get("key_hash", "")), presented_hash)
        and not record.get("revoked_at")
    )
    if not valid:
        _fail_limiter.allow(ip_bucket)
        raise HTTPException(status_code=401, detail="Неверный или отозванный ключ")

    if record.get("scope") != SCOPE_OPERATORS_READ:
        raise HTTPException(status_code=403, detail="Ключ не имеет доступа к этому ресурсу")
    if not ip_allowed(ip, record.get("allowed_ips")):
        raise HTTPException(status_code=403, detail="Доступ с этого адреса запрещён")
    if not _key_limiter.allow(record["id"]):
        raise HTTPException(status_code=429, detail="Превышен лимит запросов", headers={"Retry-After": "60"})

    await _touch_last_used(record["id"])
    return record


async def _load_latest_upload(period_label: str) -> dict | None:
    """Если на период загружено несколько файлов (повторная загрузка), берём
    самую позднюю — иначе операторы задвоились бы."""
    rows = await as_service().get(
        "kpi_uploads",
        params={
            "period_label": f"eq.{period_label}",
            "select": "id,period_label",
            "order": "uploaded_at.desc",
            "limit": "1",
        },
    )
    return rows[0] if rows else None


async def _load_ratings(upload_id: str) -> list[dict]:
    """Только основные строки (is_novice=false): у новичка в kpi_ratings
    лежит ещё и дубль для общего списка новичков — в выдаче он был бы дважды."""
    client = as_service()
    out: list[dict] = []
    offset = 0
    while True:
        page = await client.get(
            "kpi_ratings",
            params={
                "upload_id": f"eq.{upload_id}",
                "is_novice": "eq.false",
                "select": ",".join(OPERATOR_FIELDS),
                "order": "fio.asc,supervisor.asc",
                "limit": str(PAGE_SIZE),
                "offset": str(offset),
            },
        )
        out.extend(page)
        if len(page) < PAGE_SIZE:
            return out
        offset += PAGE_SIZE


def to_operator(row: dict, period_label: str) -> dict:
    """Явный whitelist: только перечисленные поля, всё остальное отбрасывается."""
    item = {"fio": row.get("fio"), "supervisor": row.get("supervisor"), "period_label": period_label}
    for field in ("work_hours", "shift_count", "final_place"):
        item[field] = row.get(field)
    return item


@router.get("/operators")
async def list_operators(
    period: str = Query(..., description="Метка периода: 7-1 (неделя) или 2026-07-27 (день)"),
    type: str = Query(..., pattern="^(week|day)$"),
    _key: dict = Depends(require_operators_key),
):
    if not PERIOD_RE.match(period):
        raise HTTPException(status_code=400, detail="Некорректная метка периода")
    if is_weekly_period_label(period) != (type == "week"):
        raise HTTPException(status_code=400, detail="Метка периода не соответствует типу")
    try:
        upload = await _load_latest_upload(period)
        if upload is None:
            raise HTTPException(status_code=404, detail="Период не найден")
        rows = await _load_ratings(upload["id"])
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Хранилище данных недоступно")
    operators = [to_operator(r, upload["period_label"]) for r in rows]
    return {"period": upload["period_label"], "type": type, "count": len(operators), "operators": operators}
