"""
db.py — робота з базою даних SQLite для програми ведення заявок ЧСМ.

Таблиці:
    price_history  — кожен імпорт прайс-листа записується сюди, тому
                      можна знати ціну товару на будь-яку дату.
    clients        — база покупців (ПІБ, телефон, область, місто, адреса).
    orders         — заявки (шапка).
    order_items    — товарні рядки заявок.
    sender_phones  — довідник "спосіб оплати -> телефон відправника".
    cities_seen    — міста, які вже вводились (для автодоповнення).
"""
import sqlite3
import os
from datetime import datetime, date

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "order_app.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            unit TEXT,
            price REAL NOT NULL,
            weight REAL,
            extra TEXT,               -- JSON з іншими характеристиками
            effective_date TEXT NOT NULL,   -- з якої дати ціна діє (YYYY-MM-DD)
            imported_at TEXT NOT NULL,      -- коли фактично завантажено
            source_file TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_price_code ON price_history(code)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_price_name ON price_history(name)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL UNIQUE,
            phone TEXT,
            oblast TEXT,
            city TEXT,
            address TEXT,
            carrier TEXT,
            carrier_branch TEXT,
            notes TEXT,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sender_phones (
            payment_method TEXT PRIMARY KEY,
            phone TEXT NOT NULL
        )
    """)
    cur.execute("""
        INSERT OR IGNORE INTO sender_phones (payment_method, phone)
        VALUES ('рр ІОМ', '096 356 65 18')
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT NOT NULL,
            order_date TEXT NOT NULL,
            buyer_name TEXT NOT NULL,
            buyer_address TEXT,
            responsible TEXT,
            payment_method TEXT,
            sender_phone TEXT,
            recipient_phone TEXT,
            carrier TEXT,
            carrier_branch TEXT,
            recipient_oblast TEXT,
            recipient_city TEXT,
            recipient_address TEXT,
            recipient_name TEXT,
            total_sum REAL,
            total_weight REAL,
            client_id INTEGER,
            file_name TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (client_id) REFERENCES clients(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            seq_no INTEGER NOT NULL,
            code TEXT,
            name TEXT NOT NULL,
            unit TEXT,
            qty REAL NOT NULL,
            price REAL NOT NULL,
            sum REAL NOT NULL,
            weight_unit REAL,
            weight_total REAL,
            FOREIGN KEY (order_id) REFERENCES orders(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cities_seen (
            oblast TEXT NOT NULL,
            city TEXT NOT NULL,
            PRIMARY KEY (oblast, city)
        )
    """)

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Прайс-лист
# ---------------------------------------------------------------------------

def import_price_rows(rows, effective_date, source_file):
    """
    rows: список dict з ключами code, name, unit, price, weight, extra(dict/None)
    effective_date: 'YYYY-MM-DD' — з якої дати ціни діють
    """
    import json
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.now().isoformat(timespec="seconds")
    for r in rows:
        cur.execute("""
            INSERT INTO price_history (code, name, unit, price, weight, extra,
                                        effective_date, imported_at, source_file)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r.get("code") or "",
            r["name"],
            r.get("unit") or "",
            float(r["price"]),
            float(r["weight"]) if r.get("weight") not in (None, "") else None,
            json.dumps(r.get("extra") or {}, ensure_ascii=False),
            effective_date,
            now,
            source_file,
        ))
    conn.commit()
    conn.close()


def get_active_catalog(as_of_date=None):
    """
    Повертає поточний каталог товарів (останню діючу ціну кожного коду/назви
    на задану дату). Якщо as_of_date=None — на сьогодні.
    """
    if as_of_date is None:
        as_of_date = date.today().isoformat()
    conn = get_connection()
    cur = conn.cursor()
    # для кожного коду беремо запис з найбільшою effective_date <= as_of_date,
    # а серед однакових effective_date — останній за imported_at
    cur.execute("""
        SELECT ph.*
        FROM price_history ph
        INNER JOIN (
            SELECT code, MAX(effective_date || '|' || imported_at) AS max_key
            FROM price_history
            WHERE effective_date <= ?
            GROUP BY code
        ) latest
        ON ph.code = latest.code
           AND (ph.effective_date || '|' || ph.imported_at) = latest.max_key
        ORDER BY ph.name
    """, (as_of_date,))
    result = [dict(row) for row in cur.fetchall()]
    conn.close()
    return result


def search_products(prefix, as_of_date=None, limit=15):
    """Пошук товарів у поточному каталозі за першими літерами назви."""
    catalog = get_active_catalog(as_of_date)
    prefix_lower = prefix.strip().lower()
    if not prefix_lower:
        return catalog[:limit]
    starts = [p for p in catalog if p["name"].lower().startswith(prefix_lower)]
    contains = [p for p in catalog if prefix_lower in p["name"].lower() and p not in starts]
    return (starts + contains)[:limit]


