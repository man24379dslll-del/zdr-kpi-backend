"""Превью payload'а для ручной проверки записи в Supabase — БЕЗ сети,
только показывает, что именно уйдёт в kpi_uploads/kpi_ratings, если
запустить scripts/run_test_write.py."""
from app.services.rating_engine import EmployeeScore
from app.services.ratings_repository import build_kpi_rating_row

PERIOD_LABEL = "TEST-DELETE-ME"
SOURCE_FILENAME = "test_manual_verification.xlsx"


def build_test_row() -> EmployeeScore:
    return EmployeeScore(
        fio="ТЕСТОВАЯ ЗАПИСЬ",
        raw={
            "supervisor": "TEST-DELETE-ME",
            "status": "",
            "is_novice": False,
            "channel": "radio",
            "c1_sum": 1, "c1_check": 1, "c1_conv": 1, "c1_per_contact": 1, "c1_cards": 1,
            "lk_sum": 1, "lk_check": 1, "lk_conv": 1, "lk_per_contact": 1, "lk_cards": 1,
            "ch_sum": 1, "ch_check": 1, "ch_conv": 1, "ch_per_contact": 1, "ch_cards": 1,
            "time_per_contact": 1, "errors_pct": 1,
            "bonus075": 1, "bonus2": 1,
        },
        places={"c1": 1, "lk": 1, "channel": 1, "time": 1, "errors": 1},
        scores={"c1": 1, "lk": 1, "channel": 1, "time": 1, "errors": 1},
        total_score=5,
        final_place=1,
        is_na=False,
        tier=1,
        coefficient=1.4,
    )


if __name__ == "__main__":
    import json

    kpi_uploads_payload = {"period_label": PERIOD_LABEL, "source_filename": SOURCE_FILENAME}
    kpi_ratings_payload = build_kpi_rating_row("<upload_id из ответа на вставку выше>", build_test_row())

    print("POST /rest/v1/kpi_uploads  (через service_role, в обход RLS)")
    print(json.dumps(kpi_uploads_payload, ensure_ascii=False, indent=2))
    print()
    print("POST /rest/v1/kpi_ratings  (upload_id подставится из ответа выше)")
    print(json.dumps(kpi_ratings_payload, ensure_ascii=False, indent=2))
