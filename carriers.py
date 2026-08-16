# -*- coding: utf-8 -*-
"""
carriers.py — інтеграція з API перевізників для автоматичного створення ТТН.

ВАЖЛИВО ПРО СТАН ЦІЄЇ ІНТЕГРАЦІЇ:
Реалізовано повний робочий виклик офіційного API Нової Пошти (v2.0, JSON) —
за документованим форматом методів Address/getCities, AddressGeneral/getWarehouses,
Counterparty/save, InternetDocument/save. Логіка написана за офіційною
специфікацією, але жодного реального виклику до серверів Нової Пошти в
процесі розробки НЕ виконувалось (немає доступу до зовнішньої мережі й
реального API-ключа) — тому перший реальний запуск варто зробити на
тестовій заявці з невеликою сумою і перевірити результат самостійно.
Якщо Нова Пошта поверне помилку — текст помилки від неї показується
користувачу без змін, це допоможе швидко з'ясувати, чого не вистачає
(зазвичай — Ref контрагента-відправника або невірний номер відділення).

Для САТ і Делівері автоматичне створення ТТН поки що НЕ реалізоване —
у публічному доступі немає перевіреної специфікації їхніх API. Функція
чесно повідомляє про це замість того, щоб імітувати роботу.
"""
import json

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

NOVA_POSHTA_API_URL = "https://api.novaposhta.ua/v2.0/json/"
REQUEST_TIMEOUT = 20


class CarrierAPIError(Exception):
    """Людяно пояснена помilka створення ТТН — показується користувачу як є."""
    pass


def create_ttn(carrier, header, items, credentials):
    """
    Диспетчер створення ТТН за перевізником.

    carrier: назва перевізника ("Нова Пошта", "САТ", "Делівері")
    header: dict заявки (ті самі поля, що йдуть у order_export/db.save_order)
    items: список товарних рядків заявки
    credentials: {"api_key": str, "extra": dict} з db.get_carrier_credentials()

    Повертає dict {"ttn": "20450123456789", "ref": "...", "raw": {...}}
    Кидає CarrierAPIError з поясненням, якщо щось не вдалось.
    """
    if carrier == "Нова Пошта":
        if not REQUESTS_AVAILABLE:
            raise CarrierAPIError(
                "Модуль мережевих запитів (requests) недоступний у цій збірці "
                "програми — автоматичне створення ТТН тимчасово неможливе."
            )
        return _create_ttn_nova_poshta(header, items, credentials)
    if carrier in ("САТ", "Делівері"):
        raise CarrierAPIError(
            f"Автоматичне створення ТТН для «{carrier}» ще не підключено — "
            f"у мене немає перевіреної специфікації їхнього API. Якщо у вас є "
            f"технічна документація API цього перевізника (від служби підтримки "
            f"компанії), надішліть її мені — я дороблю інтеграцію так само, "
            f"як для Нової Пошти."
        )
    if carrier == "Самовивіз":
        raise CarrierAPIError("Самовивіз не потребує ТТН.")
    raise CarrierAPIError(f"Невідомий перевізник: {carrier}")


