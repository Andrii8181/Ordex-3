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
import sys
import json
from datetime import datetime, date


def _get_persistent_base_dir():
    """
    Повертає папку, де мають зберігатись файли програми (база даних,
    заявки), яка НЕ зникає після закриття програми.

    Критично важливо для зібраного .exe: PyInstaller (--onefile) при
    кожному запуску розпаковує програму у ТИМЧАСОВУ папку, і саме туди
    вказує __file__ всередині запущеної програми. Ця тимчасова папка
    видаляється Windows одразу після закриття програми — тому раніше
    база даних і всі файли фактично створювались "у нікуди" й губились
    при кожному перезапуску. Натомість sys.executable завжди вказує на
    справжнє розташування самого .exe-файлу, яке не зникає.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


DB_PATH = os.path.join(_get_persistent_base_dir(), "order_app.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_column(conn, table, column, coltype):
    """Додає колонку до вже існуючої таблиці, якщо її ще немає (безпечна міграція)."""
    cur = conn.execute(f"PRAGMA table_info({table})")
    existing = {row["name"] for row in cur.fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


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
            delivery_type TEXT,        -- 'branch' (на відділення) або 'address' (адресна)
            street TEXT,
            building TEXT,
            apartment TEXT,
            notes TEXT,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sender_phones (
            payment_method TEXT PRIMARY KEY,
            phone TEXT NOT NULL,
            sender_name TEXT
        )
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
            delivery_type TEXT,
            street TEXT,
            building TEXT,
            apartment TEXT,
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS carrier_credentials (
            carrier TEXT PRIMARY KEY,
            api_key TEXT,
            extra TEXT,          -- JSON з додатковими полями (місто/відділення відправника тощо)
            updated_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Об'єднаний профіль відправника: спосіб оплати + телефон/ім'я + перевізник,
    # яким саме цей відправник відправляє, + його API-ключ і дані для ТТН.
    # Один бізнес може мати кілька відправників, і кожен може працювати
    # з іншим перевізником/акаунтом — тому це окремі рядки, не один спільний ключ.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS senders (
            payment_method TEXT PRIMARY KEY,
            phone TEXT,
            sender_name TEXT,
            carrier TEXT,
            api_key TEXT,
            extra TEXT,           -- JSON: sender_city, sender_warehouse,
                                   -- sender_counterparty_ref, sender_contact_ref
            updated_at TEXT
        )
    """)

    conn.commit()

    # безпечна міграція: додає нові колонки, якщо база створена старою версією програми
    for col, coltype in [("delivery_type", "TEXT"), ("street", "TEXT"),
                          ("building", "TEXT"), ("apartment", "TEXT")]:
        _ensure_column(conn, "clients", col, coltype)
        _ensure_column(conn, "orders", col, coltype)
    for col, coltype in [("ttn", "TEXT"), ("ttn_status", "TEXT"), ("ttn_error", "TEXT")]:
        _ensure_column(conn, "orders", col, coltype)
    for col, coltype in [("tracking_status", "TEXT"), ("tracking_status_raw", "TEXT"),
                          ("tracking_updated_at", "TEXT"), ("tracking_delivered", "INTEGER")]:
        _ensure_column(conn, "orders", col, coltype)
    _ensure_column(conn, "orders", "sender_name", "TEXT")
    _ensure_column(conn, "sender_phones", "sender_name", "TEXT")
    for col, coltype in [("payer_type", "TEXT"), ("seats_amount", "INTEGER"),
                          ("cod_amount", "REAL")]:
        _ensure_column(conn, "orders", col, coltype)
    _ensure_column(conn, "orders", "ttn_ref", "TEXT")
    _ensure_column(conn, "orders", "recipient_type", "TEXT")
    _ensure_column(conn, "orders", "recipient_edrpou", "TEXT")
    _ensure_column(conn, "orders", "sender_warehouse_number", "TEXT")
    _ensure_column(conn, "orders", "ttn_pdf_path", "TEXT")
    _ensure_column(conn, "orders", "order_status", "TEXT")

    _migrate_to_senders_table(conn)
    conn.commit()
    conn.close()


