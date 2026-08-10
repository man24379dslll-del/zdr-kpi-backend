"""
POST /ratings/compute?dry_run= — режим сравнения "старый JS vs новый
backend": при dry_run=True ничего не должно попадать в Supabase. Сама
ветвящая логика вынесена в maybe_save_weekly_rating (services/
ratings_repository.py) специально для того, чтобы это можно было
проверить без реального Supabase/.env — как и остальные тесты в проекте.
"""
import asyncio

from app.services.ratings_repository import maybe_save_weekly_rating


def test_dry_run_true_never_calls_save_and_returns_none():
    calls = []

    async def fake_save():
        calls.append(1)
        return "fake-upload-id"

    result = asyncio.run(maybe_save_weekly_rating(True, fake_save))

    assert result is None
    assert calls == []  # save ни разу не вызван — ни один запрос к Supabase не ушёл


def test_dry_run_false_calls_save_and_returns_its_result():
    calls = []

    async def fake_save():
        calls.append(1)
        return "fake-upload-id"

    result = asyncio.run(maybe_save_weekly_rating(False, fake_save))

    assert result == "fake-upload-id"
    assert calls == [1]  # ровно один вызов — как раньше, без dry_run