# ---------------------------------------------------------------------------
# Клієнти
# ---------------------------------------------------------------------------

def upsert_client(full_name, phone=None, oblast=None, city=None, address=None,
                   carrier=None, carrier_branch=None, notes=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM clients WHERE full_name = ?", (full_name,))
    row = cur.fetchone()
    if row:
        cid = row["id"]
        # оновлюємо лише непорожні поля, щоб не затирати збережене
        fields, values = [], []
        for col, val in [("phone", phone), ("oblast", oblast), ("city", city),
                          ("address", address), ("carrier", carrier),
                          ("carrier_branch", carrier_branch), ("notes", notes)]:
            if val:
                fields.append(f"{col} = ?")
                values.append(val)
        if fields:
            values.append(cid)
            cur.execute(f"UPDATE clients SET {', '.join(fields)} WHERE id = ?", values)
    else:
        cur.execute("""
            INSERT INTO clients (full_name, phone, oblast, city, address,
                                  carrier, carrier_branch, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (full_name, phone, oblast, city, address, carrier, carrier_branch,
              notes, datetime.now().isoformat(timespec="seconds")))
        cid = cur.lastrowid
    conn.commit()
    conn.close()
    return cid


def search_clients(prefix, limit=15):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM clients WHERE full_name LIKE ? ORDER BY full_name LIMIT ?",
                (prefix.strip() + "%", limit))
    result = [dict(row) for row in cur.fetchall()]
    conn.close()
    return result


def get_client_by_name(full_name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM clients WHERE full_name = ?", (full_name,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def remember_city(oblast, city):
    if not oblast or not city:
        return
    conn = get_connection()
    conn.execute("INSERT OR IGNORE INTO cities_seen (oblast, city) VALUES (?, ?)",
                 (oblast, city))
    conn.commit()
    conn.close()


def search_cities(oblast, prefix, limit=15):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT city FROM cities_seen
        WHERE oblast = ? AND city LIKE ? ORDER BY city LIMIT ?
    """, (oblast, prefix.strip() + "%", limit))
    result = [row["city"] for row in cur.fetchall()]
    conn.close()
    return result


# ---------------------------------------------------------------------------
# Відправник / способи оплати
# ---------------------------------------------------------------------------

def get_sender_phones():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sender_phones ORDER BY payment_method")
    result = {row["payment_method"]: row["phone"] for row in cur.fetchall()}
    conn.close()
    return result


def set_sender_phone(payment_method, phone):
    conn = get_connection()
    conn.execute("""
        INSERT INTO sender_phones (payment_method, phone) VALUES (?, ?)
        ON CONFLICT(payment_method) DO UPDATE SET phone = excluded.phone
    """, (payment_method, phone))
    conn.commit()
    conn.close()


def delete_sender_phone(payment_method):
    conn = get_connection()
    conn.execute("DELETE FROM sender_phones WHERE payment_method = ?", (payment_method,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Заявки
# ---------------------------------------------------------------------------

def save_order(header, items, file_name):
    """
    header: dict з полями заявки (див. схему orders)
    items: список dict з полями code, name, unit, qty, price, sum,
           weight_unit, weight_total
    Повертає id заявки.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO orders (order_number, order_date, buyer_name, buyer_address,
                             responsible, payment_method, sender_phone, recipient_phone,
                             carrier, carrier_branch, recipient_oblast, recipient_city,
                             recipient_address, recipient_name, total_sum, total_weight,
                             client_id, file_name, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        header["order_number"], header["order_date"], header["buyer_name"],
        header.get("buyer_address"), header.get("responsible"),
        header.get("payment_method"), header.get("sender_phone"),
        header.get("recipient_phone"), header.get("carrier"),
        header.get("carrier_branch"), header.get("recipient_oblast"),
        header.get("recipient_city"), header.get("recipient_address"),
        header.get("recipient_name"), header.get("total_sum"),
        header.get("total_weight"), header.get("client_id"), file_name,
        datetime.now().isoformat(timespec="seconds"),
    ))
    order_id = cur.lastrowid
    for i, it in enumerate(items, start=1):
        cur.execute("""
            INSERT INTO order_items (order_id, seq_no, code, name, unit, qty,
                                      price, sum, weight_unit, weight_total)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (order_id, i, it.get("code"), it["name"], it.get("unit"),
              it["qty"], it["price"], it["sum"], it.get("weight_unit"),
              it.get("weight_total")))
    conn.commit()
    conn.close()
    return order_id


def list_orders(limit=200):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,))
    result = [dict(row) for row in cur.fetchall()]
    conn.close()
    return result


def get_order_items(order_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM order_items WHERE order_id = ? ORDER BY seq_no", (order_id,))
    result = [dict(row) for row in cur.fetchall()]
    conn.close()
    return result
