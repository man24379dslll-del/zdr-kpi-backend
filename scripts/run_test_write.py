"""Реально пишет тестовую строку в kpi_uploads/kpi_ratings через
service_role (в обход RLS) — для проверки, что схема payload совпадает
с реальной БД. Payload идентичен scripts/preview_test_write.py.

Удалить тестовые данные после проверки:
    delete from kpi_uploads where period_label = 'TEST-DELETE-ME';
(каскадно удалит связанные kpi_ratings)
"""
import asyncio
import json

from app.services.ratings_repository import save_weekly_rating
from app.supabase_client import as_service
from scripts.preview_test_write import PERIOD_LABEL, SOURCE_FILENAME, build_test_row


async def main() -> None:
    client = as_service()
    upload_id = await save_weekly_rating(client, PERIOD_LABEL, SOURCE_FILENAME, [build_test_row()])

    print("Записано.")
    print(f"upload_id = {upload_id}")

    uploads = await client.get("kpi_uploads", params={"id": f"eq.{upload_id}", "select": "*"})
    ratings = await client.get("kpi_ratings", params={"upload_id": f"eq.{upload_id}", "select": "*"})

    print("\nkpi_uploads:")
    print(json.dumps(uploads, ensure_ascii=False, indent=2))
    print("\nkpi_ratings:")
    print(json.dumps(ratings, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
