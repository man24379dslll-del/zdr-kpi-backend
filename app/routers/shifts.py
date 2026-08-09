"""
Загрузка отдельного файла "смены/часы": ФИО + кол-во отработанных
смен/часов + ставка за смену. Хранится в таблице shift_records,
привязана к периоду (upload_id), используется при расчёте ЗП как
дополнительное слагаемое (аналогично payroll_penalties).

Формат входного файла (xlsx): столбцы ФИО, Часы (или Смены), Ставка за смену.
Разбор — через pandas/openpyxl, см. services/excel_parser.py (TODO: перенести
сюда парсинг конкретно под этот формат, сейчас — заготовка).
"""
from __future__ import annotations

import io

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from app.auth import CurrentUser, get_current_user
from app.supabase_client import as_user

router = APIRouter(prefix="/shifts", tags=["shifts"])


@router.post("/upload")
async def upload_shifts_file(
    upload_id: str,
    file: UploadFile,
    user: CurrentUser = Depends(get_current_user),
):
    """upload_id — id соответствующей записи в kpi_uploads (тот же период,
    что и основной отчёт), чтобы данные о сменах были привязаны к неделе."""
    if not user.is_admin_or_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только admin/manager могут загружать файл смен")

    raw = await file.read()
    df = pd.read_excel(io.BytesIO(raw))

    # Ожидаемые колонки — подстроить под реальный формат файла, когда он появится.
    expected = {"ФИО", "Часы", "Ставка за смену"}
    missing = expected - set(df.columns)
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"В файле не хватает колонок: {', '.join(missing)}. "
            f"Есть: {', '.join(df.columns.astype(str))}",
        )

    records = []
    for _, row in df.iterrows():
        fio = str(row["ФИО"]).strip()
        if not fio or fio.lower() == "nan":
            continue
        hours = float(row["Часы"] or 0)
        rate = float(row["Ставка за смену"] or 0)
        records.append({
            "upload_id": upload_id,
            "fio": fio,
            "hours_worked": hours,
            "rate_per_shift": rate,
            "amount": hours * rate,  # TODO: уточнить формулу (за смену vs за час)
        })

    if not records:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не нашлось ни одной валидной строки в файле")

    client = as_user(user.access_token)
    await client.post("shift_records", records, prefer="return=minimal")
    return {"inserted": len(records)}


@router.get("")
async def list_shifts(upload_id: str, user: CurrentUser = Depends(get_current_user)):
    client = as_user(user.access_token)
    return await client.get("shift_records", params={"upload_id": f"eq.{upload_id}", "select": "*"})
