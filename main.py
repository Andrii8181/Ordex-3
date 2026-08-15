# -*- coding: utf-8 -*-
"""
main.py — головне вікно програми ведення заявок ЧСМ.
Запуск: python3 main.py
"""
import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from datetime import datetime, date, timedelta

import db
import price_import
import order_export
import reports
import ukraine_regions
from autocomplete import AutocompleteEntry

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


def resource_path(*parts):
    """
    Повертає абсолютний шлях до файлу ресурсу (наприклад, іконки),
    коректно як при звичайному запуску python main.py, так і всередині
    зібраного PyInstaller-ом .exe (--onefile розпаковує дані у тимчасову
    папку, шлях до якої лежить у sys._MEIPASS).
    """
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, *parts)

CARRIERS = ["Нова Пошта", "САТ", "Делівері", "Самовивіз"]
DELIVERY_TYPES = [("branch", "На відділення"), ("address", "Адресна доставка")]

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orders")

# -- Єдиний шрифт для всієї програми: чіткий, без розмиття --
FONT = ("Segoe UI", 11)
FONT_BOLD = ("Segoe UI", 11, "bold")
FONT_SMALL = ("Segoe UI", 10)
FONT_TITLE = ("Segoe UI", 14, "bold")

SIDEBAR_ITEMS = [
    ("order", "Нова заявка"),
    ("history", "Історія заявок"),
    ("report_summary", "Звіт: Зведення"),
    ("report_products", "Звіт: Товари"),
    ("report_clients", "Звіт: Клієнти"),
    ("report_geo", "Звіт: Географія"),
    ("report_carriers", "Звіт: Перевізники"),
    ("report_dynamics", "Звіт: Динаміка"),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Ordex — платформа для замовлень та звітів")
        self.geometry("1180x760")
        self._set_app_icon()

        # -- глобальний шрифт --
        self.option_add("*Font", FONT)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=FONT)
        style.configure("Treeview", font=FONT, rowheight=26)
        style.configure("Treeview.Heading", font=FONT_BOLD)
        style.configure("TCombobox", font=FONT)
        style.configure("TNotebook.Tab", font=FONT)

        db.init_db()

        self.selected_client = None
        self.current_items = []
        self._selected_product = None

        self._build_menu()

        # -- бокове меню + область контенту --
        container = tk.Frame(self)
        container.pack(fill="both", expand=True)

        sidebar = tk.Frame(container, bg="#263238", width=210)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="Ordex", bg="#263238", fg="white",
                 font=("Segoe UI", 16, "bold")).pack(pady=(18, 6))
        tk.Label(sidebar, text="Заявки та звіти", bg="#263238", fg="#B0BEC5",
                 font=FONT_SMALL).pack(pady=(0, 16))

        self.sidebar_buttons = {}
        for key, label in SIDEBAR_ITEMS:
            btn = tk.Button(sidebar, text=label, anchor="w", relief="flat",
                             bg="#263238", fg="white", activebackground="#37474F",
                             activeforeground="white", font=FONT, bd=0,
                             padx=16, pady=10, command=lambda k=key: self._show_view(k))
            btn.pack(fill="x")
            self.sidebar_buttons[key] = btn

        self.content = tk.Frame(container)
        self.content.pack(side="left", fill="both", expand=True)

        self.views = {}
        self._build_order_view()
        self._build_history_view()
        for key in ("report_summary", "report_products", "report_clients",
                    "report_geo", "report_carriers", "report_dynamics"):
            self._build_report_view(key)

        self._show_view("order")

    def _set_app_icon(self):
        """Встановлює значок вікна/панелі завдань: .ico для Windows, .png як резерв."""
        ico_path = resource_path("assets", "ordex_icon.ico")
        png_path = resource_path("assets", "ordex_icon_256.png")
        try:
            if os.path.exists(ico_path):
                self.iconbitmap(ico_path)
        except tk.TclError:
            pass
        try:
            if os.path.exists(png_path):
                icon_img = tk.PhotoImage(file=png_path)
                self.iconphoto(True, icon_img)
                self._icon_ref = icon_img  # тримаємо посилання, щоб картинку не прибрав збирач сміття
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Навігація
    # ------------------------------------------------------------------
    def _show_view(self, key):
        for frame in self.views.values():
            frame.pack_forget()
        self.views[key].pack(fill="both", expand=True)
        for k, btn in self.sidebar_buttons.items():
            btn.configure(bg="#37474F" if k == key else "#263238")
        if key == "history":
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
        win.geometry("440x340")

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
        tk.Entry(form, textvariable=method_var, width=20, font=FONT).grid(row=0, column=1)
        tk.Label(form, text="Телефон:").grid(row=1, column=0, sticky="w")
        phone_var = tk.StringVar()
        tk.Entry(form, textvariable=phone_var, width=20, font=FONT).grid(row=1, column=1)

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
        tk.Button(btns, text="Додати / оновити", font=FONT, command=add_or_update).pack(side="left")
        tk.Button(btns, text="Видалити вибране", font=FONT, command=delete_selected).pack(side="left", padx=6)

    # ------------------------------------------------------------------
    # "Нова заявка"
    # ------------------------------------------------------------------
    def _build_order_view(self):
        parent = tk.Frame(self.content)
        self.views["order"] = parent

        canvas_wrap = tk.Frame(parent)
        canvas_wrap.pack(fill="both", expand=True)

        top = tk.Frame(canvas_wrap)
        top.pack(fill="x", padx=14, pady=10)

        left = tk.Frame(top)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(top)
        right.pack(side="left", fill="both", expand=True, padx=(24, 0))

        r = 0
        tk.Label(left, text="№ заявки:", font=FONT).grid(row=r, column=0, sticky="w", pady=3)
        self.order_number_var = tk.StringVar()
        tk.Entry(left, textvariable=self.order_number_var, width=16, font=FONT).grid(row=r, column=1, sticky="w")
        r += 1

        tk.Label(left, text="Дата створення:", font=FONT).grid(row=r, column=0, sticky="w", pady=3)
        tk.Label(left, text=date.today().strftime("%d.%m.%Y"), font=FONT).grid(row=r, column=1, sticky="w")
        r += 1

        tk.Label(left, text="Покупець:", font=FONT).grid(row=r, column=0, sticky="w", pady=3)
        self.buyer_entry = AutocompleteEntry(
            left, search_fn=self._search_clients_fn, on_select=self._on_client_selected,
            width=30, font=FONT
        )
        self.buyer_entry.grid(row=r, column=1, sticky="w")
        r += 1

        tk.Label(left, text="Адреса покупця:", font=FONT).grid(row=r, column=0, sticky="w", pady=3)
        self.buyer_address_var = tk.StringVar()
        tk.Entry(left, textvariable=self.buyer_address_var, width=32, font=FONT).grid(row=r, column=1, sticky="w")
        r += 1

        tk.Label(left, text="Відповідальний, ПІБ:", font=FONT).grid(row=r, column=0, sticky="w", pady=3)
        self.responsible_var = tk.StringVar(value="ЧСМ")
        tk.Entry(left, textvariable=self.responsible_var, width=32, font=FONT).grid(row=r, column=1, sticky="w")
        r += 1

        tk.Label(left, text="Спосіб оплати (опл):", font=FONT).grid(row=r, column=0, sticky="w", pady=3)
        self.payment_var = tk.StringVar()
        self.payment_combo = ttk.Combobox(left, textvariable=self.payment_var, width=28, font=FONT,
                                           values=list(db.get_sender_phones().keys()))
        self.payment_combo.grid(row=r, column=1, sticky="w")
        self.payment_combo.bind("<<ComboboxSelected>>", self._on_payment_selected)
        r += 1

        tk.Label(left, text="Телефон відправника:", font=FONT).grid(row=r, column=0, sticky="w", pady=3)
        self.sender_phone_var = tk.StringVar()
        tk.Entry(left, textvariable=self.sender_phone_var, width=32, font=FONT).grid(row=r, column=1, sticky="w")
        r += 1

        # -- права колонка --
        r2 = 0
        tk.Label(right, text="Телефон одержувача:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        self.recipient_phone_var = tk.StringVar()
        tk.Entry(right, textvariable=self.recipient_phone_var, width=32, font=FONT).grid(row=r2, column=1, sticky="w")
        r2 += 1

        tk.Label(right, text="Перевізник:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        self.carrier_var = tk.StringVar(value=CARRIERS[0])
        carrier_combo = ttk.Combobox(right, textvariable=self.carrier_var, values=CARRIERS,
                                      width=25, font=FONT, state="readonly")
        carrier_combo.grid(row=r2, column=1, sticky="w")
        carrier_combo.bind("<<ComboboxSelected>>", self._on_carrier_changed)
        r2 += 1

        tk.Label(right, text="Тип доставки:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        self.delivery_type_var = tk.StringVar(value="branch")
        dtype_frame = tk.Frame(right)
        dtype_frame.grid(row=r2, column=1, sticky="w")
        self.delivery_radios = []
        for val, label in DELIVERY_TYPES:
            rb = tk.Radiobutton(dtype_frame, text=label, variable=self.delivery_type_var,
                                 value=val, font=FONT, command=self._on_delivery_type_changed)
            rb.pack(side="left", padx=(0, 8))
            self.delivery_radios.append(rb)
        r2 += 1

        tk.Label(right, text="№ відділення:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        self.carrier_branch_var = tk.StringVar()
        self.carrier_branch_entry = tk.Entry(right, textvariable=self.carrier_branch_var, width=32, font=FONT)
        self.carrier_branch_entry.grid(row=r2, column=1, sticky="w")
        r2 += 1

        tk.Label(right, text="Вулиця:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        self.street_var = tk.StringVar()
        self.street_entry = tk.Entry(right, textvariable=self.street_var, width=32, font=FONT)
        self.street_entry.grid(row=r2, column=1, sticky="w")
        r2 += 1

        tk.Label(right, text="Будинок / квартира:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        bld_frame = tk.Frame(right)
        bld_frame.grid(row=r2, column=1, sticky="w")
        self.building_var = tk.StringVar()
        self.apartment_var = tk.StringVar()
        self.building_entry = tk.Entry(bld_frame, textvariable=self.building_var, width=13, font=FONT)
        self.building_entry.pack(side="left")
        self.apartment_entry = tk.Entry(bld_frame, textvariable=self.apartment_var, width=13, font=FONT)
        self.apartment_entry.pack(side="left", padx=(6, 0))
        r2 += 1

        tk.Label(right, text="Область одержувача:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        self.oblast_entry = AutocompleteEntry(
            right, search_fn=self._search_oblasts_fn, on_select=self._on_oblast_selected,
            width=30, font=FONT
        )
        self.oblast_entry.grid(row=r2, column=1, sticky="w")
        r2 += 1

        tk.Label(right, text="Місто одержувача:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        self.city_entry = AutocompleteEntry(
            right, search_fn=self._search_cities_fn, on_select=lambda l, p: None,
            width=30, font=FONT
        )
        self.city_entry.grid(row=r2, column=1, sticky="w")
        r2 += 1

        tk.Label(right, text="Одержувач, ПІБ:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        self.recipient_name_var = tk.StringVar()
        tk.Entry(right, textvariable=self.recipient_name_var, width=32, font=FONT).grid(row=r2, column=1, sticky="w")
        r2 += 1

        self._apply_delivery_state()

        # -- рядок додавання товару --
        add_frame = tk.LabelFrame(canvas_wrap, text="Додати товар", font=FONT)
        add_frame.pack(fill="x", padx=14, pady=8)

        tk.Label(add_frame, text="Товар:", font=FONT).grid(row=0, column=0, padx=4, pady=8, sticky="w")
        self.product_entry = AutocompleteEntry(
            add_frame, search_fn=self._search_products_fn, on_select=self._on_product_selected,
            width=26, font=FONT
        )
        self.product_entry.grid(row=0, column=1, padx=4)

        tk.Label(add_frame, text="Код:", font=FONT).grid(row=0, column=2, padx=4)
        self.item_code_var = tk.StringVar()
        tk.Entry(add_frame, textvariable=self.item_code_var, width=13, font=FONT, state="readonly").grid(row=0, column=3)

        tk.Label(add_frame, text="Ціна:", font=FONT).grid(row=0, column=4, padx=4)
        self.item_price_var = tk.StringVar()
        tk.Entry(add_frame, textvariable=self.item_price_var, width=8, font=FONT, state="readonly").grid(row=0, column=5)

        tk.Label(add_frame, text="Вага/од:", font=FONT).grid(row=0, column=6, padx=4)
        self.item_weight_var = tk.StringVar()
        tk.Entry(add_frame, textvariable=self.item_weight_var, width=8, font=FONT, state="readonly").grid(row=0, column=7)

        tk.Label(add_frame, text="К-сть:", font=FONT).grid(row=0, column=8, padx=4)
        self.item_qty_var = tk.StringVar(value="1")
        tk.Entry(add_frame, textvariable=self.item_qty_var, width=6, font=FONT).grid(row=0, column=9)

        tk.Button(add_frame, text="+", width=3, font=FONT_BOLD, command=self._add_item).grid(row=0, column=10, padx=8)

        # -- таблиця товарів --
        table_frame = tk.Frame(canvas_wrap)
        table_frame.pack(fill="both", expand=True, padx=14, pady=4)

        cols = ("code", "name", "unit", "qty", "price", "sum", "weight_unit", "weight_total")
        headers = ["Код", "Найменування", "Од.вим", "К-сть", "Ціна", "Сума", "Вага/од", "Вага всього"]
        self.items_tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=8)
        for c, h in zip(cols, headers):
            self.items_tree.heading(c, text=h)
            self.items_tree.column(c, width=100, anchor="center")
        self.items_tree.column("name", width=200, anchor="w")
        self.items_tree.pack(fill="both", expand=True)

        btn_row = tk.Frame(canvas_wrap)
        btn_row.pack(fill="x", padx=14)
        tk.Button(btn_row, text="Видалити вибраний рядок", font=FONT,
                  command=self._remove_selected_item).pack(side="left")

        self.totals_label = tk.Label(canvas_wrap, text="Разом: 0.00 грн,  0.00 кг", font=FONT_BOLD)
        self.totals_label.pack(anchor="e", padx=14, pady=4)

        tk.Button(canvas_wrap, text="Сформувати заявку", bg="#2e7d32", fg="white",
                  font=FONT_BOLD, command=self._generate_order).pack(pady=8)

    def _reload_payment_methods(self):
        self.payment_combo["values"] = list(db.get_sender_phones().keys())

    # -- логіка перевізник / тип доставки --
    def _apply_delivery_state(self):
        carrier = self.carrier_var.get()
        is_pickup = (carrier == "Самовивіз")

        for rb in self.delivery_radios:
            rb.configure(state="disabled" if is_pickup else "normal")

        if is_pickup:
            self.carrier_branch_var.set("")
            self.street_var.set("")
            self.building_var.set("")
            self.apartment_var.set("")
            self.carrier_branch_entry.configure(state="disabled")
            self.street_entry.configure(state="disabled")
            self.building_entry.configure(state="disabled")
            self.apartment_entry.configure(state="disabled")
            return

        delivery_type = self.delivery_type_var.get()
        if delivery_type == "branch":
            self.carrier_branch_entry.configure(state="normal")
            self.street_entry.configure(state="disabled")
            self.building_entry.configure(state="disabled")
            self.apartment_entry.configure(state="disabled")
            self.street_var.set("")
            self.building_var.set("")
            self.apartment_var.set("")
        else:
            self.carrier_branch_entry.configure(state="disabled")
            self.carrier_branch_var.set("")
            self.street_entry.configure(state="normal")
            self.building_entry.configure(state="normal")
            self.apartment_entry.configure(state="normal")

    def _on_carrier_changed(self, event=None):
        self._apply_delivery_state()

    def _on_delivery_type_changed(self):
        self._apply_delivery_state()

    # -- пошукові функції для автодоповнення --
    def _search_clients_fn(self, text):
        clients = db.search_clients(text)
        return [(c["full_name"], c) for c in clients]

    def _search_oblasts_fn(self, text):
        return [(o, o) for o in ukraine_regions.search_oblasts(text)]

    def _search_cities_fn(self, text):
        oblast = self.oblast_entry.get().strip()
        if not oblast:
            return []
        static_cities = ukraine_regions.search_cities_static(oblast, text)
        learned_cities = db.search_cities(oblast, text)
        merged = list(dict.fromkeys(static_cities + learned_cities))
        return [(c, c) for c in merged]

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
        if client.get("delivery_type"):
            self.delivery_type_var.set(client["delivery_type"])
        self.street_var.set(client.get("street") or "")
        self.building_var.set(client.get("building") or "")
        self.apartment_var.set(client.get("apartment") or "")
        self._apply_delivery_state()

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
        product = self._selected_product
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
        carrier = self.carrier_var.get()
        delivery_type = self.delivery_type_var.get() if carrier != "Самовивіз" else ""

        address_parts = [p for p in [oblast, city] if p]
        if delivery_type == "address":
            street_part = self.street_var.get().strip()
            building_part = self.building_var.get().strip()
            apartment_part = self.apartment_var.get().strip()
            if street_part:
                addr_line = f"вул. {street_part}"
                if building_part:
                    addr_line += f", буд. {building_part}"
                if apartment_part:
                    addr_line += f", кв. {apartment_part}"
                address_parts.append(addr_line)
        recipient_address = ", ".join(address_parts)

        client_id = db.upsert_client(
            full_name=buyer_name,
            phone=self.recipient_phone_var.get().strip() or None,
            oblast=oblast or None,
            city=city or None,
            address=self.buyer_address_var.get().strip() or None,
            carrier=carrier or None,
            carrier_branch=self.carrier_branch_var.get().strip() or None,
            delivery_type=delivery_type or None,
            street=self.street_var.get().strip() or None,
            building=self.building_var.get().strip() or None,
            apartment=self.apartment_var.get().strip() or None,
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
            "carrier": carrier,
            "carrier_branch": self.carrier_branch_var.get().strip() if delivery_type == "branch" else "",
            "delivery_type": delivery_type,
            "street": self.street_var.get().strip(),
            "building": self.building_var.get().strip(),
            "apartment": self.apartment_var.get().strip(),
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

    def _reset_order_form(self):
        self.order_number_var.set("")
        self.buyer_entry.set("")
        self.buyer_address_var.set("")
        self.payment_var.set("")
        self.sender_phone_var.set("")
        self.recipient_phone_var.set("")
        self.carrier_var.set(CARRIERS[0])
        self.delivery_type_var.set("branch")
        self.carrier_branch_var.set("")
        self.street_var.set("")
        self.building_var.set("")
        self.apartment_var.set("")
        self.oblast_entry.set("")
        self.city_entry.set("")
        self.recipient_name_var.set("")
        self.current_items = []
        self.items_tree.delete(*self.items_tree.get_children())
        self._update_totals()
        self._apply_delivery_state()

    # ------------------------------------------------------------------
    # "Історія заявок"
    # ------------------------------------------------------------------
    def _build_history_view(self):
        parent = tk.Frame(self.content)
        self.views["history"] = parent

        tk.Label(parent, text="Історія заявок", font=FONT_TITLE).pack(anchor="w", padx=14, pady=(14, 6))

        cols = ("number", "date", "buyer", "sum", "weight", "file")
        headers = ["№", "Дата", "Покупець", "Сума", "Вага", "Файл"]
        self.history_tree = ttk.Treeview(parent, columns=cols, show="headings")
        for c, h in zip(cols, headers):
            self.history_tree.heading(c, text=h)
            self.history_tree.column(c, width=140, anchor="center")
        self.history_tree.column("buyer", width=220, anchor="w")
        self.history_tree.pack(fill="both", expand=True, padx=14, pady=10)

        tk.Button(parent, text="Оновити список", font=FONT, command=self._refresh_history).pack(pady=4)

    def _refresh_history(self):
        self.history_tree.delete(*self.history_tree.get_children())
        for o in db.list_orders():
            self.history_tree.insert("", "end", values=(
                o["order_number"], o["order_date"][:10] if o["order_date"] else "",
                o["buyer_name"], o["total_sum"], o["total_weight"], o["file_name"]
            ))

    # ------------------------------------------------------------------
    # "Звіти та аналітика"
    # ------------------------------------------------------------------
    REPORT_TITLES = {
        "report_summary": "Зведений звіт продажів",
        "report_products": "Звіт по товарах",
        "report_clients": "Звіт по клієнтах",
        "report_geo": "Звіт по географії доставок",
        "report_carriers": "Звіт по перевізниках",
        "report_dynamics": "Динаміка продажів",
    }

    def _build_report_view(self, key):
        parent = tk.Frame(self.content)
        self.views[key] = parent

        tk.Label(parent, text=self.REPORT_TITLES[key], font=FONT_TITLE).pack(anchor="w", padx=14, pady=(14, 6))

        filter_frame = tk.Frame(parent)
        filter_frame.pack(fill="x", padx=14, pady=4)

        today = date.today()
        first_of_month = today.replace(day=1)

        tk.Label(filter_frame, text="Дата з:", font=FONT).pack(side="left")
        date_from_var = tk.StringVar(value=first_of_month.strftime("%d.%m.%Y"))
        tk.Entry(filter_frame, textvariable=date_from_var, width=12, font=FONT).pack(side="left", padx=(4, 14))

        tk.Label(filter_frame, text="Дата по:", font=FONT).pack(side="left")
        date_to_var = tk.StringVar(value=today.strftime("%d.%m.%Y"))
        tk.Entry(filter_frame, textvariable=date_to_var, width=12, font=FONT).pack(side="left", padx=(4, 14))

        tk.Button(filter_frame, text="Сформувати", font=FONT,
                  command=lambda: self._run_report(key)).pack(side="left", padx=(0, 8))
        tk.Button(filter_frame, text="Зберегти в Excel", font=FONT,
                  command=lambda: self._export_report(key)).pack(side="left", padx=(0, 8))
        tk.Button(filter_frame, text="Скопіювати в буфер", font=FONT,
                  command=lambda: self._copy_report(key)).pack(side="left")

        body = tk.Frame(parent)
        body.pack(fill="both", expand=True, padx=14, pady=8)

        table_frame = tk.Frame(body)
        table_frame.pack(side="left", fill="both", expand=True)
        tree = ttk.Treeview(table_frame, show="headings", height=14)
        tree.pack(fill="both", expand=True)

        chart_frame = tk.Frame(body, width=420)
        chart_frame.pack(side="left", fill="both", padx=(14, 0))
        chart_frame.pack_propagate(False)

        summary_label = tk.Label(parent, text="", font=FONT_BOLD, anchor="w", justify="left")
        summary_label.pack(fill="x", padx=14, pady=(0, 10))

        # зберігаємо посилання на віджети та поточні дані звіту для цієї вкладки
        parent.date_from_var = date_from_var
        parent.date_to_var = date_to_var
        parent.tree = tree
        parent.chart_frame = chart_frame
        parent.summary_label = summary_label
        parent.current_headers = []
        parent.current_rows = []
        parent.canvas = None

    def _parse_date(self, text):
        return datetime.strptime(text.strip(), "%d.%m.%Y").date()

    def _run_report(self, key):
        view = self.views[key]
        try:
            date_from = self._parse_date(view.date_from_var.get())
            date_to = self._parse_date(view.date_to_var.get())
        except ValueError:
            messagebox.showerror("Помилка", "Невірний формат дати. Використайте ДД.ММ.РРРР.")
            return
        if date_from > date_to:
            messagebox.showerror("Помилка", "Дата 'з' не може бути пізніше дати 'по'.")
            return

        df, dt = date_from.isoformat(), date_to.isoformat()

        if key == "report_summary":
            self._render_summary(view, df, dt)
        elif key == "report_products":
            self._render_products(view, df, dt)
        elif key == "report_clients":
            self._render_clients(view, df, dt)
        elif key == "report_geo":
            self._render_geo(view, df, dt)
        elif key == "report_carriers":
            self._render_carriers(view, df, dt)
        elif key == "report_dynamics":
            self._render_dynamics(view, df, dt)

    def _set_table(self, view, headers, rows):
        tree = view.tree
        tree.delete(*tree.get_children())
        tree["columns"] = list(range(len(headers)))
        for idx, h in enumerate(headers):
            tree.heading(idx, text=h)
            tree.column(idx, width=140, anchor="center")
        for row in rows:
            tree.insert("", "end", values=row)
        view.current_headers = headers
        view.current_rows = rows

    def _set_chart(self, view, fig):
        for child in view.chart_frame.winfo_children():
            child.destroy()
        canvas = FigureCanvasTkAgg(fig, master=view.chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        view.canvas = canvas

    def _show_chart_unavailable(self, view):
        """Показується замість графіка, якщо matplotlib не встановлено/не вшито в збірку.
        Таблиця звіту при цьому працює повністю — це стосується лише візуалізації."""
        for child in view.chart_frame.winfo_children():
            child.destroy()
        tk.Label(view.chart_frame,
                 text="Графік недоступний\n(модуль matplotlib відсутній у цій збірці).\n"
                      "Таблиця звіту зліва працює як звичайно.",
                 font=FONT_SMALL, fg="#78909C", wraplength=380, justify="center"
                 ).pack(expand=True)

    def _render_summary(self, view, df, dt):
        s = db.report_summary(df, dt)
        headers = ["Показник", "Значення"]
        rows = [
            ("Кількість заявок", s["orders_count"]),
            ("Загальна сума, грн", round(s["total_sum"], 2)),
            ("Загальна вага, кг", round(s["total_weight"], 2)),
            ("Середній чек, грн", round(s["avg_check"], 2)),
        ]
        self._set_table(view, headers, rows)

        ts = db.report_timeseries(df, dt)
        if MATPLOTLIB_AVAILABLE:
            fig = Figure(figsize=(4.2, 3.6), dpi=100)
            ax = fig.add_subplot(111)
            if ts:
                days = [r["day"][5:] for r in ts]
                sums = [r["total_sum"] for r in ts]
                ax.bar(days, sums, color="#2e7d32")
                ax.set_title("Сума продажів по днях", fontsize=10)
                ax.tick_params(axis="x", labelrotation=90, labelsize=7)
            else:
                ax.text(0.5, 0.5, "Немає даних", ha="center", va="center")
            fig.tight_layout()
            self._set_chart(view, fig)
        else:
            self._show_chart_unavailable(view)
        view.summary_label.configure(
            text=f"Період: {df} — {dt}.  Заявок: {s['orders_count']},  "
                 f"сума: {s['total_sum']:.2f} грн,  вага: {s['total_weight']:.2f} кг"
        )

    def _render_products(self, view, df, dt):
        data = db.report_by_product(df, dt)
        headers = ["Товар", "Код", "К-сть", "Сума, грн", "Вага, кг", "Заявок"]
        rows = [(d["product_name"], d["code"], d["total_qty"], round(d["total_sum"], 2),
                  round(d["total_weight"] or 0, 2), d["orders_count"]) for d in data]
        self._set_table(view, headers, rows)

        if MATPLOTLIB_AVAILABLE:
            fig = Figure(figsize=(4.2, 3.6), dpi=100)
            ax = fig.add_subplot(111)
            top = data[:10]
            if top:
                names = [d["product_name"][:14] for d in top][::-1]
                sums = [d["total_sum"] for d in top][::-1]
                ax.barh(names, sums, color="#1565c0")
                ax.set_title("Топ-10 товарів за сумою", fontsize=10)
                ax.tick_params(axis="y", labelsize=7)
            else:
                ax.text(0.5, 0.5, "Немає даних", ha="center", va="center")
            fig.tight_layout()
            self._set_chart(view, fig)
        else:
            self._show_chart_unavailable(view)
        total = sum(d["total_sum"] for d in data)
        view.summary_label.configure(text=f"Період: {df} — {dt}.  Позицій: {len(data)},  сума: {total:.2f} грн")

    def _render_clients(self, view, df, dt):
        data = db.report_by_client(df, dt)
        headers = ["Клієнт", "Заявок", "Сума, грн", "Вага, кг"]
        rows = [(d["buyer_name"], d["orders_count"], round(d["total_sum"], 2),
                  round(d["total_weight"] or 0, 2)) for d in data]
        self._set_table(view, headers, rows)

        if MATPLOTLIB_AVAILABLE:
            fig = Figure(figsize=(4.2, 3.6), dpi=100)
            ax = fig.add_subplot(111)
            top = data[:10]
            if top:
                names = [d["buyer_name"][:14] for d in top][::-1]
                sums = [d["total_sum"] for d in top][::-1]
                ax.barh(names, sums, color="#6a1b9a")
                ax.set_title("Топ-10 клієнтів за сумою", fontsize=10)
                ax.tick_params(axis="y", labelsize=7)
            else:
                ax.text(0.5, 0.5, "Немає даних", ha="center", va="center")
            fig.tight_layout()
            self._set_chart(view, fig)
        else:
            self._show_chart_unavailable(view)
        total = sum(d["total_sum"] for d in data)
        view.summary_label.configure(text=f"Період: {df} — {dt}.  Клієнтів: {len(data)},  сума: {total:.2f} грн")

    def _render_geo(self, view, df, dt):
        data = db.report_by_geo(df, dt)
        headers = ["Область", "Місто", "Заявок", "Сума, грн"]
        rows = [(d["oblast"], d["city"], d["orders_count"], round(d["total_sum"], 2)) for d in data]
        self._set_table(view, headers, rows)

        if MATPLOTLIB_AVAILABLE:
            fig = Figure(figsize=(4.2, 3.6), dpi=100)
            ax = fig.add_subplot(111)
            top = data[:10]
            if top:
                labels = [f"{d['oblast'][:10]}/{d['city'][:10]}" for d in top][::-1]
                sums = [d["total_sum"] for d in top][::-1]
                ax.barh(labels, sums, color="#ef6c00")
                ax.set_title("Топ-10 напрямків доставки", fontsize=10)
                ax.tick_params(axis="y", labelsize=7)
            else:
                ax.text(0.5, 0.5, "Немає даних", ha="center", va="center")
            fig.tight_layout()
            self._set_chart(view, fig)
        else:
            self._show_chart_unavailable(view)
        total = sum(d["total_sum"] for d in data)
        view.summary_label.configure(text=f"Період: {df} — {dt}.  Напрямків: {len(data)},  сума: {total:.2f} грн")

    def _render_carriers(self, view, df, dt):
        data = db.report_by_carrier(df, dt)
        headers = ["Перевізник", "Заявок", "Сума, грн"]
        rows = [(d["carrier"], d["orders_count"], round(d["total_sum"], 2)) for d in data]
        self._set_table(view, headers, rows)

        if MATPLOTLIB_AVAILABLE:
            fig = Figure(figsize=(4.2, 3.6), dpi=100)
            ax = fig.add_subplot(111)
            if data:
                labels = [d["carrier"] for d in data]
                sums = [d["total_sum"] for d in data]
                ax.pie(sums, labels=labels, autopct="%1.0f%%", textprops={"fontsize": 8})
                ax.set_title("Розподіл продажів по перевізниках", fontsize=10)
            else:
                ax.text(0.5, 0.5, "Немає даних", ha="center", va="center")
            fig.tight_layout()
            self._set_chart(view, fig)
        else:
            self._show_chart_unavailable(view)
        total = sum(d["total_sum"] for d in data)
        view.summary_label.configure(text=f"Період: {df} — {dt}.  Сума: {total:.2f} грн")

    def _render_dynamics(self, view, df, dt):
        data = db.report_timeseries(df, dt)
        headers = ["Дата", "Заявок", "Сума, грн"]
        rows = [(d["day"], d["orders_count"], round(d["total_sum"], 2)) for d in data]
        self._set_table(view, headers, rows)

        if MATPLOTLIB_AVAILABLE:
            fig = Figure(figsize=(4.2, 3.6), dpi=100)
            ax = fig.add_subplot(111)
            if data:
                days = [d["day"][5:] for d in data]
                sums = [d["total_sum"] for d in data]
                ax.plot(days, sums, marker="o", color="#c62828")
                ax.set_title("Динаміка суми продажів", fontsize=10)
                ax.tick_params(axis="x", labelrotation=90, labelsize=7)
            else:
                ax.text(0.5, 0.5, "Немає даних", ha="center", va="center")
            fig.tight_layout()
            self._set_chart(view, fig)
        else:
            self._show_chart_unavailable(view)
        total_orders = sum(d["orders_count"] for d in data)
        total_sum = sum(d["total_sum"] for d in data)
        view.summary_label.configure(
            text=f"Період: {df} — {dt}.  Заявок: {total_orders},  сума: {total_sum:.2f} грн")

    def _export_report(self, key):
        view = self.views[key]
        if not view.current_rows:
            messagebox.showwarning("Увага", "Спочатку сформуйте звіт.")
            return
        path = filedialog.asksaveasfilename(
            title="Зберегти звіт", defaultextension=".xlsx",
            initialfile=f"{key}.xlsx",
            filetypes=[("Excel files", "*.xlsx")]
        )
        if not path:
            return
        reports.export_table_to_excel(view.current_headers, view.current_rows,
                                       self.REPORT_TITLES[key], path)
        messagebox.showinfo("Готово", f"Звіт збережено:\n{path}")

    def _copy_report(self, key):
        view = self.views[key]
        if not view.current_rows:
            messagebox.showwarning("Увага", "Спочатку сформуйте звіт.")
            return
        text = reports.table_to_clipboard_text(view.current_headers, view.current_rows)
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("Готово", "Таблицю скопійовано в буфер обміну.\n"
                             "Можна вставити прямо в Excel (Ctrl+V).")


if __name__ == "__main__":
    app = App()
    app.mainloop()