def _migrate_to_senders_table(conn):
    """
    Одноразова міграція для тих, хто вже налаштував телефони відправника
    та/або API-ключі перевізників окремо (до об'єднання в один профіль).
    Не перезаписує senders, якщо там уже щось є.
    """
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM senders")
    if cur.fetchone()["c"] > 0:
        return

    cur.execute("SELECT * FROM sender_phones")
    old_phones = cur.fetchall()
    if not old_phones:
        return

    cur.execute("SELECT * FROM carrier_credentials")
    old_creds = cur.fetchall()
    # якщо налаштовано рівно одного перевізника — прив'язуємо його ключ
    # до всіх наявних способів оплати (найкраще припущення без втрати даних)
    single_cred = old_creds[0] if len(old_creds) == 1 else None

    for row in old_phones:
        carrier = single_cred["carrier"] if single_cred else None
        api_key = single_cred["api_key"] if single_cred else None
        extra = single_cred["extra"] if single_cred else None
        cur.execute("""
            INSERT OR IGNORE INTO senders
                (payment_method, phone, sender_name, carrier, api_key, extra, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (row["payment_method"], row["phone"], row["sender_name"],
              carrier, api_key, extra, datetime.now().isoformat(timespec="seconds")))


# ---------------------------------------------------------------------------
# Налаштування програми (ключ-значення)
# ---------------------------------------------------------------------------

def get_setting(key, default=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_connection()
    conn.execute("""
        INSERT INTO app_settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, str(value)))
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


def search_products_by_code(prefix, as_of_date=None, limit=15):
    """
    Пошук товарів за кодом — потрібен, коли одна й та сама назва товару
    (наприклад "Виток") має кілька модифікацій з різними кодами й цінами,
    і користувач хоче знайти чи звірити потрібний код напряму.
    """
    catalog = get_active_catalog(as_of_date)
    prefix_lower = prefix.strip().lower()
    if not prefix_lower:
        return catalog[:limit]
    matches = [p for p in catalog if p.get("code") and prefix_lower in p["code"].lower()]
    return matches[:limit]


# ---------------------------------------------------------------------------
# Клієнти
# ---------------------------------------------------------------------------

