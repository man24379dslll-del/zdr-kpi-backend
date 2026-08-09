"""
Тонкая обёртка над Supabase REST (PostgREST) API через httpx.
Не используем supabase-py, чтобы не тащить лишнюю зависимость —
REST API у Supabase достаточно простой для наших нужд.

Два режима:
- as_user(access_token): запросы от имени залогиненного пользователя,
  RLS-политики применяются как для него (для чтения "своей" группы и т.д.)
- as_service(): запросы с service_role — обходит RLS полностью,
  использовать только там, где реально нужен полный доступ на сервере
  (например, при подтверждении, что вызывающий — admin/manager, уже
  проверено через as_user()).
"""
from __future__ import annotations

import httpx

from app.config import settings


class SupabaseClient:
    def __init__(self, bearer_token: str):
        self._token = bearer_token

    def _headers(self, extra: dict | None = None) -> dict:
        headers = {
            "apikey": settings.supabase_publishable_key,
            "Authorization": f"Bearer {self._token}",
        }
        if extra:
            headers.update(extra)
        return headers

    async def get(self, path: str, params: dict | None = None) -> list[dict]:
        async with httpx.AsyncClient(base_url=settings.supabase_url) as client:
            res = await client.get(f"/rest/v1/{path}", headers=self._headers(), params=params)
            res.raise_for_status()
            return res.json()

    async def post(self, path: str, json: list[dict] | dict, prefer: str = "return=representation") -> list[dict]:
        async with httpx.AsyncClient(base_url=settings.supabase_url) as client:
            res = await client.post(
                f"/rest/v1/{path}",
                headers=self._headers({"Content-Type": "application/json", "Prefer": prefer}),
                json=json,
            )
            res.raise_for_status()
            return res.json() if res.content else []

    async def patch(self, path: str, json: dict, prefer: str = "return=representation") -> list[dict]:
        async with httpx.AsyncClient(base_url=settings.supabase_url) as client:
            res = await client.patch(
                f"/rest/v1/{path}",
                headers=self._headers({"Content-Type": "application/json", "Prefer": prefer}),
                json=json,
            )
            res.raise_for_status()
            return res.json() if res.content else []

    async def delete(self, path: str) -> None:
        async with httpx.AsyncClient(base_url=settings.supabase_url) as client:
            res = await client.delete(f"/rest/v1/{path}", headers=self._headers())
            res.raise_for_status()

    async def auth_sign_in(self, email: str, password: str) -> dict:
        async with httpx.AsyncClient(base_url=settings.supabase_url) as client:
            res = await client.post(
                "/auth/v1/token",
                params={"grant_type": "password"},
                headers={"apikey": settings.supabase_publishable_key, "Content-Type": "application/json"},
                json={"email": email, "password": password},
            )
            res.raise_for_status()
            return res.json()


def as_user(access_token: str) -> SupabaseClient:
    """Клиент, действующий от имени залогиненного пользователя (уважает RLS)."""
    return SupabaseClient(access_token)


def as_service() -> SupabaseClient:
    """Клиент с полным доступом (service_role). Использовать осторожно —
    только на сервере, никогда не передавать этот ключ клиенту."""
    return SupabaseClient(settings.supabase_service_key)
