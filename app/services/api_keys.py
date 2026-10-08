"""
Внешние API-ключи (только чтение, см. routers/external.py). Чистая логика
без сети — тестируется отдельно: генерация/хэш ключа, определение реального
IP клиента за прокси Railway, проверка списка разрешённых адресов, лимит
запросов.

В базе (таблица api_keys) хранится ТОЛЬКО SHA-256 от ключа. Сам ключ
показывается один раз при создании (scripts/create_api_key.py).
"""
from __future__ import annotations

import hashlib
import ipaddress
import secrets
import time
from collections import deque

SCOPE_OPERATORS_READ = "operators_read"


def generate_key() -> str:
    """>= 32 байт случайности (token_urlsafe(32) даёт 43 символа)."""
    return secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def client_ip(forwarded_for: str | None, peer: str | None, trusted_hops: int) -> str | None:
    """Реальный адрес клиента за прокси.

    X-Forwarded-For — список "клиент, прокси1, прокси2...": КАЖДЫЙ прокси
    дописывает в КОНЕЦ адрес, от которого получил запрос. Левые элементы
    клиент может подставить сам (поддельный заголовок), поэтому им верить
    нельзя. Доверяем только записям, добавленным нашими прокси: при
    trusted_hops=1 (Railway — один прокси перед приложением) берём ПОСЛЕДНИЙ
    элемент, при 2 — предпоследний и т.д. trusted_hops=0 или слишком короткая
    цепочка — игнорируем заголовок и берём адрес TCP-соединения (peer)."""
    if trusted_hops > 0 and forwarded_for:
        parts = [p.strip() for p in forwarded_for.split(",") if p.strip()]
        if len(parts) >= trusted_hops:
            return parts[-trusted_hops]
    return peer


def ip_allowed(ip: str | None, allowed_ips: list[str] | None) -> bool:
    """Пустой/None список — ограничения по IP нет. Иначе IP должен попасть в
    один из адресов/подсетей. Нераспознанный IP или некорректная запись в
    списке — "не совпало" (fail closed), без исключений."""
    if not allowed_ips:
        return True
    try:
        addr = ipaddress.ip_address(ip or "")
    except ValueError:
        return False
    for entry in allowed_ips:
        try:
            if addr in ipaddress.ip_network(str(entry).strip(), strict=False):
                return True
        except ValueError:
            continue
    return False


class RateLimiter:
    """Скользящее окно: не более `limit` событий на ключ за `window` секунд.
    Состояние в памяти процесса — при нескольких инстансах лимит считается
    на каждый отдельно."""

    def __init__(self, limit: int, window: float = 60.0, clock=time.monotonic):
        self.limit = limit
        self.window = window
        self._clock = clock
        self._hits: dict[str, deque] = {}

    def _expire(self, hits: deque, now: float) -> None:
        while hits and now - hits[0] >= self.window:
            hits.popleft()

    def peek(self, key: str) -> bool:
        """True, если лимит ещё не исчерпан (событие НЕ записывается)."""
        hits = self._hits.get(key)
        if not hits:
            return True
        self._expire(hits, self._clock())
        return len(hits) < self.limit

    def allow(self, key: str) -> bool:
        """Записывает событие и возвращает True, если лимит не превышен."""
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        self._expire(hits, now)
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        if len(self._hits) > 10_000:
            self._prune(now)
        return True

    def _prune(self, now: float) -> None:
        for k in [k for k, h in self._hits.items() if not h or now - h[-1] >= self.window]:
            del self._hits[k]