def upsert_client(full_name, phone=None, oblast=None, city=None, address=None,
                   carrier=None, carrier_branch=None, delivery_type=None,
                   street=None, building=None, apartment=None, notes=None):
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
                          ("carrier_branch", carrier_branch),
                          ("delivery_type", delivery_type), ("street", street),
                          ("building", building), ("apartment", apartment),
                          ("notes", notes)]:
            if val:
                fields.append(f"{col} = ?")
                values.append(val)
        if fields:
            values.append(cid)
            cur.execute(f"UPDATE clients SET {', '.join(fields)} WHERE id = ?", values)
    else:
        cur.execute("""
            INSERT INTO clients (full_name, phone, oblast, city, address,
                                  carrier, carrier_branch, delivery_type,
                                  street, building, apartment, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (full_name, phone, oblast, city, address, carrier, carrier_branch,
              delivery_type, street, building, apartment, notes,
              datetime.now().isoformat(timespec="seconds")))
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


def _normalize_phone(phone):
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def format_phone_display(phone):
    """
    Приводить будь-який введений телефон до єдиного вигляду +380XXXXXXXXX
    (стандарт, який вимагають перевізники для ТТН). Розпізнає українські
    номери в популярних форматах: "0671112233", "380671112233",
    "+380671112233", з пробілами/дужками/тире — усе це стає
    "+380671112233". Якщо номер не схожий на український мобільний
    (інша кількість цифр) — повертає його як є, без вигадування зайвого.
    """
    digits = _normalize_phone(phone)
    if not digits:
        return phone or ""
    if digits.startswith("380") and len(digits) == 12:
        pass
    elif digits.startswith("0") and len(digits) == 10:
        digits = "380" + digits[1:]
    elif len(digits) == 9:
        digits = "380" + digits
    else:
        return phone.strip() if phone else ""  # незвичний формат — не чіпаємо
    return "+" + digits


def format_phone_for_api(phone):
    """
    Те саме, що format_phone_display, але без символу '+' — саме такий
    вигляд (лише цифри, з кодом країни 380) очікують методи API
    перевізників (SendersPhone/RecipientsPhone тощо).
    """
    display = format_phone_display(phone)
    return display[1:] if display.startswith("+") else display


def search_clients_by_phone(prefix, limit=15):
    """
    Пошук клієнта за телефоном — стійкий до форматування (пробіли, дужки,
    тире): порівнюються лише цифри. Повертає клієнтів, чий номер містить
    введені цифри як підрядок (щоб знайти навіть за останніми цифрами).
    """
    digits = _normalize_phone(prefix)
    if not digits:
        return []
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM clients WHERE phone IS NOT NULL AND phone != ''")
    result = []
    for row in cur.fetchall():
        if digits in _normalize_phone(row["phone"]):
            result.append(dict(row))
            if len(result) >= limit:
                break
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
# Відправники (профіль: спосіб оплати + телефон/ім'я + перевізник + API-ключ)
# ---------------------------------------------------------------------------

def _sender_row_to_dict(row):
    extra = {}
    if row["extra"]:
        try:
            extra = json.loads(row["extra"])
        except (ValueError, TypeError):
            extra = {}
    return {
        "payment_method": row["payment_method"],
        "phone": row["phone"],
        "sender_name": row["sender_name"],
        "carrier": row["carrier"],
        "api_key": row["api_key"],
        "extra": extra,
    }


def get_senders():
    """Повертає список усіх профілів відправників (список dict)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM senders ORDER BY payment_method")
    result = [_sender_row_to_dict(row) for row in cur.fetchall()]
    conn.close()
    return result


def get_sender(payment_method):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM senders WHERE payment_method = ?", (payment_method,))
    row = cur.fetchone()
    conn.close()
    return _sender_row_to_dict(row) if row else None


def set_sender(payment_method, phone, sender_name=None, carrier=None,
               api_key=None, extra=None):
    conn = get_connection()
    conn.execute("""
        INSERT INTO senders (payment_method, phone, sender_name, carrier,
                              api_key, extra, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(payment_method) DO UPDATE SET
            phone = excluded.phone,
            sender_name = excluded.sender_name,
            carrier = excluded.carrier,
            api_key = excluded.api_key,
            extra = excluded.extra,
            updated_at = excluded.updated_at
    """, (payment_method, phone, sender_name, carrier, api_key,
          json.dumps(extra or {}, ensure_ascii=False),
          datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    conn.close()


def delete_sender(payment_method):
    conn = get_connection()
    conn.execute("DELETE FROM senders WHERE payment_method = ?", (payment_method,))
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
                             responsible, payment_method, sender_phone, sender_name,
                             sender_warehouse_number, recipient_phone, carrier,
                             carrier_branch, delivery_type,
                             street, building, apartment, recipient_oblast, recipient_city,
                             recipient_address, recipient_name, recipient_type,
                             recipient_edrpou, total_sum, total_weight,
                             client_id, file_name, ttn, ttn_ref, ttn_status, ttn_error,
                             ttn_pdf_path, payer_type, seats_amount, cod_amount, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        header["order_number"], header["order_date"], header["buyer_name"],
        header.get("buyer_address"), header.get("responsible"),
        header.get("payment_method"), header.get("sender_phone"), header.get("sender_name"),
        header.get("sender_warehouse_number"),
        header.get("recipient_phone"), header.get("carrier"),
        header.get("carrier_branch"), header.get("delivery_type"),
        header.get("street"), header.get("building"), header.get("apartment"),
        header.get("recipient_oblast"), header.get("recipient_city"),
        header.get("recipient_address"), header.get("recipient_name"),
        header.get("recipient_type"), header.get("recipient_edrpou"),
        header.get("total_sum"), header.get("total_weight"),
        header.get("client_id"), file_name,
        header.get("ttn"), header.get("ttn_ref"), header.get("ttn_status"), header.get("ttn_error"),
        header.get("ttn_pdf_path"),
        header.get("payer_type"), header.get("seats_amount"), header.get("cod_amount"),
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


# ---------------------------------------------------------------------------
# Відстеження статусу доставки
# ---------------------------------------------------------------------------

def list_active_ttn_orders():
    """Заявки з ТТН, які ще не позначені як доставлені й не скасовані —
    саме їх опитуємо."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM orders
        WHERE ttn IS NOT NULL AND ttn != ''
          AND (tracking_delivered IS NULL OR tracking_delivered = 0)
          AND (ttn_status IS NULL OR ttn_status != 'cancelled')
          AND (order_status IS NULL OR order_status != 'cancelled')
        ORDER BY id DESC
    """)
    result = [dict(row) for row in cur.fetchall()]
    conn.close()
    return result


def update_order_tracking(order_id, status_text, status_raw_json, delivered):
    conn = get_connection()
    conn.execute("""
        UPDATE orders SET tracking_status = ?, tracking_status_raw = ?,
                           tracking_updated_at = ?, tracking_delivered = ?
        WHERE id = ?
    """, (status_text, status_raw_json, datetime.now().isoformat(timespec="seconds"),
          1 if delivered else 0, order_id))
    conn.commit()
    conn.close()


def mark_order_ttn_cancelled(order_id):
    """Позначає ТТН заявки як скасований. Номер ТТН лишається в записі
    для історії — просто більше не відстежується і видно, що його
    скасовано."""
    conn = get_connection()
    conn.execute("""
        UPDATE orders SET ttn_status = 'cancelled',
                           tracking_status = 'ТТН скасовано',
                           tracking_delivered = 1,
                           tracking_updated_at = ?
        WHERE id = ?
    """, (datetime.now().isoformat(timespec="seconds"), order_id))
    conn.commit()
    conn.close()


def cancel_order(order_id):
    """
    Позначає всю заявку як скасовану, не видаляючи фізично. Лишено для
    сумісності зі старими базами (заявки, скасовані до переходу на повне
    видалення) — сама програма більше цю функцію не викликає, натомість
    використовує delete_order (див. нижче).
    """
    conn = get_connection()
    conn.execute("UPDATE orders SET order_status = 'cancelled' WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()


def delete_order(order_id):
    """
    Остаточно видаляє заявку та всі її товарні рядки з бази даних.
    Незворотно — номер заявки після цього більше ніде не фігурує,
    і його безпечно використати повторно.
    """
    conn = get_connection()
    conn.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
    conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()


def get_order(order_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def set_order_ttn_pdf_path(order_id, pdf_path):
    conn = get_connection()
    conn.execute("UPDATE orders SET ttn_pdf_path = ? WHERE id = ?", (pdf_path, order_id))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# База клієнтів — перегляд/експорт
# ---------------------------------------------------------------------------

def list_clients(limit=1000):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM clients ORDER BY full_name LIMIT ?", (limit,))
    result = [dict(row) for row in cur.fetchall()]
    conn.close()
    return result


# ---------------------------------------------------------------------------
# API-ключі перевізників
# ---------------------------------------------------------------------------

def get_carrier_credentials(carrier):
    """Повертає {'api_key': str, 'extra': dict} або None, якщо не налаштовано."""
    import json
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM carrier_credentials WHERE carrier = ?", (carrier,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    extra = {}
    if row["extra"]:
        try:
            extra = json.loads(row["extra"])
        except (ValueError, TypeError):
            extra = {}
    return {"api_key": row["api_key"], "extra": extra}


def set_carrier_credentials(carrier, api_key, extra=None):
    import json
    conn = get_connection()
    conn.execute("""
        INSERT INTO carrier_credentials (carrier, api_key, extra, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(carrier) DO UPDATE SET api_key = excluded.api_key,
                                            extra = excluded.extra,
                                            updated_at = excluded.updated_at
    """, (carrier, api_key, json.dumps(extra or {}, ensure_ascii=False),
          datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    conn.close()


def delete_carrier_credentials(carrier):
    conn = get_connection()
    conn.execute("DELETE FROM carrier_credentials WHERE carrier = ?", (carrier,))
    conn.commit()
    conn.close()


def list_carrier_credentials():
    import json
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM carrier_credentials ORDER BY carrier")
    result = {}
    for row in cur.fetchall():
        extra = {}
        if row["extra"]:
            try:
                extra = json.loads(row["extra"])
            except (ValueError, TypeError):
                extra = {}
        result[row["carrier"]] = {"api_key": row["api_key"], "extra": extra}
    conn.close()
    return result


def get_order_items(order_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM order_items WHERE order_id = ? ORDER BY seq_no", (order_id,))
    result = [dict(row) for row in cur.fetchall()]
    conn.close()
    return result


# ---------------------------------------------------------------------------
# Звітність та аналітика
# ---------------------------------------------------------------------------

def get_orders_in_range(date_from, date_to):
    """date_from/date_to: 'YYYY-MM-DD' (включно)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM orders
        WHERE substr(order_date, 1, 10) BETWEEN ? AND ?
        ORDER BY order_date
    """, (date_from, date_to))
    result = [dict(row) for row in cur.fetchall()]
    conn.close()
    return result


def report_summary(date_from, date_to):
    """Загальні підсумки за період: кількість заявок, сума, вага, середній чек.
    Скасовані заявки не враховуються — вони не є реальними продажами."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) AS orders_count,
               COALESCE(SUM(total_sum), 0) AS total_sum,
               COALESCE(SUM(total_weight), 0) AS total_weight
        FROM orders
        WHERE substr(order_date, 1, 10) BETWEEN ? AND ?
          AND (order_status IS NULL OR order_status != 'cancelled')
    """, (date_from, date_to))
    row = dict(cur.fetchone())
    conn.close()
    row["avg_check"] = (row["total_sum"] / row["orders_count"]) if row["orders_count"] else 0
    return row


def report_by_product(date_from, date_to):
    """Продажі по товарах: сумарна кількість, сума, вага.
    Скасовані заявки не враховуються."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT oi.name AS product_name,
               oi.code AS code,
               SUM(oi.qty) AS total_qty,
               SUM(oi.sum) AS total_sum,
               SUM(oi.weight_total) AS total_weight,
               COUNT(DISTINCT oi.order_id) AS orders_count
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE substr(o.order_date, 1, 10) BETWEEN ? AND ?
          AND (o.order_status IS NULL OR o.order_status != 'cancelled')
        GROUP BY oi.name, oi.code
        ORDER BY total_sum DESC
    """, (date_from, date_to))
    result = [dict(row) for row in cur.fetchall()]
    conn.close()
    return result


def report_by_client(date_from, date_to):
    """Продажі по клієнтах. Скасовані заявки не враховуються."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT buyer_name,
               COUNT(*) AS orders_count,
               SUM(total_sum) AS total_sum,
               SUM(total_weight) AS total_weight
        FROM orders
        WHERE substr(order_date, 1, 10) BETWEEN ? AND ?
          AND (order_status IS NULL OR order_status != 'cancelled')
        GROUP BY buyer_name
        ORDER BY total_sum DESC
    """, (date_from, date_to))
    result = [dict(row) for row in cur.fetchall()]
    conn.close()
    return result


def report_by_geo(date_from, date_to):
    """Продажі по областях/містах одержувачів. Скасовані заявки не враховуються."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT COALESCE(NULLIF(recipient_oblast, ''), 'Не вказано') AS oblast,
               COALESCE(NULLIF(recipient_city, ''), 'Не вказано') AS city,
               COUNT(*) AS orders_count,
               SUM(total_sum) AS total_sum
        FROM orders
        WHERE substr(order_date, 1, 10) BETWEEN ? AND ?
          AND (order_status IS NULL OR order_status != 'cancelled')
        GROUP BY oblast, city
        ORDER BY total_sum DESC
    """, (date_from, date_to))
    result = [dict(row) for row in cur.fetchall()]
    conn.close()
    return result


def report_by_carrier(date_from, date_to):
    """Продажі по перевізниках. Скасовані заявки не враховуються."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT COALESCE(NULLIF(carrier, ''), 'Не вказано') AS carrier,
               COUNT(*) AS orders_count,
               SUM(total_sum) AS total_sum
        FROM orders
        WHERE substr(order_date, 1, 10) BETWEEN ? AND ?
          AND (order_status IS NULL OR order_status != 'cancelled')
        GROUP BY carrier
        ORDER BY total_sum DESC
    """, (date_from, date_to))
    result = [dict(row) for row in cur.fetchall()]
    conn.close()
    return result


def report_timeseries(date_from, date_to):
    """Динаміка продажів по днях (для графіка). Скасовані заявки не враховуються."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT substr(order_date, 1, 10) AS day,
               COUNT(*) AS orders_count,
               SUM(total_sum) AS total_sum
        FROM orders
        WHERE substr(order_date, 1, 10) BETWEEN ? AND ?
          AND (order_status IS NULL OR order_status != 'cancelled')
        GROUP BY day
        ORDER BY day
    """, (date_from, date_to))
    result = [dict(row) for row in cur.fetchall()]
    conn.close()
    return result
