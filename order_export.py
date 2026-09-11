# -*- coding: utf-8 -*-
"""
order_export.py — формування Excel-файлу заявки за структурою зразка
"Балабан__17_07_26__270_.xlsx".
"""
import os
import re
import openpyxl
from openpyxl.styles import Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from datetime import datetime

THIN = Side(style="thin")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
BOLD = Font(bold=True)


def sanitize_filename_part(text):
    text = (text or "").strip()
    text = re.sub(r'[\\/:*?"<>|]', "", text)
    return text


def build_filename(buyer_full_name, order_date, order_number):
    """Прізвище_ДД_ММ_РР_(номер).xlsx — за зразком назви файлу з прикладу."""
    surname = buyer_full_name.split()[0] if buyer_full_name.split() else "Заявка"
    surname = sanitize_filename_part(surname)
    date_part = order_date.strftime("%d_%m_%y")
    return f"{surname}__{date_part}__{order_number}_.xlsx"


def generate_order_excel(header, items, output_path):
    """
    header: dict з полями:
        order_number, order_date (datetime), buyer_name, buyer_address,
        responsible, payment_method, sender_phone, recipient_phone,
        carrier, carrier_branch, recipient_address (текст: область+місто),
        recipient_name
    items: список dict {seq_no, name, code, unit, qty, price, sum,
                         weight_unit, weight_total}
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Заявка"

    def merge_set(rng, value=None, bold=False, align=None):
        ws.merge_cells(rng)
        top_left = rng.split(":")[0]
        cell = ws[top_left]
        if value is not None:
            cell.value = value
        if bold:
            cell.font = BOLD
        if align:
            cell.alignment = Alignment(horizontal=align)
        return cell

    merge_set("A1:D1", f"Заявка  № {header['order_number']}", bold=True)
    ws["E1"] = "Дата"
    date_cell = merge_set("F1:G1", header["order_date"])
    date_cell.number_format = "dd.mm.yyyy"

    merge_set("A2:B2", "Покупець     ")
    merge_set("C2:G2", header.get("buyer_name", ""))

    merge_set("A3:B3", "Адреса покупця")
    merge_set("C3:G3", header.get("buyer_address", ""))

    merge_set("A4:B4", "Телефон відправника")
    merge_set("C4:G4", header.get("sender_phone", ""))

    merge_set("A5:B5", "Відповідальний, ПІБ")
    merge_set("C5:D5", header.get("responsible", ""))
    ws["E5"] = "опл"
    merge_set("F5:G5", header.get("payment_method", ""))

    merge_set("A6:B6", "Телефон одержувача")
    merge_set("C6:G6", header.get("recipient_phone", ""))

    merge_set("A7:B7", "Перевізник")
    carrier_text = header.get("carrier", "")
    if header.get("carrier_branch"):
        carrier_text = f"{carrier_text} {header['carrier_branch']}"
    merge_set("C7:G7", carrier_text)

    merge_set("A8:B8", "Адреса одержувача")
    merge_set("C8:G8", header.get("recipient_address", ""))

    merge_set("A9:B9", "Одержувач, ПІБ")
    merge_set("C9:G9", header.get("recipient_name", ""))

    next_row = 10
    if header.get("ttn"):
        merge_set(f"A{next_row}:B{next_row}", "№ ТТН")
        ttn_cell = merge_set(f"C{next_row}:G{next_row}", header["ttn"], bold=True)
        next_row += 1

    headers_row = next_row
    vat_enabled = bool(header.get("vat_enabled"))
    col_defs = [
        ("seq_no", "№П/п", 6),
        ("name", "Найменування", 22),
        ("code", None, 14),
        ("unit", "Од.вим", 8),
        ("qty", "К-сть", 7),
        ("price", "Ціна ", 9),
    ]
    if vat_enabled:
        col_defs.append(("price_vat", "Ціна з ПДВ", 11))
    col_defs += [
        ("sum", "Сумма", 10),
        ("weight_unit", "Вага, кг", 9),
        ("weight_total", "Вага, всього", 11),
    ]
    col_letters = {key: get_column_letter(i + 1) for i, (key, _title, _w) in enumerate(col_defs)}
    last_col_letter = col_letters[col_defs[-1][0]]

    name_col = col_letters["name"]
    code_col = col_letters["code"]
    ws.merge_cells(f"{name_col}{headers_row}:{code_col}{headers_row}")
    for key, title, _w in col_defs:
        if title is None:
            continue
        cell = ws[f"{col_letters[key]}{headers_row}"]
        cell.value = title
        cell.font = BOLD
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
        cell.border = BORDER

    total_sum = 0.0
    total_weight = 0.0
    row = headers_row + 1
    for it in items:
        for key, _title, _w in col_defs:
            ws[f"{col_letters[key]}{row}"] = it.get(key, "" if key == "code" or key == "unit" else 0)
        for _key, _title, _w in col_defs:
            ws[f"{col_letters[_key]}{row}"].border = BORDER
        total_sum += it.get("sum") or 0
        total_weight += it.get("weight_total") or 0
        row += 1

    sum_col = col_letters["sum"]
    weight_total_col = col_letters["weight_total"]
    ws[f"{sum_col}{row}"] = round(total_sum, 2)
    ws[f"{weight_total_col}{row}"] = round(total_weight, 2)
    ws[f"{sum_col}{row}"].font = BOLD
    ws[f"{weight_total_col}{row}"].font = BOLD

    for key, _title, width in col_defs:
        ws.column_dimensions[col_letters[key]].width = width

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    wb.save(output_path)
    return output_path
