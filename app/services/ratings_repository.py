"""
Запись результата недельного расчёта в Supabase — таблицы kpi_uploads
(одна строка = одна загрузка) и kpi_ratings (одна строка = один
сотрудник за этот период). Схема уже существует в базе (не создаём её
здесь), пишем через тот же REST-клиент, что и остальные роутеры
(supabase_client.as_user), чтобы соблюдались RLS-политики (писать
могут только admin/manager).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.rating_engine import EmployeeScore
from app.services.weekly_rating import group_channel_key

if TYPE_CHECKING:
    # Импорт только для типизации: supabase_client.py тянет app.config
    # (требует реальные SUPABASE_* переменные), не нужно для build_kpi_rating_row.
    from app.supabase_client import SupabaseClient


def _int_place(value):
    """Места каналов в kpi_ratings — integer; тир канала считает float
    (1.0, 2.0, ...), а JSON "3.0" в integer-колонку Postgres не принимает."""
    if value is None:
        return None
    return int(value) if float(value).is_integer() else value


def build_kpi_rating_row(upload_id: str, r: EmployeeScore) -> dict:
    raw = r.raw
    own_channel = group_channel_key(raw)  # какой канал настроен группе (ch_* ниже)
    return {
        "upload_id": upload_id,
        "supervisor": raw.get("supervisor"),
        "fio": r.fio,
        "status": raw.get("status"),
        "is_novice": raw.get("is_novice"),
        "channel": raw.get("channel"),

        "c1_sum": raw.get("c1_sum"),
        "c1_check": raw.get("c1_check"),
        "c1_conv": raw.get("c1_conv"),
        "c1_per_contact": raw.get("c1_per_contact"),
        "c1_place": r.places.get("c1"),
        "c1_score": r.scores.get("c1"),
        "c1_cards": raw.get("c1_cards"),

        "lk_sum": raw.get("lk_sum"),
        "lk_check": raw.get("lk_check"),
        "lk_conv": raw.get("lk_conv"),
        "lk_per_contact": raw.get("lk_per_contact"),
        "lk_place": r.places.get("lk"),  # numeric, не int — тир Б/В даёт дробное место
        "lk_score": r.scores.get("lk"),
        "lk_cards": raw.get("lk_cards"),

        # Канал группы (единый ch_*): данные/место/балл того канала, что
        # настроен группе — для просмотра и дашбордов, на total_score не
        # влияет (в нём уже обе категории ниже).
        "ch_sum": raw.get("ch_sum"),
        "ch_check": raw.get("ch_check"),
        "ch_conv": raw.get("ch_conv"),
        "ch_per_contact": raw.get("ch_per_contact"),
        "ch_place": _int_place(r.places.get("channel")),
        "ch_score": r.scores.get(own_channel),
        "ch_cards": raw.get("ch_cards"),

        # Радио+ТВ и Интернет — две отдельные категории рейтинга.
        "radio_sum": raw.get("radio_sum"),
        "radio_check": raw.get("radio_check"),
        "radio_conv": raw.get("radio_conv"),
        "radio_per_contact": raw.get("radio_per_contact"),
        "radio_cards": raw.get("radio_cards"),
        "radio_place": _int_place(r.places.get("radio")),
        "radio_score": r.scores.get("radio"),
        "inet_sum": raw.get("inet_sum"),
        "inet_check": raw.get("inet_check"),
        "inet_conv": raw.get("inet_conv"),
        "inet_per_contact": raw.get("inet_per_contact"),
        "inet_cards": raw.get("inet_cards"),
        "inet_place": _int_place(r.places.get("inet")),
        "inet_score": r.scores.get("inet"),

        "time_per_contact": raw.get("time_per_contact"),
        "time_place": r.places.get("time"),
        "time_score": r.scores.get("time"),

        "errors_pct": raw.get("errors_pct"),
        "errors_place": r.places.get("errors"),
        "errors_score": r.scores.get("errors"),
        "errors_count": raw.get("errors_count"),  # только для информации, не в расчёте

        "total_score": r.total_score,
        "final_place": r.final_place,
        "is_na": r.is_na,

        "tier": r.tier,
        "coefficient": r.coefficient,

        "bonus075": raw.get("bonus075"),
        "bonus2": raw.get("bonus2"),
        "salary": r.salary,  # None для дневных периодов, см. services/salary.py

        "work_hours": raw.get("work_hours"),  # участвует в формуле ЗП, см. services/salary.py
        "shift_count": raw.get("shift_count"),  # только для информации, в формулу не входит
    }


async def save_weekly_rating(
    client: "SupabaseClient",
    period_label: str,
    source_filename: str,
    results: list[EmployeeScore],
    weights_snapshot: dict | None = None,
) -> str:
    """Создаёт запись в kpi_uploads (с весами секторов, по которым посчитан
    период — services/sector_weights.snapshot_of), затем пишет по одной строке
    kpi_ratings на каждого сотрудника. Возвращает id созданной загрузки."""
    upload = {"period_label": period_label, "source_filename": source_filename}
    if weights_snapshot is not None:
        upload["weights_snapshot"] = weights_snapshot
    uploads = await client.post("kpi_uploads", upload)
    upload_id = uploads[0]["id"]

    rows = [build_kpi_rating_row(upload_id, r) for r in results]
    await client.post("kpi_ratings", rows, prefer="return=minimal")

    return upload_id


async def maybe_save_weekly_rating(dry_run: bool, save) -> str | None:
    """Ветвление "писать или не писать" для POST /ratings/compute?dry_run=
    (routers/ratings.py) — режим сравнения "старый JS vs новый backend" не
    должен трогать Supabase вообще. save — async callable без аргументов
    (обычно замыкание над save_weekly_rating(client, ...)); при dry_run=True
    НЕ вызывается вовсе (значит и никакого сетевого похода в Supabase не
    происходит), просто возвращается None. Вынесено в отдельную чистую
    функцию, чтобы тестировать без реального Supabase/.env — так же, как
    build_kpi_rating_row выше."""
    if dry_run:
        return None
    return await save()
