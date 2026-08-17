# -*- coding: utf-8 -*-
"""
np_diagnostic.py — окремий діагностичний скрипт (не частина самої програми
Ordex), який перевіряє, чи достатньо даних для автоматичного створення ТТН
через API Нової Пошти — БЕЗ реального створення накладної (щоб не витратити
гроші чи не створити зайве відправлення).

Запуск:
    python3 np_diagnostic.py

Він запитає ваш API-ключ, місто/відділення відправника — і крок за кроком
перевірить кожен елемент, потрібний для InternetDocument/save:
  1. Чи взагалі приймає сервер цей API-ключ
  2. Чи є у вас зареєстрований відправник (Counterparty з типом Sender)
     і чи можна автоматично дізнатись його Ref та Ref контактної особи
     (без ручного пошуку в кабінеті!)
  3. Чи знаходиться вказане місто відправника
  4. Чи знаходиться вказане відділення відправника в цьому місті

Наприкінці скрипт покаже готові значення, які можна скопіювати прямо в
Ordex -> Налаштування -> Відправники.

Встановлення (якщо ще не стоїть): pip install requests
"""
import sys

try:
    import requests
except ImportError:
    print("Не встановлено бібліотеку requests. Виконайте: pip install requests")
    sys.exit(1)

API_URL = "https://api.novaposhta.ua/v2.0/json/"


def call(api_key, model, method, props):
    payload = {"apiKey": api_key, "modelName": model, "calledMethod": method,
               "methodProperties": props}
    try:
        resp = requests.post(API_URL, json=payload, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        return None, f"Немає з'єднання з сервером Нової Пошти: {e}"
    try:
        data = resp.json()
    except ValueError:
        return None, "Сервер повернув не-JSON відповідь."
    if not data.get("success"):
        msgs = (data.get("errors") or []) + (data.get("warnings") or [])
        return None, "; ".join(str(m) for m in msgs) or "Невідома помилка (success=false)."
    return data.get("data", []), None


def main():
    print("=" * 70)
    print("Діагностика підключення до API Нової Пошти для Ordex")
    print("=" * 70)
    api_key = input("Вставте ваш API-ключ Нової Пошти: ").strip()
    if not api_key:
        print("Ключ не введено, зупиняюсь.")
        return

    print("\n[1/4] Перевіряю API-ключ (запит списку міст 'Київ')...")
    data, err = call(api_key, "Address", "getCities", {"FindByString": "Київ"})
    if err:
        print(f"   ПОМИЛКА: {err}")
        print("   -> Ключ, найімовірніше, невірний або не активований. Зупиняюсь.")
        return
    print(f"   OK — ключ приймається сервером ({len(data)} збігів на 'Київ').")

    print("\n[2/4] Шукаю зареєстрованого відправника (Counterparty, тип Sender)...")
    senders, err = call(api_key, "Counterparty", "getCounterparties",
                         {"CounterpartyProperty": "Sender", "Page": "1"})
    if err:
        print(f"   ПОМИЛКА: {err}")
        senders = []
    if not senders:
        print("   Не знайдено жодного зареєстрованого відправника на цьому акаунті.")
        print("   -> Потрібно завести відправника в особистому кабінеті")
        print("      my.novaposhta.ua -> Контрагенти -> Додати відправника,")
        print("      або звернутись у підтримку Нової Пошти для вашого бізнес-акаунту.")
        sender_ref = None
        contact_ref = None
    else:
        s = senders[0]
        sender_ref = s.get("Ref")
        sender_name = s.get("Description") or s.get("CounterpartyName") or "(без назви)"
        print(f"   Знайдено: {sender_name}")
        print(f"   Ref контрагента-відправника: {sender_ref}")
        if len(senders) > 1:
            print(f"   (Усього знайдено {len(senders)} відправників на акаунті — "
                  f"взято перший; якщо потрібен інший, скажіть — допоможу вибрати.)")

        print("\n   Шукаю контактну особу цього відправника...")
        contacts, err2 = call(api_key, "ContactPerson", "getCounterpartyContactPersons",
                               {"Ref": sender_ref, "Page": "1"})
        if err2 or not contacts:
            print(f"   ПОМИЛКА або немає контактних осіб: {err2 or 'порожній список'}")
            contact_ref = None
        else:
            contact_ref = contacts[0].get("Ref")
            contact_name = contacts[0].get("Description") or "(без імені)"
            print(f"   Знайдено контактну особу: {contact_name}")
            print(f"   Ref контактної особи: {contact_ref}")

    print("\n[3/4] Перевіряю місто відправника...")
    sender_city = input("   Введіть назву міста відправника (напр. Київ): ").strip()
    city_data, err = call(api_key, "Address", "getCities", {"FindByString": sender_city})
    if err or not city_data:
        print(f"   ПОМИЛКА: {err or 'місто не знайдено'}")
        city_ref = None
    else:
        city_ref = city_data[0]["Ref"]
        print(f"   OK — знайдено місто «{city_data[0].get('Description')}», Ref: {city_ref}")

    warehouse_ref = None
    if city_ref:
        print("\n[4/4] Перевіряю відділення відправника...")
        warehouse_num = input("   Введіть номер відділення відправника (напр. 5): ").strip()
        wh_data, err = call(api_key, "AddressGeneral", "getWarehouses", {"CityRef": city_ref})
        if err:
            print(f"   ПОМИЛКА: {err}")
        else:
            match = next((w for w in wh_data if str(w.get("Number")) == warehouse_num), None)
            if match:
                warehouse_ref = match["Ref"]
                print(f"   OK — знайдено відділення №{warehouse_num}, Ref: {warehouse_ref}")
            else:
                print(f"   Відділення №{warehouse_num} не знайдено серед "
                      f"{len(wh_data)} відділень цього міста. Перевірте номер.")
    else:
        print("\n[4/4] Пропускаю (місто не знайдено на попередньому кроці).")

    print("\n" + "=" * 70)
    print("ПІДСУМОК")
    print("=" * 70)
    all_ok = all([sender_ref, contact_ref, city_ref, warehouse_ref])
    if all_ok:
        print("Усіх даних достатньо для автоматичного створення ТТН.")
        print("\nВнесіть ці значення в Ordex -> Налаштування -> Відправники:")
        print(f"  Місто відправника:              {sender_city}")
        print(f"  № відділення відправника:       {warehouse_num}")
        print(f"  Ref контрагента-відправника:     {sender_ref}")
        print(f"  Ref контактної особи відправника: {contact_ref}")
        print(f"  API-ключ:                        {api_key}")
    else:
        print("Чогось не вистачає — див. позначки ПОМИЛКА вище. Найчастіші причини:")
        print("  - на акаунті ще не заведено відправника (крок 2)")
        print("  - невірно вказане місто/відділення (кроки 3-4)")
        print("  - ключ має обмежені права доступу (зверніться в підтримку НП)")


if __name__ == "__main__":
    main()
