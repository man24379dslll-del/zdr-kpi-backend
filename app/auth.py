"""
Зависимость FastAPI для проверки авторизации.
Ожидает заголовок Authorization: Bearer <supabase access_token>,
достаёт профиль пользователя (роль, supervisor_names) из user_profiles.

supervisor_names — МАССИВ (не одна строка): у супервайзера может быть
несколько групп одновременно (например, Курбанова Зарина ведёт свою
группу "Супервайзер - Курбанова Зарина Рахимджановна" И одновременно
видит группу другого супервайзера — см. app/db/schema.sql — миграция
"Несколько групп у одного супервайзера"). Для обычного случая с одной
группой — массив из одного элемента. Фактическая фильтрация "видит
только СВОИ группы" делает RLS-политика "ratings_select" на стороне
Supabase (supervisor = ANY(...)) — здесь этот список только
прокидывается дальше, явной проверки в Python-коде роутеров нет (и не
было для старого supervisor_name тоже).
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
    supervisor_names: list[str] | None
    display_name: str | None

    @property
    def is_admin_or_manager(self) -> bool:
        return self.role in ("admin", "manager")


def resolve_supervisor_names(profile: dict) -> list[str] | None:
    """supervisor_names (новое, массив) — источник истины; supervisor_name
    (старое, одна строка) — фоллбэк, если для конкретного профиля миграция
    ещё не проставила supervisor_names (см. schema.sql). Один элемент в
    массиве ведёт себя так же, как раньше со сравнением на равенство
    (фильтрация делает RLS-политика "supervisor = ANY(my_supervisor_names())",
    ANY на массиве из 1 элемента эквивалентен "=")."""
    supervisor_names = profile.get("supervisor_names")
    if supervisor_names:
        return supervisor_names
    if profile.get("supervisor_name"):
        return [profile["supervisor_name"]]
    return None


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
        params={"id": f"eq.{user['id']}", "select": "role,supervisor_names,supervisor_name,display_name"},
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
        supervisor_names=resolve_supervisor_names(profile),
        display_name=profile.get("display_name"),
    )


async def require_admin_or_manager(user: CurrentUser = Header(default=None)) -> CurrentUser:  # placeholder, see routers
    """См. использование через Depends(get_current_user) + ручную проверку
    user.is_admin_or_manager в самих эндпоинтах — так проще читать 403-сообщения."""
    return user
