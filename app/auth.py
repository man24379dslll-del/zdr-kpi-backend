"""
Зависимость FastAPI для проверки авторизации.
Ожидает заголовок Authorization: Bearer <supabase access_token>,
достаёт профиль пользователя (роль, supervisor_name) из user_profiles.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException, status

from app.supabase_client import as_user


@dataclass
class CurrentUser:
    access_token: str
    user_id: str
    email: str
    role: str  # 'admin' | 'manager' | 'supervisor'
    supervisor_name: str | None
    display_name: str | None

    @property
    def is_admin_or_manager(self) -> bool:
        return self.role in ("admin", "manager")


async def get_current_user(authorization: str = Header(...)) -> CurrentUser:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Ожидается заголовок Authorization: Bearer <token>")
    token = authorization.removeprefix("Bearer ").strip()

    client = as_user(token)
    # /auth/v1/user отдаёт данные текущего пользователя по его токену
    import httpx

    from app.config import settings

    async with httpx.AsyncClient(base_url=settings.supabase_url) as http:
        res = await http.get(
            "/auth/v1/user",
            headers={"apikey": settings.supabase_publishable_key, "Authorization": f"Bearer {token}"},
        )
    if res.status_code != 200:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недействительный или истёкший токен")
    user = res.json()

    profiles = await client.get(
        "user_profiles",
        params={"id": f"eq.{user['id']}", "select": "role,supervisor_name,display_name"},
    )
    if not profiles:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Аккаунт есть, но для него не настроен профиль (роль). Обратитесь к администратору.",
        )
    profile = profiles[0]

    return CurrentUser(
        access_token=token,
        user_id=user["id"],
        email=user.get("email", ""),
        role=profile["role"],
        supervisor_name=profile.get("supervisor_name"),
        display_name=profile.get("display_name"),
    )


async def require_admin_or_manager(user: CurrentUser = Header(default=None)) -> CurrentUser:  # placeholder, see routers
    """См. использование через Depends(get_current_user) + ручную проверку
    user.is_admin_or_manager в самих эндпоинтах — так проще читать 403-сообщения."""
    return user