def _np_request(api_key, model, method, method_properties):
    payload = {
        "apiKey": api_key,
        "modelName": model,
        "calledMethod": method,
        "methodProperties": method_properties,
    }
    try:
        resp = requests.post(NOVA_POSHTA_API_URL, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise CarrierAPIError(f"Немає з'єднання з сервером Нової Пошти: {e}")

    try:
        data = resp.json()
    except ValueError:
        raise CarrierAPIError("Нова Пошта повернула невірну відповідь (не JSON).")

    if not data.get("success"):
        errors = data.get("errors") or []
        warnings = data.get("warnings") or []
        messages = [str(e) for e in errors] + [str(w) for w in warnings]
        if not messages:
            messages = ["Невідома помилка API Нової Пошти (success=false без опису)."]
        raise CarrierAPIError("Нова Пошта: " + "; ".join(messages))

    return data.get("data", [])


def _get_city_ref(api_key, city_name):
    if not city_name:
        raise CarrierAPIError("Не вказано назву міста для пошуку в довіднику Нової Пошти.")
    data = _np_request(api_key, "Address", "getCities", {"FindByString": city_name})
    if not data:
        raise CarrierAPIError(f"Не знайдено місто «{city_name}» у довіднику Нової Пошти.")
    return data[0]["Ref"]


def _get_warehouse_ref(api_key, city_ref, warehouse_number):
    data = _np_request(api_key, "AddressGeneral", "getWarehouses", {"CityRef": city_ref})
    for wh in data:
        if str(wh.get("Number")) == str(warehouse_number).strip():
            return wh["Ref"]
    raise CarrierAPIError(f"Не знайдено відділення №{warehouse_number} у вказаному місті.")


def _split_full_name(full_name):
    parts = (full_name or "").split()
    last_name = parts[0] if len(parts) > 0 else (full_name or "Одержувач")
    first_name = parts[1] if len(parts) > 1 else last_name
    middle_name = parts[2] if len(parts) > 2 else ""
    return last_name, first_name, middle_name


def _get_or_create_recipient(api_key, recipient_name, recipient_phone, city_ref):
    """
    Створює (або повторно використовує, якщо вже існує) одержувача-приватну
    особу в системі Нової Пошти й повертає (ref_контрагента, ref_контактної_особи).
    """
    last_name, first_name, middle_name = _split_full_name(recipient_name)
    props = {
        "FirstName": first_name,
        "LastName": last_name,
        "MiddleName": middle_name,
        "Phone": recipient_phone,
        "CounterpartyType": "PrivatePerson",
        "CounterpartyProperty": "Recipient",
    }
    data = _np_request(api_key, "Counterparty", "save", props)
    if not data:
        raise CarrierAPIError("Не вдалось створити/знайти одержувача в системі Нової Пошти.")
    counterparty_ref = data[0]["Ref"]
    contact_ref = None
    contact_data = (data[0].get("ContactPerson") or {}).get("data") or []
    if contact_data:
        contact_ref = contact_data[0].get("Ref")
    if not contact_ref:
        raise CarrierAPIError("Нова Пошта не повернула контактну особу одержувача.")
    return counterparty_ref, contact_ref


def _create_ttn_nova_poshta(header, items, credentials):
    if not credentials or not credentials.get("api_key"):
        raise CarrierAPIError(
            "Не вказано API-ключ Нової Пошти "
            "(Налаштування → API-ключі перевізників → Нова Пошта)."
        )
    api_key = credentials["api_key"]
    extra = credentials.get("extra") or {}

    sender_city_name = extra.get("sender_city")
    sender_warehouse_number = extra.get("sender_warehouse")
    sender_counterparty_ref = extra.get("sender_counterparty_ref")
    sender_contact_ref = extra.get("sender_contact_ref")
    sender_phone = extra.get("sender_phone") or header.get("sender_phone") or ""

    missing = []
    if not sender_city_name:
        missing.append("місто відправника")
    if not sender_warehouse_number:
        missing.append("№ відділення відправника")
    if not sender_counterparty_ref:
        missing.append("Ref контрагента-відправника")
    if not sender_contact_ref:
        missing.append("Ref контактної особи відправника")
    if missing:
        raise CarrierAPIError(
            "У налаштуваннях Нової Пошти не вистачає: " + ", ".join(missing) +
            " (Налаштування → API-ключі перевізників → Нова Пошта)."
        )

    if header.get("delivery_type") != "branch" or not header.get("carrier_branch"):
        raise CarrierAPIError(
            "Автоматичне створення ТТН підтримується поки що лише для доставки "
            "«На відділення» (з номером відділення одержувача)."
        )
    if not header.get("recipient_city"):
        raise CarrierAPIError("Не вказано місто одержувача.")
    if not header.get("recipient_phone"):
        raise CarrierAPIError("Не вказано телефон одержувача.")

    sender_city_ref = _get_city_ref(api_key, sender_city_name)
    sender_warehouse_ref = _get_warehouse_ref(api_key, sender_city_ref, sender_warehouse_number)

    recipient_city_ref = _get_city_ref(api_key, header["recipient_city"])
    recipient_warehouse_ref = _get_warehouse_ref(api_key, recipient_city_ref, header["carrier_branch"])

    recipient_counterparty_ref, recipient_contact_ref = _get_or_create_recipient(
        api_key,
        header.get("recipient_name") or header.get("buyer_name"),
        header["recipient_phone"],
        recipient_city_ref,
    )

    total_weight = header.get("total_weight") or sum((i.get("weight_total") or 0) for i in items) or 1
    total_sum = header.get("total_sum") or sum((i.get("sum") or 0) for i in items) or 100
    description = ", ".join(i["name"] for i in items)[:100] or "Товар"

    props = {
        "NewAddress": "1",
        "PayerType": "Sender",
        "PaymentMethod": "Cash",
        "CargoType": "Cargo",
        "Weight": str(round(float(total_weight), 2)),
        "ServiceType": "WarehouseWarehouse",
        "SeatsAmount": "1",
        "Description": description,
        "Cost": str(round(float(total_sum), 2)),
        "CitySender": sender_city_ref,
        "Sender": sender_counterparty_ref,
        "SenderAddress": sender_warehouse_ref,
        "ContactSender": sender_contact_ref,
        "SendersPhone": sender_phone,
        "CityRecipient": recipient_city_ref,
        "Recipient": recipient_counterparty_ref,
        "RecipientAddress": recipient_warehouse_ref,
        "ContactRecipient": recipient_contact_ref,
        "RecipientsPhone": header["recipient_phone"],
    }

    data = _np_request(api_key, "InternetDocument", "save", props)
    if not data:
        raise CarrierAPIError("Нова Пошта не повернула номер ТТН.")
    ttn_number = data[0].get("IntDocNumber")
    if not ttn_number:
        raise CarrierAPIError("Нова Пошта не повернула номер ТТН у відповіді (перевірте дані заявки).")

    return {"ttn": ttn_number, "ref": data[0].get("Ref"), "raw": data[0]}


# ---------------------------------------------------------------------------
# Відстеження статусу доставки
# ---------------------------------------------------------------------------

# Ключові слова в тексті статусу Нової Пошти, які означають "посилку отримано".
# Офіційні StatusCode Нової Пошти в різних джерелах документовані по-різному
# й можуть відрізнятись для різних типів відправлень, тому для надійності
# орієнтуємось на текст самого статусу (Status), а не лише на код.
_DELIVERED_KEYWORDS = ["отримано", "видано"]


def track_status(carrier, ttn, credentials, recipient_phone=None):
    """
    Повертає {"status": "текст статусу", "delivered": bool, "raw": {...}}
    Кидає CarrierAPIError, якщо перевірка не вдалась.
    """
    if carrier == "Нова Пошта":
        if not REQUESTS_AVAILABLE:
            raise CarrierAPIError("Модуль мережевих запитів (requests) недоступний у цій збірці.")
        return _track_status_nova_poshta(ttn, credentials, recipient_phone)
    raise CarrierAPIError(f"Відстеження для «{carrier}» ще не підключено.")


def _track_status_nova_poshta(ttn, credentials, recipient_phone=None):
    if not credentials or not credentials.get("api_key"):
        raise CarrierAPIError("Не вказано API-ключ Нової Пошти.")
    api_key = credentials["api_key"]

    document = {"DocumentNumber": ttn}
    if recipient_phone:
        document["Phone"] = recipient_phone

    data = _np_request(api_key, "TrackingDocument", "getStatusDocuments",
                        {"Documents": [document]})
    if not data:
        raise CarrierAPIError(f"Нова Пошта не повернула дані по ТТН {ttn}.")

    info = data[0]
    status_text = info.get("Status") or "Статус невідомий"
    delivered = any(kw in status_text.lower() for kw in _DELIVERED_KEYWORDS)
    return {"status": status_text, "delivered": delivered, "raw": info}
