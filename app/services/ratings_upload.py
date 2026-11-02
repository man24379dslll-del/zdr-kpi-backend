"""
Загрузка уже посчитанного (в браузере) рейтинга руководителем сектора —
чистая логика без сети: проверка метки периода, белый список колонок
kpi_ratings, проверка типов значений, выбор предыдущей загрузки. См.
routers/ratings.py::save_computed_ratings / get_upload_context.

Расчёт рейтинга по-прежнему делает JS (static/index.html — основной
боевой путь), руководитель сектора лишь передаёт готовые строки через
бэкенд: у него нет прав записи в Supabase напрямую и RLS урезает чтение
до его групп. Строки, как и при загрузке админом (toDbRow во фронтенде),
содержат ТОЛЬКО перечисленные ниже колонки — всё остальное отбрасывается.
"""
from __future__ import annotations

import re

from app.services.periods import period_sort_value

WEEK_RE = re.compile(r"^\d{1,2}-\d{1,2}$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MAX_ROWS = 5000
MAX_TEXT = 300

TEXT_FIELDS = ("supervisor", "fio", "status", "channel")
BOOL_FIELDS = ("is_novice", "is_na")
NUMERIC_FIELDS = (
    "c1_sum", "c1_check", "c1_conv", "c1_per_contact", "c1_cards", "c1_place", "c1_score",
    "lk_sum", "lk_check", "lk_conv", "lk_per_contact", "lk_cards", "lk_place", "lk_score",
    "ch_sum", "ch_check", "ch_conv", "ch_per_contact", "ch_cards", "ch_place", "ch_score",
    "time_per_contact", "time_place", "time_score",
    "errors_pct", "errors_place", "errors_score", "errors_count",
    "total_score", "final_place", "tier", "coefficient",
    "bonus075", "bonus2", "salary", "work_hours", "shift_count",
)
ALLOWED_FIELDS = frozenset(TEXT_FIELDS + BOOL_FIELDS + NUMERIC_FIELDS)


class UploadValidationError(ValueError):
    pass


def period_type_of(period_label: str | None) -> str | None:
    if period_label and WEEK_RE.match(period_label):
        return "week"
    if period_label and DAY_RE.match(period_label):
        return "day"
    return None


def sanitize_rows(rows: list) -> list[dict]:
    """Белый список колонок + проверка типов. Лишние поля молча отбрасываются,
    неверный тип/пустые fio-supervisor — UploadValidationError (загрузка
    целиком отклоняется, а не пишется частично)."""
    if not isinstance(rows, list) or not rows:
        raise UploadValidationError("Нет строк для записи")
    if len(rows) > MAX_ROWS:
        raise UploadValidationError(f"Слишком много строк (максимум {MAX_ROWS})")
    clean: list[dict] = []
    for i, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise UploadValidationError(f"Строка {i + 1}: ожидался объект")
        row: dict = {}
        for key in TEXT_FIELDS:
            value = raw.get(key)
            if value is None:
                row[key] = None
            elif isinstance(value, str) and len(value) <= MAX_TEXT:
                row[key] = value
            else:
                raise UploadValidationError(f"Строка {i + 1}: поле {key} должно быть строкой")
        for key in BOOL_FIELDS:
            value = raw.get(key)
            if value is None:
                row[key] = None
            elif isinstance(value, bool):
                row[key] = value
            else:
                raise UploadValidationError(f"Строка {i + 1}: поле {key} должно быть true/false")
        for key in NUMERIC_FIELDS:
            value = raw.get(key)
            if value is None:
                row[key] = None
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                row[key] = value
            else:
                raise UploadValidationError(f"Строка {i + 1}: поле {key} должно быть числом")
        if not row["fio"] or not row["supervisor"]:
            raise UploadValidationError(f"Строка {i + 1}: нет ФИО или группы")
        if row["is_novice"] is None:
            row["is_novice"] = False
        clean.append(row)
    return clean


def find_previous_upload(uploads: list[dict], current_label: str, period_type: str) -> dict | None:
    """Точный перенос fetchLatestUpload из фронтенда: среди загрузок того же
    типа берётся период с наибольшим календарным значением СТРОГО раньше
    текущего; при нескольких загрузках одного периода — самая свежая
    (uploaded_at)."""
    ref = period_sort_value(period_type, current_label)
    if ref == "":
        return None
    candidates = []
    for u in uploads:
        label = u.get("period_label")
        if period_type_of(label) != period_type:
            continue
        value = period_sort_value(period_type, label)
        if value == "" or value >= ref:
            continue
        candidates.append((value, u.get("uploaded_at") or "", u))
    if not candidates:
        return None
    return max(candidates, key=lambda c: (c[0], c[1]))[2]
