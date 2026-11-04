"""
Конструктор рейтинга ПО СЕКТОРАМ: веса шести категорий у каждого сектора
(см. services/sector_weights.py).

  GET  /sector-weights                  — действующие веса секторов (читают все
                                          залогиненные — их использует расчёт
                                          в браузере), плюс заявки и журнал в
                                          пределах прав пользователя
  PUT  /sector-weights/{sector}         — админ/менеджер: применить сразу;
                                          руководитель сектора: подать заявку
                                          на СВОЙ сектор (ждёт подтверждения)
  POST /sector-weights/changes/{id}/approve | /reject — админ/менеджер

Запись идёт через service_role (у таблицы нет политик записи для клиентов):
права проверяются здесь. Веса действуют только на будущие загрузки.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import CurrentUser, get_current_user
from app.services.sector_weights import (
    DEFAULT_WEIGHTS,
    MAX_WEIGHT,
    SECTOR_NAMES,
    SECTOR_NUMBERS,
    WEIGHT_KEYS,
    WEIGHT_LABELS,
    WeightsValidationError,
    effective_weights,
    validate_weights,
    weights_equal,
)
from app.supabase_client import as_service

router = APIRouter(prefix="/sector-weights", tags=["sector-weights"])

HISTORY_LIMIT = 30
COMMENT_MAX = 500


class WeightsIn(BaseModel):
    weights: dict
    comment: str | None = None


class DecisionIn(BaseModel):
    comment: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _head_sector(user: CurrentUser) -> int | None:
    if user.is_sector2_head:
        return 2
    if user.is_sector3_head:
        return 3
    return None


def _actor_name(user: CurrentUser) -> str:
    return user.display_name or user.email or user.user_id


def _public(change: dict) -> dict:
    fields = ("id", "sector", "weights", "status", "comment", "requested_by_name", "requested_at",
              "decided_by_name", "decided_at")
    return {f: change.get(f) for f in fields}


def _check_comment(comment: str | None) -> str | None:
    if comment is None:
        return None
    comment = comment.strip()
    if len(comment) > COMMENT_MAX:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Комментарий длиннее {COMMENT_MAX} символов")
    return comment or None


def _parse_change_id(change_id: str) -> str:
    try:
        return str(uuid.UUID(change_id))
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")


async def _all_changes(client) -> list[dict]:
    return await client.get(
        "sector_weight_changes", params={"select": "*", "order": "requested_at.desc", "limit": "500"}
    )


@router.get("")
async def get_sector_weights(user: CurrentUser = Depends(get_current_user)):
    client = as_service()
    changes = await _all_changes(client)
    effective = effective_weights(changes)

    head_sector = _head_sector(user)
    if user.is_admin_or_manager:
        visible = changes
        editable = list(SECTOR_NUMBERS)
    elif head_sector is not None:
        visible = [c for c in changes if c.get("sector") == head_sector]
        editable = [head_sector]
    else:
        visible, editable = [], []

    return {
        "keys": list(WEIGHT_KEYS),
        "labels": WEIGHT_LABELS,
        "defaults": DEFAULT_WEIGHTS,
        "max_weight": MAX_WEIGHT,
        "sector_names": {str(s): n for s, n in SECTOR_NAMES.items()},
        "sectors": {str(s): eff for s, eff in effective.items()},
        "pending": [_public(c) for c in visible if c.get("status") == "pending"],
        "history": [_public(c) for c in visible if c.get("status") != "pending"][:HISTORY_LIMIT],
        "editable_sectors": editable,
        "can_approve": user.is_admin_or_manager,
    }


@router.put("/{sector}")
async def change_sector_weights(
    sector: int,
    payload: WeightsIn,
    user: CurrentUser = Depends(get_current_user),
):
    if sector not in SECTOR_NUMBERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Такого сектора нет")
    direct = user.is_admin_or_manager
    if not direct and _head_sector(user) != sector:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Менять веса можно только в своём секторе")
    try:
        weights = validate_weights(payload.weights)
    except WeightsValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    comment = _check_comment(payload.comment)

    client = as_service()
    changes = await _all_changes(client)
    current = effective_weights(changes)[sector]["weights"]
    if weights_equal(weights, current):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Эти веса уже действуют — менять нечего")

    # Любая ещё не рассмотренная заявка по сектору заменяется новой
    # (у сектора один руководитель — две параллельные заявки не нужны).
    if any(c.get("sector") == sector and c.get("status") == "pending" for c in changes):
        await client.patch(
            f"sector_weight_changes?sector=eq.{sector}&status=eq.pending",
            {"status": "cancelled", "decided_by": user.user_id, "decided_by_name": _actor_name(user),
             "decided_at": _now(), "comment": "Заменена новой записью"},
            prefer="return=minimal",
        )

    row = {
        "sector": sector,
        "weights": weights,
        "comment": comment,
        "requested_by": user.user_id,
        "requested_by_name": _actor_name(user),
        "status": "approved" if direct else "pending",
    }
    if direct:
        row.update({"decided_by": user.user_id, "decided_by_name": _actor_name(user), "decided_at": _now()})
    created = await client.post("sector_weight_changes", row)
    return {"applied": direct, "change": _public(created[0])}


async def _decide(change_id: str, decision: str, comment: str | None, user: CurrentUser) -> dict:
    if not user.is_admin_or_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Решение принимает только админ/менеджер")
    change_id = _parse_change_id(change_id)
    client = as_service()
    rows = await client.get(
        "sector_weight_changes", params={"id": f"eq.{change_id}", "select": "*", "limit": "1"}
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    if rows[0].get("status") != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Заявка уже рассмотрена")
    if decision == "approved":
        try:
            validate_weights(rows[0].get("weights"))
        except WeightsValidationError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Веса в заявке некорректны: {exc}")
    patch = {"status": decision, "decided_by": user.user_id, "decided_by_name": _actor_name(user),
             "decided_at": _now()}
    if comment:
        patch["comment"] = comment
    # фильтр по status=pending — защита от двойного решения параллельными запросами
    updated = await client.patch(f"sector_weight_changes?id=eq.{change_id}&status=eq.pending", patch)
    if not updated:
        raise HTTPException(status.HTTP_409_CONFLICT, "Заявка уже рассмотрена")
    return _public(updated[0])


@router.post("/changes/{change_id}/approve")
async def approve_change(change_id: str, payload: DecisionIn | None = None, user: CurrentUser = Depends(get_current_user)):
    comment = _check_comment(payload.comment) if payload else None
    return await _decide(change_id, "approved", comment, user)


@router.post("/changes/{change_id}/reject")
async def reject_change(change_id: str, payload: DecisionIn | None = None, user: CurrentUser = Depends(get_current_user)):
    comment = _check_comment(payload.comment) if payload else None
    return await _decide(change_id, "rejected", comment, user)
