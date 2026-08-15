# -*- coding: utf-8 -*-
"""
main.py — головне вікно програми ведення заявок ЧСМ.
Запуск: python3 main.py
"""
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from datetime import datetime, date

import db
import price_import
import order_export 
import ukraine_regions
from autocomplete import AutocompleteEntry

CARRIERS = ["Нова Пошта", "САТ", "Делівері", "Самовивіз"]

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orders")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ЧСМ — Заявки")
        self.geometry("980x720")

        db.init_db()

        self.selected_client = None   # payload з autocomplete покупця
        self.current_items = []       # рядки поточної заявки

        self._build_menu()

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        self.order_tab = ttk.Frame(notebook)
        self.history_tab = ttk.Frame(notebook)
        notebook.add(self.order_tab, text="Нова заявка")
        notebook.add(self.history_tab, text="Історія заявок")

        self._build_order_tab(self.order_tab)
        self._build_history_tab(self.history_tab)
        self._refresh_history()

    # ------------------------------------------------------------------
    # Меню
    # ------------------------------------------------------------------
    def _build_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Завантажити прайс-лист...", command=self._import_price_dialog)
        menubar.add_cascade(label="Файл", menu=file_menu)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Телефони відправника...", command=self._sender_phones_dialog)
        menubar.add_cascade(label="Налаштування", menu=settings_menu)

        self.config(menu=menubar)

    def _import_price_dialog(self):
        path = filedialog.askopenfilename(
            title="Виберіть файл прайс-листа",
            filetypes=[("Excel files", "*.xlsx *.xlsm")]
        )
        if not path:
            return

        eff_date_str = simpledialog.askstring(
            "Дата дії цін",
            "З якої дати діють нові ціни? (ДД.ММ.РРРР, порожньо = сьогодні)"
        )
        if eff_date_str:
            try:
                eff_date = datetime.strptime(eff_date_str.strip(), "%d.%m.%Y").date()
            except ValueError:
                messagebox.showerror("Помилка", "Невірний формат дати. Використайте ДД.ММ.РРРР.")
                return
        else:
            eff_date = date.today()

        rows, warnings = price_import.read_price_list(path)
        if not rows:
            messagebox.showerror("Помилка", "Не вдалось прочитати жодного товару з файлу.\n"
                                  + "\n".join(warnings))
            return

        db.import_price_rows(rows, eff_date.isoformat(), os.path.basename(path))

        msg = f"Імпортовано {len(rows)} позицій. Ціни діють з {eff_date.strftime('%d.%m.%Y')}."
        if warnings:
            msg += "\n\nПопередження:\n" + "\n".join(warnings)
        messagebox.showinfo("Готово", msg)

    def _sender_phones_dialog(self):
        win = tk.Toplevel(self)
        win.title("Телефони відправника за способом оплати")
        win.geometry("420x320")

        tree = ttk.Treeview(win, columns=("phone",), show="tree headings", height=10)
        tree.heading("#0", text="Спосіб оплати")
        tree.heading("phone", text="Телефон")
        tree.pack(fill="both", expand=True, padx=8, pady=8)

        def refresh():
            tree.delete(*tree.get_children())
            for method, phone in db.get_sender_phones().items():
                tree.insert("", "end", text=method, values=(phone,))
        refresh()

        form = tk.Frame(win)
        form.pack(fill="x", padx=8, pady=4)
        tk.Label(form, text="Спосіб оплати:").grid(row=0, column=0, sticky="w")
        method_var = tk.StringVar()
        tk.Entry(form, textvariable=method_var, width=18).grid(row=0, column=1)
        tk.Label(form, text="Телефон:").grid(row=1, column=0, sticky="w")
        phone_var = tk.StringVar()
        tk.Entry(form, textvariable=phone_var, width=18).grid(row=1, column=1)

        def add_or_update():
            if not method_var.get().strip() or not phone_var.get().strip():
                return
            db.set_sender_phone(method_var.get().strip(), phone_var.get().strip())
            method_var.set("")
            phone_var.set("")
            refresh()
            self._reload_payment_methods()

        def delete_selected():
            sel = tree.selection()
            if not sel:
                return
            method = tree.item(sel[0], "text")
            db.delete_sender_phone(method)
            refresh()
            self._reload_payment_methods()

        btns = tk.Frame(win)
        btns.pack(fill="x", padx=8, pady=4)
        tk.Button(btns, text="Додати / оновити", command=add_or_update).pack(side="left")
        tk.Button(btns, text="Видалити вибране", command=delete_selected).pack(side="left", padx=6)

    # ------------------------------------------------------------------
    # Вкладка "Нова заявка"
    # ------------------------------------------------------------------
    def _build_order_tab(self, parent):
        top = tk.Frame(parent)
        top.pack(fill="x", padx=10, pady=8)

        left = tk.Frame(top)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(top)
        right.pack(side="left", fill="both", expand=True, padx=(20, 0))

        r = 0
        tk.Label(left, text="№ заявки:").grid(row=r, column=0, sticky="w", pady=2)
        self.order_number_var = tk.StringVar()
        tk.Entry(left, textvariable=self.order_number_var, width=15).grid(row=r, column=1, sticky="w")
        r += 1

        tk.Label(left, text="Дата створення:").grid(row=r, column=0, sticky="w", pady=2)
        self.order_date_label = tk.Label(left, text=date.today().strftime("%d.%m.%Y"))
        self.order_date_label.grid(row=r, column=1, sticky="w")
        r += 1

        tk.Label(left, text="Покупець:").grid(row=r, column=0, sticky="w", pady=2)
        self.buyer_entry = AutocompleteEntry(
            left, search_fn=self._search_clients_fn, on_select=self._on_client_selected, width=30
        )
        self.buyer_entry.grid(row=r, column=1, sticky="w")
        r += 1

        tk.Label(left, text="Адреса покупця:").grid(row=r, column=0, sticky="w", pady=2)
        self.buyer_address_var = tk.StringVar()
        tk.Entry(left, textvariable=self.buyer_address_var, width=32).grid(row=r, column=1, sticky="w")
        r += 1

        tk.Label(left, text="Відповідальний, ПІБ:").grid(row=r, column=0, sticky="w", pady=2)
        self.responsible_var = tk.StringVar(value="ЧСМ")
        tk.Entry(left, textvariable=self.responsible_var, width=32).grid(row=r, column=1, sticky="w")
        r += 1

        tk.Label(left, text="Спосіб оплати (опл):").grid(row=r, column=0, sticky="w", pady=2)
        self.payment_var = tk.StringVar()
        self.payment_combo = ttk.Combobox(left, textvariable=self.payment_var, width=29,
                                           values=list(db.get_sender_phones().keys()))
        self.payment_combo.grid(row=r, column=1, sticky="w")
        self.payment_combo.bind("<<ComboboxSelected>>", self._on_payment_selected)
        r += 1

        tk.Label(left, text="Телефон відправника:").grid(row=r, column=0, sticky="w", pady=2)
        self.sender_phone_var = tk.StringVar()
        tk.Entry(left, textvariable=self.sender_phone_var, width=32).grid(row=r, column=1, sticky="w")
        r += 1

        # -- права колонка --
        r2 = 0
        tk.Label(right, text="Телефон одержувача:").grid(row=r2, column=0, sticky="w", pady=2)
        self.recipient_phone_var = tk.StringVar()
        tk.Entry(right, textvariable=self.recipient_phone_var, width=32).grid(row=r2, column=1, sticky="w")
        r2 += 1

        tk.Label(right, text="Перевізник:").grid(row=r2, column=0, sticky="w", pady=2)
        self.carrier_var = tk.StringVar(value=CARRIERS[0])
        ttk.Combobox(right, textvariable=self.carrier_var, values=CARRIERS,
                     width=20, state="readonly").grid(row=r2, column=1, sticky="w")
        r2 += 1

        tk.Label(right, text="№ відділення:").grid(row=r2, column=0, sticky="w", pady=2)
        self.carrier_branch_var = tk.StringVar()
        tk.Entry(right, textvariable=self.carrier_branch_var, width=32).grid(row=r2, column=1, sticky="w")
        r2 += 1

        tk.Label(right, text="Область одержувача:").grid(row=r2, column=0, sticky="w", pady=2)
        self.oblast_entry = AutocompleteEntry(
            right, search_fn=self._search_oblasts_fn, on_select=self._on_oblast_selected, width=30
        )
        self.oblast_entry.grid(row=r2, column=1, sticky="w")
        r2 += 1

        tk.Label(right, text="Місто одержувача:").grid(row=r2, column=0, sticky="w", pady=2)
        self.city_entry = AutocompleteEntry(
            right, search_fn=self._search_cities_fn, on_select=lambda l, p: None, width=30
        )
        self.city_entry.grid(row=r2, column=1, sticky="w")
        r2 += 1

        tk.Label(right, text="Одержувач, ПІБ:").grid(row=r2, column=0, sticky="w", pady=2)
        self.recipient_name_var = tk.StringVar()
        tk.Entry(right, textvariable=self.recipient_name_var, width=32).grid(row=r2, column=1, sticky="w")
        r2 += 1

        # -- рядок додавання товару --
        add_frame = tk.LabelFrame(parent, text="Додати товар")
        add_frame.pack(fill="x", padx=10, pady=8)

        tk.Label(add_frame, text="Товар:").grid(row=0, column=0, padx=4, pady=6, sticky="w")
        self.product_entry = AutocompleteEntry(
            add_frame, search_fn=self._search_products_fn, on_select=self._on_product_selected, width=28
        )
        self.product_entry.grid(row=0, column=1, padx=4)

        tk.Label(add_frame, text="Код:").grid(row=0, column=2, padx=4)
        self.item_code_var = tk.StringVar()
        tk.Entry(add_frame, textvariable=self.item_code_var, width=14, state="readonly").grid(row=0, column=3)

        tk.Label(add_frame, text="Ціна:").grid(row=0, column=4, padx=4)
        self.item_price_var = tk.StringVar()
        tk.Entry(add_frame, textvariable=self.item_price_var, width=8, state="readonly").grid(row=0, column=5)

        tk.Label(add_frame, text="Вага/од:").grid(row=0, column=6, padx=4)
        self.item_weight_var = tk.StringVar()
        tk.Entry(add_frame, textvariable=self.item_weight_var, width=8, state="readonly").grid(row=0, column=7)

        tk.Label(add_frame, text="К-сть:").grid(row=0, column=8, padx=4)
        self.item_qty_var = tk.StringVar(value="1")
        tk.Entry(add_frame, textvariable=self.item_qty_var, width=6).grid(row=0, column=9)

        tk.Button(add_frame, text="+", width=3, command=self._add_item).grid(row=0, column=10, padx=6)

        # -- таблиця товарів --
        table_frame = tk.Frame(parent)
        table_frame.pack(fill="both", expand=True, padx=10, pady=4)

        cols = ("code", "name", "unit", "qty", "price", "sum", "weight_unit", "weight_total")
        headers = ["Код", "Найменування", "Од.вим", "К-сть", "Ціна", "Сума", "Вага/од", "Вага всього"]
        self.items_tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=10)
        for c, h in zip(cols, headers):
            self.items_tree.heading(c, text=h)
            self.items_tree.column(c, width=100, anchor="center")
        self.items_tree.column("name", width=200, anchor="w")
        self.items_tree.pack(fill="both", expand=True)

        btn_row = tk.Frame(parent)
        btn_row.pack(fill="x", padx=10)
        tk.Button(btn_row, text="Видалити вибраний рядок", command=self._remove_selected_item).pack(side="left")

        self.totals_label = tk.Label(parent, text="Разом: 0.00 грн,  0.00 кг", font=("", 11, "bold"))
        self.totals_label.pack(anchor="e", padx=10, pady=4)

        tk.Button(parent, text="Сформувати заявку", bg="#2e7d32", fg="white",
                  font=("", 11, "bold"), command=self._generate_order).pack(pady=8)

    def _reload_payment_methods(self):
        self.payment_combo["values"] = list(db.get_sender_phones().keys())

    # -- пошукові функції для автодоповнення --
    def _search_clients_fn(self, text):
        clients = db.search_clients(text)
        return [(c["full_name"], c) for c in clients]

    def _search_oblasts_fn(self, text):
        return [(o, o) for o in ukraine_regions.search_oblasts(text)]

    def _search_cities_fn(self, text):
        oblast = self.oblast_entry.get().strip()
        cities = db.search_cities(oblast, text) if oblast else []
        return [(c, c) for c in cities]

    def _search_products_fn(self, text):
        products = db.search_products(text)
        return [(f"{p['name']} ({p['code']})" if p["code"] else p["name"], p) for p in products]

    # -- обробники вибору --
    def _on_client_selected(self, label, client):
        self.selected_client = client
        self.buyer_address_var.set(client.get("address") or "")
        self.recipient_phone_var.set(client.get("phone") or "")
        self.oblast_entry.set(client.get("oblast") or "")
        self.city_entry.set(client.get("city") or "")
        self.recipient_name_var.set(client.get("full_name") or "")
        if client.get("carrier"):
            self.carrier_var.set(client["carrier"])
        if client.get("carrier_branch"):
            self.carrier_branch_var.set(client["carrier_branch"])

    def _on_payment_selected(self, event=None):
        method = self.payment_var.get()
        phones = db.get_sender_phones()
        if method in phones:
            self.sender_phone_var.set(phones[method])

    def _on_oblast_selected(self, label, payload):
        self.city_entry.set("")

    def _on_product_selected(self, label, product):
        self._selected_product = product
        self.item_code_var.set(product.get("code") or "")
        self.item_price_var.set(str(product.get("price") or ""))
        self.item_weight_var.set(str(product.get("weight") or ""))

    # -- товарні рядки --
    def _add_item(self):
        product = getattr(self, "_selected_product", None)
        if not product:
            messagebox.showwarning("Увага", "Спочатку виберіть товар зі списку.")
            return
        try:
            qty = float(self.item_qty_var.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Помилка", "Некоректна кількість.")
            return
        price = float(product["price"])
        weight_unit = float(product["weight"]) if product.get("weight") else 0.0
        item = {
            "code": product.get("code") or "",
            "name": product["name"],
            "unit": product.get("unit") or "",
            "qty": qty,
            "price": price,
            "sum": round(qty * price, 2),
            "weight_unit": weight_unit,
            "weight_total": round(qty * weight_unit, 2),
        }
        self.current_items.append(item)
        self.items_tree.insert("", "end", values=(
            item["code"], item["name"], item["unit"], item["qty"],
            item["price"], item["sum"], item["weight_unit"], item["weight_total"]
        ))
        self.product_entry.set("")
        self.item_code_var.set("")
        self.item_price_var.set("")
        self.item_weight_var.set("")
        self.item_qty_var.set("1")
        self._selected_product = None
        self._update_totals()

    def _remove_selected_item(self):
        sel = self.items_tree.selection()
        if not sel:
            return
        idx = self.items_tree.index(sel[0])
        self.items_tree.delete(sel[0])
        del self.current_items[idx]
        self._update_totals()

    def _update_totals(self):
        total_sum = sum(i["sum"] for i in self.current_items)
        total_weight = sum(i["weight_total"] for i in self.current_items)
        self.totals_label.config(text=f"Разом: {total_sum:.2f} грн,  {total_weight:.2f} кг")

    # -- формування заявки --
    def _generate_order(self):
        if not self.order_number_var.get().strip():
            messagebox.showwarning("Увага", "Вкажіть номер заявки.")
            return
        if not self.buyer_entry.get().strip():
            messagebox.showwarning("Увага", "Вкажіть покупця.")
            return
        if not self.current_items:
            messagebox.showwarning("Увага", "Додайте хоча б один товар.")
            return

        buyer_name = self.buyer_entry.get().strip()
        oblast = self.oblast_entry.get().strip()
        city = self.city_entry.get().strip()
        recipient_address = ", ".join(p for p in [oblast, city] if p)

        client_id = db.upsert_client(
            full_name=buyer_name,
            phone=self.recipient_phone_var.get().strip() or None,
            oblast=oblast or None,
            city=city or None,
            address=self.buyer_address_var.get().strip() or None,
            carrier=self.carrier_var.get() or None,
            carrier_branch=self.carrier_branch_var.get().strip() or None,
        )
        db.remember_city(oblast, city)

        order_date = date.today()
        header = {
            "order_number": self.order_number_var.get().strip(),
            "order_date": datetime(order_date.year, order_date.month, order_date.day),
            "buyer_name": buyer_name,
            "buyer_address": self.buyer_address_var.get().strip(),
            "responsible": self.responsible_var.get().strip() or "ЧСМ",
            "payment_method": self.payment_var.get().strip(),
            "sender_phone": self.sender_phone_var.get().strip(),
            "recipient_phone": self.recipient_phone_var.get().strip(),
            "carrier": self.carrier_var.get(),
            "carrier_branch": self.carrier_branch_var.get().strip(),
            "recipient_oblast": oblast,
            "recipient_city": city,
            "recipient_address": recipient_address,
            "recipient_name": self.recipient_name_var.get().strip() or buyer_name,
            "total_sum": round(sum(i["sum"] for i in self.current_items), 2),
            "total_weight": round(sum(i["weight_total"] for i in self.current_items), 2),
            "client_id": client_id,
        }

        items_for_export = []
        for i, it in enumerate(self.current_items, start=1):
            row = dict(it)
            row["seq_no"] = i
            items_for_export.append(row)

        filename = order_export.build_filename(buyer_name, order_date, header["order_number"])
        output_path = os.path.join(OUTPUT_DIR, filename)
        order_export.generate_order_excel(header, items_for_export, output_path)

        db.save_order(header, self.current_items, filename)

        messagebox.showinfo("Готово", f"Заявку збережено:\n{output_path}")
        self._reset_order_form()
        self._refresh_history()

    def _reset_order_form(self):
        self.order_number_var.set("")
        self.buyer_entry.set("")
        self.buyer_address_var.set("")
        self.payment_var.set("")
        self.sender_phone_var.set("")
        self.recipient_phone_var.set("")
        self.carrier_branch_var.set("")
        self.oblast_entry.set("")
        self.city_entry.set("")
        self.recipient_name_var.set("")
        self.current_items = []
        self.items_tree.delete(*self.items_tree.get_children())
        self._update_totals()

    # ------------------------------------------------------------------
    # Вкладка "Історія заявок"
    # ------------------------------------------------------------------
    def _build_history_tab(self, parent):
        cols = ("number", "date", "buyer", "sum", "weight", "file")
        headers = ["№", "Дата", "Покупець", "Сума", "Вага", "Файл"]
        self.history_tree = ttk.Treeview(parent, columns=cols, show="headings")
        for c, h in zip(cols, headers):
            self.history_tree.heading(c, text=h)
            self.history_tree.column(c, width=140, anchor="center")
        self.history_tree.column("buyer", width=220, anchor="w")
        self.history_tree.pack(fill="both", expand=True, padx=10, pady=10)

        tk.Button(parent, text="Оновити список", command=self._refresh_history).pack(pady=4)

    def _refresh_history(self):
        self.history_tree.delete(*self.history_tree.get_children())
        for o in db.list_orders():
            self.history_tree.insert("", "end", values=(
                o["order_number"], o["order_date"][:10] if o["order_date"] else "",
                o["buyer_name"], o["total_sum"], o["total_weight"], o["file_name"]
            ))


if __name__ == "__main__":
    app = App()
    app.mainloop()
