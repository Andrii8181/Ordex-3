# -*- coding: utf-8 -*-
"""
price_import.py — читання прайс-листа з Excel.

Очікується, що перший рядок файлу — заголовки колонок. Програма сама
намагається розпізнати колонки "Назва / Найменування", "Код / Артикул",
"Ціна", "Вага", "Од.вим." за їхніми заголовками (регістронезалежно,
українською). Всі інші колонки потрапляють у "extra" як додаткові
характеристики товару.
"""
import openpyxl

# ключові слова для розпізнавання колонок (все в нижньому регістрі)
COLUMN_HINTS = {
    "code": ["код", "артикул"],
    "name": ["назва", "найменування", "товар"],
    "price": ["ціна", "цена"],
    "weight": ["вага", "вес"],
    "unit": ["од.вим", "одиниця", "од вим", "ед.изм"],
}


def _match_column(header, hints):
    header_l = (header or "").strip().lower()
    for hint in hints:
        if hint in header_l:
            return True
    return False


def detect_columns(header_row):
    """header_row: список назв колонок (рядок 1 файлу). Повертає dict {роль: індекс}"""
    mapping = {}
    for idx, header in enumerate(header_row):
        for role, hints in COLUMN_HINTS.items():
            if role not in mapping and _match_column(str(header) if header else "", hints):
                mapping[role] = idx
    return mapping


def read_price_list(file_path, sheet_name=None):
    """
    Повертає (rows, warnings)
    rows: список dict {code, name, unit, price, weight, extra}
    warnings: список текстових попереджень (наприклад, рядки без ціни пропущено)
    """
    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active

    all_rows = list(ws.iter_rows(values_only=True))
    if not all_rows:
        return [], ["Файл порожній"]

    header_row = all_rows[0]
    mapping = detect_columns(header_row)

    warnings = []
    if "name" not in mapping:
        warnings.append("Не вдалось автоматично визначити колонку з назвою товару — "
                         "перевірте заголовки файлу.")
    if "price" not in mapping:
        warnings.append("Не вдалось автоматично визначити колонку з ціною — "
                         "перевірте заголовки файлу.")

    rows = []
    used_indices = set(mapping.values())
    for r_idx, row in enumerate(all_rows[1:], start=2):
        if row is None or all(v is None for v in row):
            continue
        name = row[mapping["name"]] if "name" in mapping and mapping["name"] < len(row) else None
        price = row[mapping["price"]] if "price" in mapping and mapping["price"] < len(row) else None
        if name is None or price is None:
            continue
        try:
            price_val = float(price)
        except (TypeError, ValueError):
            warnings.append(f"Рядок {r_idx}: некоректна ціна '{price}' — пропущено.")
            continue

        code = row[mapping["code"]] if "code" in mapping and mapping["code"] < len(row) else None
        unit = row[mapping["unit"]] if "unit" in mapping and mapping["unit"] < len(row) else None
        weight = row[mapping["weight"]] if "weight" in mapping and mapping["weight"] < len(row) else None
        try:
            weight_val = float(weight) if weight not in (None, "") else None
        except (TypeError, ValueError):
            weight_val = None

        extra = {}
        for c_idx, header in enumerate(header_row):
            if c_idx in used_indices:
                continue
            if header and c_idx < len(row) and row[c_idx] is not None:
                extra[str(header)] = row[c_idx]

        rows.append({
            "code": str(code).strip() if code is not None else "",
            "name": str(name).strip(),
            "unit": str(unit).strip() if unit is not None else "",
            "price": price_val,
            "weight": weight_val,
            "extra": extra,
        })

    return rows, warnings
