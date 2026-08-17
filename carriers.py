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


def _get_or_create_recipient(api_key, recipient_name, recipient_phone, city_ref,
                              recipient_type="individual", edrpou=None):
    """
    Створює (або повторно використовує, якщо вже існує) одержувача в
    системі Нової Пошти й повертає (ref_контрагента, ref_контактної_особи).
    recipient_type: "individual" (фізична особа) або "legal" (юридична особа).
    """
    if recipient_type == "legal":
        if not edrpou:
            raise CarrierAPIError("Для одержувача-юридичної особи потрібен код ЄДРПОУ.")
        props = {
            "CounterpartyProperty": "Recipient",
            "CounterpartyType": "Organization",
            "EDRPOU": edrpou,
            "CounterpartyName": recipient_name or "Юридична особа",
        }
    else:
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

    if not contact_ref and recipient_type == "legal":
        # для юридичної особи контактну особу треба створити окремим
        # викликом (ContactPerson/save), система не завжди повертає її
        # одразу у відповіді Counterparty/save, як для фізичної особи
        last_name, first_name, middle_name = _split_full_name(recipient_name)
        contact_props = {
            "CounterpartyRef": counterparty_ref,
            "FirstName": first_name,
            "LastName": last_name,
            "MiddleName": middle_name,
            "Phone": recipient_phone,
        }
        contact_data2 = _np_request(api_key, "ContactPerson", "save", contact_props)
        if contact_data2:
            contact_ref = contact_data2[0].get("Ref")

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
    if header.get("recipient_type") == "legal" and not header.get("recipient_edrpou"):
        raise CarrierAPIError("Для одержувача-юридичної особи вкажіть код ЄДРПОУ.")

    sender_city_ref = _get_city_ref(api_key, sender_city_name)
    sender_warehouse_ref = _get_warehouse_ref(api_key, sender_city_ref, sender_warehouse_number)

    recipient_city_ref = _get_city_ref(api_key, header["recipient_city"])
    recipient_warehouse_ref = _get_warehouse_ref(api_key, recipient_city_ref, header["carrier_branch"])

    recipient_counterparty_ref, recipient_contact_ref = _get_or_create_recipient(
        api_key,
        header.get("recipient_name") or header.get("buyer_name"),
        header["recipient_phone"],
        recipient_city_ref,
        recipient_type=header.get("recipient_type") or "individual",
        edrpou=header.get("recipient_edrpou"),
    )

    total_weight = header.get("total_weight") or sum((i.get("weight_total") or 0) for i in items) or 1
    total_sum = header.get("total_sum") or sum((i.get("sum") or 0) for i in items) or 100
    description = ", ".join(i["name"] for i in items)[:100] or "Товар"

    payer_type_np = "Recipient" if header.get("payer_type") == "recipient" else "Sender"
    seats_amount = header.get("seats_amount") or 1

    props = {
        "NewAddress": "1",
        "PayerType": payer_type_np,
        "PaymentMethod": "Cash",
        "CargoType": "Cargo",
        "Weight": str(round(float(total_weight), 2)),
        "ServiceType": "WarehouseWarehouse",
        "SeatsAmount": str(int(seats_amount)),
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

    # -- накладений платіж (готівка, яку перевізник збирає з одержувача
    # при видачі й повертає відправнику) --
    cod_amount = header.get("cod_amount")
    if cod_amount:
        props["BackwardDeliveryData"] = [{
            "PayerType": "Recipient",
            "CargoType": "Money",
            "RedeliveryString": str(round(float(cod_amount), 2)),
        }]

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


def discover_sender_refs(api_key):
    """
    Автоматично знаходить Ref зареєстрованого відправника й Ref його
    контактної особи на акаунті цього API-ключа — без ручного пошуку в
    кабінеті Нової Пошти. Повертає {"sender_ref", "contact_ref", "name"}.
    Кидає CarrierAPIError, якщо на акаунті ще не заведено відправника.
    """
    if not REQUESTS_AVAILABLE:
        raise CarrierAPIError("Модуль мережевих запитів (requests) недоступний у цій збірці.")
    if not api_key:
        raise CarrierAPIError("Спочатку вкажіть API-ключ.")

    senders = _np_request(api_key, "Counterparty", "getCounterparties",
                           {"CounterpartyProperty": "Sender", "Page": "1"})
    if not senders:
        raise CarrierAPIError(
            "На цьому акаунті ще не заведено жодного відправника. Додайте його в "
            "особистому кабінеті my.novaposhta.ua -> Контрагенти -> Додати відправника."
        )
    sender = senders[0]
    sender_ref = sender.get("Ref")
    sender_name = sender.get("Description") or sender.get("CounterpartyName") or ""

    contacts = _np_request(api_key, "Counterparty", "getCounterpartyContactPersons",
                            {"Ref": sender_ref, "Page": "1"})
    if not contacts:
        raise CarrierAPIError(
            f"Знайдено відправника «{sender_name}», але в нього немає жодної "
            f"контактної особи. Додайте її в кабінеті Нової Пошти."
        )
    contact_ref = contacts[0].get("Ref")

    return {"sender_ref": sender_ref, "contact_ref": contact_ref, "name": sender_name}


def _normalize_phone(phone):
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def find_sender_by_phone(api_key, phone):
    """
    Шукає серед відправників, зареєстрованих на акаунті цього API-ключа,
    того, чий телефон збігається з введеним (звіряються тільки цифри,
    формат не важливий). Повертає {"sender_ref", "contact_ref", "name",
    "city"} або None, якщо збігів не знайдено.

    Використовується для полегшення заповнення профілю відправника: після
    введення номера телефону програма намагається підтягнути решту даних
    сама. Публічне API Нової Пошти не має прямого пошуку "за телефоном",
    тому тут перебираються зареєстровані на акаунті відправники (їх
    зазвичай небагато) і звіряється номер їхньої контактної особи.
    """
    if not REQUESTS_AVAILABLE:
        raise CarrierAPIError("Модуль мережевих запитів (requests) недоступний у цій збірці.")
    if not api_key:
        raise CarrierAPIError("Спочатку вкажіть API-ключ.")
    digits = _normalize_phone(phone)
    if not digits:
        return None

    senders = _np_request(api_key, "Counterparty", "getCounterparties",
                           {"CounterpartyProperty": "Sender", "Page": "1"})
    for sender in (senders or [])[:50]:
        sender_ref = sender.get("Ref")
        if not sender_ref:
            continue
        contacts = _np_request(api_key, "Counterparty", "getCounterpartyContactPersons",
                                {"Ref": sender_ref, "Page": "1"})
        for contact in (contacts or []):
            contact_phone = contact.get("Phones") or contact.get("Phone") or ""
            if digits and digits in _normalize_phone(contact_phone):
                return {
                    "sender_ref": sender_ref,
                    "contact_ref": contact.get("Ref"),
                    "name": sender.get("Description") or sender.get("CounterpartyName") or "",
                    "city": (sender.get("City") or {}).get("Description")
                            if isinstance(sender.get("City"), dict) else None,
                }
    return None


def cancel_ttn(carrier, ttn_ref, credentials):
    """
    Скасовує вже створену ТТН (наприклад, створено помилково, або клієнт
    зрештою забрав товар самовивозом). Працює, лише поки відправлення не
    передане перевізнику фізично — якщо посилка вже в дорозі, сервер
    поверне помилку, яка показується користувачу як є.
    """
    if carrier == "Нова Пошта":
        if not REQUESTS_AVAILABLE:
            raise CarrierAPIError("Модуль мережевих запитів (requests) недоступний у цій збірці.")
        return _cancel_ttn_nova_poshta(ttn_ref, credentials)
    raise CarrierAPIError(f"Скасування ТТН для «{carrier}» ще не підключено.")


def _cancel_ttn_nova_poshta(ttn_ref, credentials):
    if not credentials or not credentials.get("api_key"):
        raise CarrierAPIError("Не вказано API-ключ Нової Пошти.")
    if not ttn_ref:
        raise CarrierAPIError(
            "Немає внутрішнього ідентифікатора (Ref) цієї накладної — схоже, "
            "вона була створена до оновлення програми. Скасуйте її вручну на "
            "сайті чи в кабінеті Нової Пошти."
        )
    api_key = credentials["api_key"]
    data = _np_request(api_key, "InternetDocument", "delete", {"DocumentRefs": [ttn_ref]})
    if not data:
        raise CarrierAPIError("Нова Пошта не підтвердила скасування ТТН.")
    return True


PRINT_DOCUMENT_URL = "https://my.novaposhta.ua/orders/printDocument/orders[0]/{ref}/type/pdf/apiKey/{api_key}"


def fetch_ttn_pdf(ttn_ref, api_key):
    """
    Завантажує друковану форму ТТН (бланк-накладну) у форматі PDF з
    Нової Пошти. Повертає байти PDF-файлу. Кидає CarrierAPIError, якщо
    завантажити не вдалось (напр. немає з'єднання чи невірний Ref).
    """
    if not REQUESTS_AVAILABLE:
        raise CarrierAPIError("Модуль мережевих запитів (requests) недоступний у цій збірці.")
    if not ttn_ref:
        raise CarrierAPIError("Немає внутрішнього ідентифікатора (Ref) цієї накладної.")
    if not api_key:
        raise CarrierAPIError("Не вказано API-ключ Нової Пошти.")
    url = PRINT_DOCUMENT_URL.format(ref=ttn_ref, api_key=api_key)
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise CarrierAPIError(f"Не вдалось завантажити бланк ТТН: {e}")
    content_type = resp.headers.get("Content-Type", "")
    if "pdf" not in content_type.lower() and not resp.content.startswith(b"%PDF"):
        raise CarrierAPIError(
            "Нова Пошта повернула не PDF-файл (можливо, невірний Ref або ключ "
            "не має прав на друк цієї накладної)."
        )
    return resp.content


def get_warehouses_for_city(api_key, city_name):
    """
    Повертає список відділень заданого міста: [{"number": "5", "description":
    "Відділення №5: ...", "ref": "..."}] — для автодоповнення номера
    відділення одержувача прямо з довідника Нової Пошти.
    Кидає CarrierAPIError, якщо не вдалось (немає ключа, місто не знайдено).
    """
    if not REQUESTS_AVAILABLE:
        raise CarrierAPIError("Модуль мережевих запитів (requests) недоступний у цій збірці.")
    if not api_key:
        raise CarrierAPIError("Не вказано API-ключ.")
    city_ref = _get_city_ref(api_key, city_name)
    data = _np_request(api_key, "AddressGeneral", "getWarehouses", {"CityRef": city_ref})
    return [
        {"number": str(w.get("Number") or ""), "description": w.get("Description") or "",
         "ref": w.get("Ref")}
        for w in (data or [])
    ]
