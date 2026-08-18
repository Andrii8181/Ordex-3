# -*- coding: utf-8 -*-
"""
main.py — головне вікно програми ведення заявок ЧСМ.
Запуск: python3 main.py
"""
import os
import subprocess
import sys
import json
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from datetime import datetime, date, timedelta

import db
import price_import
import order_export
import reports
import ukraine_regions
import carriers
from autocomplete import AutocompleteEntry

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


def resource_path(*parts):
    """
    Повертає абсолютний шлях до вбудованого РЕСУРСУ програми (наприклад,
    файлу іконки), коректно як при звичайному запуску python main.py, так
    і всередині зібраного PyInstaller-ом .exe (--onefile розпаковує дані
    у тимчасову папку, шлях до якої лежить у sys._MEIPASS). Використовувати
    лише для файлів, що постачаються РАЗОМ із програмою (тільки читання) —
    для файлів, які програма сама створює й повинна зберігати між
    запусками (база даних, заявки), використовуйте persistent_base_dir().
    """
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, *parts)


def persistent_base_dir():
    """
    Повертає папку поруч зі справжнім .exe-файлом — саме туди мають
    зберігатись файли, які повинні лишатись між запусками програми
    (згенеровані заявки, бланки ТТН). На відміну від resource_path(),
    яка навмисно вказує на тимчасову розпаковану папку (та зникає одразу
    після закриття програми), тут sys.executable дає стабільне
    розташування самого .exe.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def enable_windows_dpi_awareness():
    """
    Головна причина "розмитого" тексту у звичайних Tkinter-програмах на
    Windows — це НЕ шрифт, а те, що Windows масштабує все вікно програми
    як картинку (bitmap stretching), якщо програма не повідомила систему,
    що вміє сама коректно малювати на екранах з масштабуванням >100%
    (а майже всі сучасні ноутбуки/монітори мають масштабування 125–150%).
    Цей виклик має відбутися ДО створення головного вікна.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

CARRIERS = ["Нова Пошта", "САТ", "Делівері", "Самовивіз"]
DELIVERY_TYPES = [("branch", "На відділення"), ("address", "Адресна доставка")]

OUTPUT_DIR = os.path.join(persistent_base_dir(), "orders")

# -- Єдиний шрифт для всієї програми: чіткий, без розмиття --
FONT = ("Segoe UI", 11)
FONT_BOLD = ("Segoe UI", 11, "bold")
FONT_SMALL = ("Segoe UI", 10)
FONT_TITLE = ("Segoe UI", 15, "bold")
FONT_TOPBAR = ("Segoe UI", 12)
FONT_TOPBAR_BOLD = ("Segoe UI", 12, "bold")

# -- Кольорова палітра (у стилі логотипу Ordex: глибокий синій + бірюзовий) --
COLOR_SIDEBAR = "#16232F"        # темно-синій, майже графітовий
COLOR_SIDEBAR_ACTIVE = "#1F3A4D"
COLOR_TOPBAR = "#1C2E3D"
COLOR_TOPBAR_HOVER = "#2A4457"
COLOR_ACCENT = "#20B2A6"         # бірюзовий акцент з логотипу
COLOR_ACCENT_DARK = "#189488"
COLOR_BG = "#F2F5F7"             # світлий фон робочої області
COLOR_CARD = "#FFFFFF"
COLOR_BORDER = "#DCE3E8"
COLOR_TEXT = "#1C2B36"
COLOR_TEXT_MUTED = "#7C8A93"

SIDEBAR_ITEMS = [
    ("order", "Нова заявка"),
    ("history", "Історія заявок"),
    ("clients", "Клієнти"),
]

REPORT_MENU_ITEMS = [
    ("report_summary", "Зведення"),
    ("report_products", "Товари"),
    ("report_clients", "Клієнти"),
    ("report_geo", "Географія"),
    ("report_carriers", "Перевізники"),
    ("report_dynamics", "Динаміка"),
]

DEFAULT_TRACKING_INTERVAL_MINUTES = 30
TOAST_WIDTH = 340


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Ordex — платформа для замовлень та звітів")
        self.geometry("1520x900")
        self.minsize(1180, 680)
        self.configure(bg=COLOR_BG)
        self._set_app_icon()

        # -- глобальний шрифт --
        self.option_add("*Font", FONT)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=FONT, background=COLOR_BG)
        style.configure("Treeview", font=FONT, rowheight=28,
                         background=COLOR_CARD, fieldbackground=COLOR_CARD,
                         borderwidth=0)
        style.configure("Treeview.Heading", font=FONT_BOLD,
                         background="#EDF1F3", foreground=COLOR_TEXT, relief="flat")
        style.map("Treeview", background=[("selected", COLOR_ACCENT)],
                  foreground=[("selected", "white")])
        style.configure("TCombobox", font=FONT)
        style.configure("TNotebook.Tab", font=FONT)

        db.init_db()
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        self.selected_client = None
        self.current_items = []
        self._selected_product = None
        self._warehouse_cache = {}
        self._warehouse_fetch_in_progress = set()

        # -- глобальна світла тема: замість переписування кожного віджета
        # окремо, задаємо кольори за замовчуванням через реєстр опцій Tk.
        # Віджети, яким явно задано bg/fg у коді (сайдбар, топбар, кнопки-
        # акценти), просто перекривають ці значення локально. --
        self.option_add("*Background", COLOR_BG)
        self.option_add("*Foreground", COLOR_TEXT)
        self.option_add("*Entry.Background", "white")
        self.option_add("*Entry.relief", "solid")
        self.option_add("*Entry.borderWidth", 1)
        self.option_add("*Entry.highlightThickness", 1)
        self.option_add("*Entry.highlightColor", COLOR_ACCENT)
        self.option_add("*Entry.highlightBackground", COLOR_BORDER)
        self.option_add("*Button.Background", "#E7ECEF")
        self.option_add("*Button.activeBackground", "#DCE3E8")
        self.option_add("*Button.relief", "flat")
        self.option_add("*Button.borderWidth", 0)
        self.option_add("*Button.cursor", "hand2")
        self.option_add("*Button.padX", 12)
        self.option_add("*Button.padY", 6)
        self.option_add("*Listbox.Background", "white")
        self.option_add("*Listbox.relief", "solid")
        self.option_add("*Listbox.borderWidth", 1)
        self.option_add("*Labelframe.Background", COLOR_BG)
        self.option_add("*Labelframe.foreground", COLOR_TEXT_MUTED)
        self.option_add("*Radiobutton.Background", COLOR_BG)
        self.option_add("*Radiobutton.activeBackground", COLOR_BG)

        # -- верхня панель: Файл / Налаштування / Звіти --
        self._build_topbar()

        # -- бокове меню + область контенту --
        container = tk.Frame(self, bg=COLOR_BG)
        container.pack(fill="both", expand=True)

        sidebar = tk.Frame(container, bg=COLOR_SIDEBAR, width=220)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        self.sidebar_buttons = {}
        for key, label in SIDEBAR_ITEMS:
            btn = tk.Button(sidebar, text="  " + label, anchor="w", relief="flat",
                             bg=COLOR_SIDEBAR, fg="white",
                             activebackground=COLOR_SIDEBAR_ACTIVE,
                             activeforeground="white", font=FONT, bd=0,
                             cursor="hand2",
                             padx=16, pady=12, command=lambda k=key: self._show_view(k))
            btn.pack(fill="x", padx=8, pady=(16, 2) if label == SIDEBAR_ITEMS[0][1] else (2, 2))
            self.sidebar_buttons[key] = btn

        self.content = tk.Frame(container, bg=COLOR_BG)
        self.content.pack(side="left", fill="both", expand=True)

        self.views = {}
        self._build_order_view()
        self._build_history_view()
        self._build_clients_view()
        for key, _label in REPORT_MENU_ITEMS:
            self._build_report_view(key)

        self._show_view("order")

        # -- фонове відстеження статусу доставок --
        self._toast_stack = []
        self._tracking_in_progress = False
        self._tracking_after_id = None
        self.after(3000, self._run_tracking_check_async)

    def _get_tracking_interval_minutes(self):
        try:
            return max(1, int(db.get_setting("tracking_interval_minutes",
                                              DEFAULT_TRACKING_INTERVAL_MINUTES)))
        except (TypeError, ValueError):
            return DEFAULT_TRACKING_INTERVAL_MINUTES

    def _get_show_notifications_setting(self):
        return db.get_setting("show_notifications", "1") != "0"

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
    def _make_scrollable(self, parent):
        """
        Створює вертикально прокручувану область: Canvas + Scrollbar,
        всередині якої розміщується звичайний Frame. Повертає (inner, canvas) —
        усі віджети додаються в inner як зазвичай. Використовується для
        вкладки "Нова заявка", щоб вміст ніколи не обрізався незалежно від
        розміру вікна (кнопка "Сформувати заявку" завжди буде доступна).
        """
        outer = tk.Frame(parent, bg=COLOR_BG)
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer, bg=COLOR_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=COLOR_BG)

        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        def on_inner_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", on_inner_configure)

        def on_canvas_configure(event):
            canvas.itemconfig(inner_id, width=event.width)
        canvas.bind("<Configure>", on_canvas_configure)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        return inner, canvas

    def _bind_wheel_deep(self, widget, canvas, skip=()):
        """
        Прив'язує прокрутку колесом миші до widget і рекурсивно до всіх його
        нащадків, крім тих, що в skip (і їхніх нащадків) — їм лишається
        власна прокрутка (наприклад, таблиця товарів має власну смугу).
        Завдяки цьому колесо миші прокручує саме ту область, над якою
        зараз курсор: головну форму або таблицю товарів.
        """
        if widget in skip:
            return
        if isinstance(widget, ttk.Combobox):
            return  # у комбобоксів своя реакція на колесо миші

        def on_mousewheel(event, _canvas=canvas):
            delta = -1 if getattr(event, "num", None) == 5 or event.delta < 0 else 1
            _canvas.yview_scroll(-delta, "units")

        widget.bind("<MouseWheel>", on_mousewheel)
        widget.bind("<Button-4>", on_mousewheel)
        widget.bind("<Button-5>", on_mousewheel)
        for child in widget.winfo_children():
            self._bind_wheel_deep(child, canvas, skip=skip)

    def _show_view(self, key):
        for frame in self.views.values():
            frame.pack_forget()
        self.views[key].pack(fill="both", expand=True)
        for k, btn in self.sidebar_buttons.items():
            btn.configure(bg=COLOR_SIDEBAR_ACTIVE if k == key else COLOR_SIDEBAR)
        if key == "history":
            self._refresh_history()
        elif key == "clients":
            self._refresh_clients()

    # ------------------------------------------------------------------
    # Верхня панель: Файл / Налаштування / Звіти
    # ------------------------------------------------------------------
    def _build_topbar(self):
        topbar = tk.Frame(self, bg=COLOR_TOPBAR, height=54)
        topbar.pack(fill="x", side="top")
        topbar.pack_propagate(False)

        # -- логотип + назва програми, у верхньому лівому куті вікна --
        brand = tk.Frame(topbar, bg=COLOR_TOPBAR)
        brand.pack(side="left", padx=(14, 22))
        png_path = resource_path("assets", "ordex_icon_256.png")
        self._logo_img = None
        if os.path.exists(png_path):
            try:
                img = tk.PhotoImage(file=png_path)
                # 256px джерело -> ~42px у топбарі (subsample приймає лише цілий коефіцієнт)
                self._logo_img = img.subsample(6, 6)
                tk.Label(brand, image=self._logo_img, bg=COLOR_TOPBAR).pack(side="left")
            except tk.TclError:
                pass
        # назва "Ordex" з останньою буквою "X" — велика, курсивна, кольором
        # логотипа, як окремий акцент
        tk.Label(brand, text="Orde", bg=COLOR_TOPBAR, fg="white",
                 font=("Segoe UI", 15, "bold")).pack(side="left", padx=(8, 0))
        tk.Label(brand, text="X", bg=COLOR_TOPBAR, fg=COLOR_ACCENT,
                 font=("Segoe UI", 16, "bold italic")).pack(side="left")

        self._topbar_buttons = {}

        def make_topbar_button(text, build_menu_fn):
            btn = tk.Menubutton(topbar, text=text, font=FONT_TOPBAR_BOLD,
                                 bg=COLOR_TOPBAR, fg="white",
                                 activebackground=COLOR_TOPBAR_HOVER,
                                 activeforeground="white",
                                 bd=0, relief="flat", padx=18, pady=9,
                                 cursor="hand2")
            menu = tk.Menu(btn, tearoff=0, font=FONT_TOPBAR)
            build_menu_fn(menu)
            btn.configure(menu=menu)
            btn.pack(side="left")
            return btn

        make_topbar_button("Файл", self._populate_file_menu)
        make_topbar_button("Налаштування", self._populate_settings_menu)
        make_topbar_button("Звіти", self._populate_reports_menu)

    def _populate_file_menu(self, menu):
        menu.add_command(label="Завантажити прайс-лист...", command=self._import_price_dialog)

    def _populate_settings_menu(self, menu):
        menu.add_command(label="Відправники...", command=self._senders_dialog)
        menu.add_command(label="Сповіщення та відстеження...", command=self._tracking_settings_dialog)

    def _populate_reports_menu(self, menu):
        for key, label in REPORT_MENU_ITEMS:
            menu.add_command(label=label, command=lambda k=key: self._show_view(k))

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

    def _senders_dialog(self):
        """
        Об'єднаний профіль відправника: спосіб оплати, телефон, ім'я — і,
        якщо цей відправник відправляє через певного перевізника, тут же
        місто/відділення відправника, а для перевізників з підключеним API
        (наразі Нова Пошта) — ще й сам ключ і Ref-и для автоматичного ТТН.
        """
        win = tk.Toplevel(self)
        win.title("Відправники")
        win.configure(bg=COLOR_BG)
        win.transient(self)
        win.resizable(False, False)

        wrap = tk.Frame(win, bg=COLOR_BG, padx=16, pady=16)
        wrap.pack(fill="both", expand=True)

        def resize_to_content():
            win.update_idletasks()
            req_w = max(win.winfo_reqwidth(), 560)
            req_h = win.winfo_reqheight()
            x = self.winfo_rootx() + (self.winfo_width() - req_w) // 2
            y = self.winfo_rooty() + (self.winfo_height() - req_h) // 2
            win.geometry(f"{req_w}x{req_h}+{max(x, 0)}+{max(y, 0)}")

        tk.Label(wrap, text="Відправники", font=FONT_BOLD,
                 bg=COLOR_BG, fg=COLOR_TEXT).pack(anchor="w", pady=(0, 4))
        tk.Label(wrap,
                 text="Кожен спосіб оплати — це окремий відправник зі своїм телефоном,\n"
                      "ім'ям, перевізником і (за потреби) API-ключем для автоматичного ТТН.",
                 font=FONT_SMALL, bg=COLOR_BG, fg=COLOR_TEXT_MUTED,
                 justify="left").pack(anchor="w", pady=(0, 12))

        tree = ttk.Treeview(wrap, columns=("phone", "sender_name", "carrier", "api"),
                             show="tree headings", height=5)
        tree.heading("#0", text="Спосіб оплати")
        tree.heading("phone", text="Телефон")
        tree.heading("sender_name", text="Ім'я відправника")
        tree.heading("carrier", text="Перевізник")
        tree.heading("api", text="API-ключ")
        tree.column("#0", width=150)
        tree.column("phone", width=130)
        tree.column("sender_name", width=170)
        tree.column("carrier", width=110)
        tree.column("api", width=110, anchor="center")
        tree.pack(fill="x", pady=(0, 4))

        def refresh():
            tree.delete(*tree.get_children())
            for s in db.get_senders():
                tree.insert("", "end", text=s["payment_method"], values=(
                    s["phone"] or "", s["sender_name"] or "", s["carrier"] or "",
                    "є" if s.get("api_key") else "—"
                ))
        refresh()

        form = tk.LabelFrame(wrap, text="Додати / редагувати відправника", font=FONT_SMALL,
                              bg=COLOR_BG, fg=COLOR_TEXT_MUTED, padx=12, pady=10)
        form.pack(fill="x", pady=(10, 0))

        tk.Label(form, text="Спосіб оплати:", bg=COLOR_BG, font=FONT).grid(
            row=0, column=0, sticky="w", pady=4)
        method_var = tk.StringVar()
        tk.Entry(form, textvariable=method_var, width=26, font=FONT).grid(
            row=0, column=1, sticky="w", padx=(8, 0), pady=4)

        tk.Label(form, text="Телефон:", bg=COLOR_BG, font=FONT).grid(
            row=1, column=0, sticky="w", pady=4)
        phone_var = tk.StringVar()
        tk.Entry(form, textvariable=phone_var, width=26, font=FONT).grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=4)

        def lookup_sender_by_phone():
            phone = phone_var.get().strip()
            if not phone:
                messagebox.showwarning("Увага", "Спочатку вкажіть телефон.")
                return
            key = api_key_var.get().strip()
            found_via_np = False
            self.config(cursor="watch")
            self.update_idletasks()
            try:
                if key:
                    try:
                        result = carriers.find_sender_by_phone(key, phone)
                    except carriers.CarrierAPIError:
                        result = None
                    if result:
                        sender_name_var.set(result.get("name") or sender_name_var.get())
                        if result.get("city"):
                            sender_city_var.set(result["city"])
                        sender_cp_ref_var.set(result.get("sender_ref") or "")
                        sender_contact_ref_var.set(result.get("contact_ref") or "")
                        found_via_np = True

                local_match = None
                if not found_via_np:
                    digits = "".join(ch for ch in phone if ch.isdigit())
                    for s in db.get_senders():
                        s_digits = "".join(ch for ch in (s.get("phone") or "") if ch.isdigit())
                        if digits and digits in s_digits:
                            local_match = s
                            break
                    if local_match:
                        sender_name_var.set(local_match.get("sender_name") or sender_name_var.get())
                        if local_match.get("carrier"):
                            carrier_var.set(local_match["carrier"])
                        extra_m = local_match.get("extra") or {}
                        if extra_m.get("sender_city"):
                            sender_city_var.set(extra_m["sender_city"])
                        update_carrier_fields()
            finally:
                self.config(cursor="")

            if found_via_np:
                messagebox.showinfo("Готово", "Дані підтягнуто з Нової Пошти за телефоном.")
            elif local_match:
                messagebox.showinfo("Готово", "Нова Пошта не знайшла збігу — "
                                     "дані підтягнуто з власної бази.")
            else:
                messagebox.showinfo("Не знайдено", "Не вдалось знайти дані за цим "
                                     "телефоном — введіть їх вручну.")

        tk.Button(form, text="Знайти дані за телефоном", font=FONT_SMALL,
                  bg="#ECEFF1", fg=COLOR_TEXT, relief="flat", padx=8, pady=3,
                  cursor="hand2", command=lookup_sender_by_phone).grid(
            row=1, column=2, sticky="w", padx=(6, 0))

        tk.Label(form, text="Ім'я відправника:", bg=COLOR_BG, font=FONT).grid(
            row=2, column=0, sticky="w", pady=4)
        sender_name_var = tk.StringVar()
        tk.Entry(form, textvariable=sender_name_var, width=26, font=FONT).grid(
            row=2, column=1, sticky="w", padx=(8, 0), pady=4)

        tk.Label(form, text="Перевізник:", bg=COLOR_BG, font=FONT).grid(
            row=3, column=0, sticky="w", pady=4)
        carrier_var = tk.StringVar(value="")
        carrier_combo = ttk.Combobox(form, textvariable=carrier_var,
                                      values=[""] + CARRIERS[:-1], state="readonly",
                                      width=23, font=FONT)
        carrier_combo.grid(row=3, column=1, sticky="w", padx=(8, 0), pady=4)

        # -- місто відправника: потрібне для будь-якого перевізника. Номер
        # відділення відправника тепер обирається прямо в заявці (там може
        # бути 1 або 7 — залежно від того, звідки цього разу відправляють) --
        common_frame = tk.Frame(form, bg=COLOR_BG)
        common_frame.grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))

        tk.Label(common_frame, text="Місто відправника:", bg=COLOR_BG, font=FONT).grid(
            row=0, column=0, sticky="w", pady=3)
        sender_city_var = tk.StringVar()
        tk.Entry(common_frame, textvariable=sender_city_var, width=22, font=FONT).grid(
            row=0, column=1, sticky="w", padx=(8, 0), pady=3)

        # -- API-ключ і Ref-и: наразі є лише для Нової Пошти --
        np_frame = tk.Frame(form, bg=COLOR_BG)
        np_frame.grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 0))

        tk.Label(np_frame, text="API-ключ:", bg=COLOR_BG, font=FONT).grid(
            row=0, column=0, sticky="w", pady=3)
        api_key_var = tk.StringVar()
        api_key_entry = tk.Entry(np_frame, textvariable=api_key_var, width=45, font=FONT, show="•")
        api_key_entry.grid(row=0, column=1, sticky="w", padx=(8, 0), pady=3)

        def paste_api_key():
            try:
                clip = self.clipboard_get()
            except tk.TclError:
                return
            api_key_var.set(clip.strip())

        tk.Button(np_frame, text="Вставити", font=FONT_SMALL, bg="#ECEFF1", fg=COLOR_TEXT,
                  relief="flat", padx=8, pady=2, cursor="hand2",
                  command=paste_api_key).grid(row=0, column=2, sticky="w", padx=(6, 0))
        show_key_var = tk.BooleanVar(value=False)
        tk.Checkbutton(np_frame, text="показати", variable=show_key_var, bg=COLOR_BG,
                        font=FONT_SMALL,
                        command=lambda: api_key_entry.configure(
                            show="" if show_key_var.get() else "•")
                        ).grid(row=0, column=3, sticky="w", padx=(6, 0))

        tk.Label(np_frame, text="Ref контрагента-відправника:", bg=COLOR_BG, font=FONT).grid(
            row=1, column=0, sticky="w", pady=3)
        sender_cp_ref_var = tk.StringVar()
        tk.Entry(np_frame, textvariable=sender_cp_ref_var, width=40, font=FONT).grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=3)

        tk.Label(np_frame, text="Ref контактної особи відправника:", bg=COLOR_BG, font=FONT).grid(
            row=2, column=0, sticky="w", pady=3)
        sender_contact_ref_var = tk.StringVar()
        tk.Entry(np_frame, textvariable=sender_contact_ref_var, width=40, font=FONT).grid(
            row=2, column=1, sticky="w", padx=(8, 0), pady=3)

        def auto_discover_refs():
            key = api_key_var.get().strip()
            if not key:
                messagebox.showwarning("Увага", "Спочатку вкажіть API-ключ.")
                return
            self.config(cursor="watch")
            self.update_idletasks()
            try:
                result = carriers.discover_sender_refs(key)
                sender_cp_ref_var.set(result["sender_ref"])
                sender_contact_ref_var.set(result["contact_ref"])
                messagebox.showinfo(
                    "Готово",
                    f"Знайдено відправника «{result['name']}» — Ref-и підставлено автоматично."
                )
            except carriers.CarrierAPIError as e:
                messagebox.showerror("Не вдалось знайти автоматично", str(e))
            finally:
                self.config(cursor="")

        tk.Button(np_frame, text="Отримати Ref автоматично", font=FONT_SMALL,
                  bg="#ECEFF1", fg=COLOR_TEXT, relief="flat", padx=8, pady=3,
                  cursor="hand2", command=auto_discover_refs).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(2, 4))

        tk.Label(np_frame,
                 text="Ref контрагента й контактної особи відправника — це ваші\n"
                      "ідентифікатори в системі Нової Пошти. Кнопка вище знаходить\n"
                      "їх автоматично за API-ключем (перший зареєстрований\n"
                      "відправник на акаунті); якщо не спрацює — їх можна взяти\n"
                      "в кабінеті my.novaposhta.ua, розділ «Контрагенти».\n"
                      "Для САТ і Делівері API поки не підключено — досить міста й\n"
                      "відділення вище, ТТН для них створюється вручну.",
                 bg=COLOR_BG, fg=COLOR_TEXT_MUTED, font=FONT_SMALL,
                 justify="left").grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

        def update_carrier_fields(*_args):
            carrier = carrier_var.get()
            if carrier:
                common_frame.grid()
            else:
                common_frame.grid_remove()
            if carrier == "Нова Пошта":
                np_frame.grid()
            else:
                np_frame.grid_remove()
            resize_to_content()
        carrier_combo.bind("<<ComboboxSelected>>", update_carrier_fields)

        def load_selected(event=None):
            sel = tree.selection()
            if not sel:
                return
            method = tree.item(sel[0], "text")
            s = db.get_sender(method)
            if not s:
                return
            method_var.set(s["payment_method"])
            phone_var.set(s["phone"] or "")
            sender_name_var.set(s["sender_name"] or "")
            carrier_var.set(s["carrier"] or "")
            api_key_var.set(s["api_key"] or "")
            extra = s.get("extra") or {}
            sender_city_var.set(extra.get("sender_city") or "")
            sender_cp_ref_var.set(extra.get("sender_counterparty_ref") or "")
            sender_contact_ref_var.set(extra.get("sender_contact_ref") or "")
            update_carrier_fields()
        tree.bind("<<TreeviewSelect>>", load_selected)
        update_carrier_fields()

        def clear_form():
            method_var.set("")
            phone_var.set("")
            sender_name_var.set("")
            carrier_var.set("")
            api_key_var.set("")
            sender_city_var.set("")
            sender_cp_ref_var.set("")
            sender_contact_ref_var.set("")
            update_carrier_fields()

        def save_sender():
            if not method_var.get().strip() or not phone_var.get().strip():
                messagebox.showwarning("Увага", "Вкажіть спосіб оплати і телефон.")
                return
            phone_normalized = db.format_phone_display(phone_var.get().strip())
            extra = {}
            if carrier_var.get():
                extra = {
                    "sender_city": sender_city_var.get().strip(),
                }
                if carrier_var.get() == "Нова Пошта":
                    extra["sender_counterparty_ref"] = sender_cp_ref_var.get().strip()
                    extra["sender_contact_ref"] = sender_contact_ref_var.get().strip()
            db.set_sender(method_var.get().strip(), phone_normalized,
                           sender_name_var.get().strip() or None,
                           carrier_var.get().strip() or None,
                           api_key_var.get().strip() or None, extra)
            clear_form()
            refresh()
            self._reload_payment_methods()
            self._update_ttn_availability_hint()
            messagebox.showinfo("Готово", "Відправника збережено.")

        def delete_selected():
            sel = tree.selection()
            if not sel:
                return
            method = tree.item(sel[0], "text")
            db.delete_sender(method)
            clear_form()
            refresh()
            self._reload_payment_methods()
            self._update_ttn_availability_hint()

        btns = tk.Frame(wrap, bg=COLOR_BG)
        btns.pack(fill="x", pady=(12, 0))
        tk.Button(btns, text="Зберегти", font=FONT, bg=COLOR_ACCENT, fg="white",
                  activebackground=COLOR_ACCENT_DARK, activeforeground="white",
                  relief="flat", padx=12, pady=6, cursor="hand2",
                  command=save_sender).pack(side="left")
        tk.Button(btns, text="Нове поле (очистити форму)", font=FONT, bg="#ECEFF1", fg=COLOR_TEXT,
                  relief="flat", padx=12, pady=6, cursor="hand2",
                  command=clear_form).pack(side="left", padx=8)
        tk.Button(btns, text="Видалити вибране", font=FONT, bg="#ECEFF1", fg=COLOR_TEXT,
                  relief="flat", padx=12, pady=6, cursor="hand2",
                  command=delete_selected).pack(side="left")

        resize_to_content()

    def _tracking_settings_dialog(self):
        win = tk.Toplevel(self)
        win.title("Сповіщення та відстеження")
        win.configure(bg=COLOR_BG)
        win.transient(self)
        win.resizable(False, False)

        wrap = tk.Frame(win, bg=COLOR_BG, padx=16, pady=16)
        wrap.pack(fill="both", expand=True)

        tk.Label(wrap, text="Сповіщення та відстеження доставок", font=FONT_BOLD,
                 bg=COLOR_BG, fg=COLOR_TEXT).pack(anchor="w", pady=(0, 4))
        tk.Label(wrap,
                 text="Програма автоматично перевіряє статус заявок з ТТН при запуску,\n"
                      "а далі — з обраним інтервалом, поки програма відкрита (навіть згорнута).",
                 font=FONT_SMALL, bg=COLOR_BG, fg=COLOR_TEXT_MUTED,
                 justify="left").pack(anchor="w", pady=(0, 14))

        show_var = tk.BooleanVar(value=self._get_show_notifications_setting())
        tk.Checkbutton(wrap, text="Показувати спливаючі повідомлення про зміну статусу доставки",
                        variable=show_var, font=FONT, bg=COLOR_BG).pack(anchor="w")

        interval_frame = tk.Frame(wrap, bg=COLOR_BG)
        interval_frame.pack(anchor="w", pady=(12, 0))
        tk.Label(interval_frame, text="Перевіряти статус кожні", font=FONT,
                 bg=COLOR_BG).pack(side="left")
        interval_var = tk.StringVar(value=str(self._get_tracking_interval_minutes()))
        tk.Entry(interval_frame, textvariable=interval_var, width=5, font=FONT).pack(side="left", padx=6)
        tk.Label(interval_frame, text="хв", font=FONT, bg=COLOR_BG).pack(side="left")

        def save_and_close():
            try:
                minutes = max(1, int(interval_var.get().strip()))
            except ValueError:
                messagebox.showerror("Помилка", "Інтервал має бути цілим числом хвилин.")
                return
            db.set_setting("tracking_interval_minutes", minutes)
            db.set_setting("show_notifications", "1" if show_var.get() else "0")
            win.destroy()
            messagebox.showinfo("Готово", "Налаштування збережено.")

        tk.Button(wrap, text="Зберегти", font=FONT, bg=COLOR_ACCENT, fg="white",
                  activebackground=COLOR_ACCENT_DARK, activeforeground="white",
                  relief="flat", padx=12, pady=6, cursor="hand2",
                  command=save_and_close).pack(anchor="w", pady=(16, 0))

        win.update_idletasks()
        req_w = max(win.winfo_reqwidth(), 480)
        req_h = win.winfo_reqheight()
        x = self.winfo_rootx() + (self.winfo_width() - req_w) // 2
        y = self.winfo_rooty() + (self.winfo_height() - req_h) // 2
        win.geometry(f"{req_w}x{req_h}+{max(x, 0)}+{max(y, 0)}")

    # ------------------------------------------------------------------
    # "Нова заявка"
    # ------------------------------------------------------------------
    def _build_order_view(self):
        parent = tk.Frame(self.content)
        self.views["order"] = parent

        canvas_wrap, order_canvas = self._make_scrollable(parent)

        top = tk.Frame(canvas_wrap)
        top.pack(fill="x", padx=14, pady=10)

        left = tk.Frame(top)
        left.pack(side="left", fill="both", expand=True, anchor="n")
        right = tk.Frame(top)
        right.pack(side="left", fill="both", expand=True, padx=(28, 0), anchor="n")

        tk.Label(left, text="ВІДПРАВНИК", font=FONT_BOLD, fg=COLOR_ACCENT_DARK,
                 bg=COLOR_BG).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        tk.Label(right, text="ПОКУПЕЦЬ ТА ОДЕРЖУВАЧ", font=FONT_BOLD, fg=COLOR_ACCENT_DARK,
                 bg=COLOR_BG).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        # ================= ЛІВА КОЛОНКА: ВІДПРАВНИК =================
        r = 1
        tk.Label(left, text="№ заявки:", font=FONT).grid(row=r, column=0, sticky="w", pady=3)
        self.order_number_var = tk.StringVar()
        tk.Entry(left, textvariable=self.order_number_var, width=16, font=FONT).grid(row=r, column=1, sticky="w")
        r += 1

        tk.Label(left, text="Дата створення:", font=FONT).grid(row=r, column=0, sticky="w", pady=3)
        tk.Label(left, text=date.today().strftime("%d.%m.%Y"), font=FONT).grid(row=r, column=1, sticky="w")
        r += 1

        tk.Label(left, text="Відповідальний, ПІБ:", font=FONT).grid(row=r, column=0, sticky="w", pady=3)
        self.responsible_var = tk.StringVar(value="ЧСМ")
        tk.Entry(left, textvariable=self.responsible_var, width=32, font=FONT).grid(row=r, column=1, sticky="w")
        r += 1

        tk.Label(left, text="Спосіб оплати (опл):", font=FONT).grid(row=r, column=0, sticky="w", pady=3)
        self.payment_var = tk.StringVar()
        self.payment_combo = ttk.Combobox(left, textvariable=self.payment_var, width=28, font=FONT,
                                           values=[s["payment_method"] for s in db.get_senders()])
        self.payment_combo.grid(row=r, column=1, sticky="w")
        self.payment_combo.bind("<<ComboboxSelected>>", self._on_payment_selected)
        r += 1

        tk.Label(left, text="Телефон відправника:", font=FONT).grid(row=r, column=0, sticky="w", pady=3)
        self.sender_phone_var = tk.StringVar()
        sender_phone_entry_widget = tk.Entry(left, textvariable=self.sender_phone_var, width=32, font=FONT)
        sender_phone_entry_widget.grid(row=r, column=1, sticky="w")
        sender_phone_entry_widget.bind("<FocusOut>", self._on_sender_phone_focus_out)
        r += 1

        tk.Label(left, text="Ім'я відправника (для ТТН):", font=FONT).grid(row=r, column=0, sticky="w", pady=3)
        self.sender_name_var = tk.StringVar()
        tk.Entry(left, textvariable=self.sender_name_var, width=32, font=FONT).grid(row=r, column=1, sticky="w")
        r += 1

        tk.Label(left, text="Відділення відправника:", font=FONT).grid(row=r, column=0, sticky="w", pady=3)
        self.sender_warehouse_var = tk.StringVar(value="1")
        wh_frame = tk.Frame(left, bg=COLOR_BG)
        wh_frame.grid(row=r, column=1, sticky="w")
        tk.Radiobutton(wh_frame, text="1", variable=self.sender_warehouse_var,
                        value="1", font=FONT, bg=COLOR_BG).pack(side="left", padx=(0, 12))
        tk.Radiobutton(wh_frame, text="7", variable=self.sender_warehouse_var,
                        value="7", font=FONT, bg=COLOR_BG).pack(side="left")
        r += 1

        # ================= ПРАВА КОЛОНКА: ПОКУПЕЦЬ ТА ОДЕРЖУВАЧ =================
        # Порядок полів: телефон -> покупець -> перевізник -> тип доставки ->
        # область -> населений пункт -> відділення/адреса -> одержувач.
        self.buyer_address_var = tk.StringVar()  # заповнюється автоматично, без окремого поля

        r2 = 1
        tk.Label(right, text="Телефон одержувача:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        self.recipient_phone_entry = AutocompleteEntry(
            right, search_fn=self._search_clients_by_phone_fn, on_select=self._on_client_selected,
            width=30, font=FONT
        )
        self.recipient_phone_entry.grid(row=r2, column=1, sticky="w")
        self.recipient_phone_entry.entry.bind("<FocusOut>", self._on_recipient_phone_focus_out)
        r2 += 1

        tk.Label(right, text="Покупець:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        self.buyer_entry = AutocompleteEntry(
            right, search_fn=self._search_clients_fn, on_select=self._on_client_selected,
            width=30, font=FONT
        )
        self.buyer_entry.grid(row=r2, column=1, sticky="w")
        # покупець і одержувач зазвичай одна й та сама особа — якщо поле
        # "Одержувач, ПІБ" ще порожнє, підставляємо туди ім'я покупця
        # (не перезаписуючи, якщо там уже щось вручну вписано)
        self.buyer_entry.entry.bind("<FocusOut>", self._on_buyer_name_focus_out)
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

        tk.Label(right, text="Область одержувача:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        self.oblast_entry = AutocompleteEntry(
            right, search_fn=self._search_oblasts_fn, on_select=self._on_oblast_selected,
            width=30, font=FONT
        )
        self.oblast_entry.grid(row=r2, column=1, sticky="w")
        r2 += 1

        tk.Label(right, text="Населений пункт:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        self.city_entry = AutocompleteEntry(
            right, search_fn=self._search_cities_fn, on_select=lambda l, p: None,
            width=30, font=FONT
        )
        self.city_entry.grid(row=r2, column=1, sticky="w")
        r2 += 1

        tk.Label(right, text="№ відділення:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        self.carrier_branch_entry = AutocompleteEntry(
            right, search_fn=self._search_recipient_warehouses_fn,
            on_select=self._on_recipient_warehouse_selected, width=32, font=FONT
        )
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

        tk.Label(right, text="Тип одержувача:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        self.recipient_type_var = tk.StringVar(value="individual")
        rtype_frame = tk.Frame(right, bg=COLOR_BG)
        rtype_frame.grid(row=r2, column=1, sticky="w")
        tk.Radiobutton(rtype_frame, text="Фізична особа", variable=self.recipient_type_var,
                        value="individual", font=FONT, bg=COLOR_BG,
                        command=lambda: self._on_recipient_type_changed()).pack(side="left", padx=(0, 8))
        tk.Radiobutton(rtype_frame, text="Юридична особа", variable=self.recipient_type_var,
                        value="legal", font=FONT, bg=COLOR_BG,
                        command=lambda: self._on_recipient_type_changed()).pack(side="left")
        r2 += 1

        self.recipient_edrpou_label = tk.Label(right, text="ЄДРПОУ:", font=FONT)
        self.recipient_edrpou_label.grid(row=r2, column=0, sticky="w", pady=3)
        self.recipient_edrpou_var = tk.StringVar()
        self.recipient_edrpou_entry = tk.Entry(right, textvariable=self.recipient_edrpou_var,
                                                 width=16, font=FONT)
        self.recipient_edrpou_entry.grid(row=r2, column=1, sticky="w")
        self.recipient_edrpou_label.grid_remove()
        self.recipient_edrpou_entry.grid_remove()
        r2 += 1

        tk.Label(right, text="Одержувач, ПІБ:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        self.recipient_name_var = tk.StringVar()
        tk.Entry(right, textvariable=self.recipient_name_var, width=32, font=FONT).grid(row=r2, column=1, sticky="w")
        r2 += 1

        tk.Label(right, text="Оплата доставки:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        self.payer_type_var = tk.StringVar(value="recipient")
        payer_frame = tk.Frame(right, bg=COLOR_BG)
        payer_frame.grid(row=r2, column=1, sticky="w")
        tk.Radiobutton(payer_frame, text="Відправник", variable=self.payer_type_var,
                        value="sender", font=FONT, bg=COLOR_BG).pack(side="left", padx=(0, 8))
        tk.Radiobutton(payer_frame, text="Одержувач", variable=self.payer_type_var,
                        value="recipient", font=FONT, bg=COLOR_BG).pack(side="left")
        r2 += 1

        tk.Label(right, text="Кількість місць:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        self.seats_amount_var = tk.StringVar(value="1")
        tk.Entry(right, textvariable=self.seats_amount_var, width=8, font=FONT).grid(row=r2, column=1, sticky="w")
        r2 += 1

        tk.Label(right, text="Накладений платіж:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        cod_frame = tk.Frame(right, bg=COLOR_BG)
        cod_frame.grid(row=r2, column=1, sticky="w")
        self.cod_enabled_var = tk.BooleanVar(value=False)
        self.cod_amount_var = tk.StringVar()
        self.cod_amount_entry = tk.Entry(cod_frame, textvariable=self.cod_amount_var,
                                          width=12, font=FONT, state="disabled")

        def on_cod_toggle():
            self.cod_amount_entry.configure(state="normal" if self.cod_enabled_var.get() else "disabled")
            if not self.cod_enabled_var.get():
                self.cod_amount_var.set("")

        tk.Checkbutton(cod_frame, text="так, сума:", variable=self.cod_enabled_var,
                        font=FONT, bg=COLOR_BG, command=on_cod_toggle).pack(side="left")
        self.cod_amount_entry.pack(side="left", padx=(6, 0))
        tk.Label(cod_frame, text="грн (для отримання на відділенні)", font=FONT_SMALL,
                 bg=COLOR_BG, fg=COLOR_TEXT_MUTED).pack(side="left", padx=(6, 0))
        r2 += 1

        tk.Label(right, text="", bg=COLOR_BG).grid(row=r2, column=0)
        r2 += 1

        ttn_frame = tk.Frame(right, bg=COLOR_BG)
        ttn_frame.grid(row=r2, column=0, columnspan=2, sticky="we", pady=(4, 0))
        self.auto_ttn_var = tk.BooleanVar(value=True)
        self.auto_ttn_check = tk.Checkbutton(
            ttn_frame, text="Створити ТТН автоматично при формуванні заявки",
            variable=self.auto_ttn_var, font=FONT, bg=COLOR_BG
        )
        self.auto_ttn_check.pack(anchor="w")
        # прихований лейбл-підказка: логіка вмикання/вимикання прапорця (напр.
        # для самовивозу) лишається, але текст користувачу більше не показуємо
        self.ttn_status_label = tk.Label(ttn_frame, text="")
        r2 += 1
        # номер ТТН стає відомим лише ПІСЛЯ формування заявки — тому окремого
        # поля тут немає, номер показується у вікні підтвердження і в
        # "Історії заявок"

        self._apply_delivery_state()
        self._update_ttn_availability_hint()

        # -- рядок додавання товару --
        add_frame = tk.LabelFrame(canvas_wrap, text="Додати товар", font=FONT)
        add_frame.pack(fill="x", padx=14, pady=8)

        tk.Label(add_frame, text="Товар:", font=FONT).grid(row=0, column=0, padx=4, pady=8, sticky="w")
        self.product_entry = AutocompleteEntry(
            add_frame, search_fn=self._search_products_fn, on_select=self._on_product_selected,
            width=38, font=FONT
        )
        self.product_entry.grid(row=0, column=1, padx=4)

        tk.Label(add_frame, text="Код:", font=FONT).grid(row=0, column=2, padx=4)
        self.item_code_entry = AutocompleteEntry(
            add_frame, search_fn=self._search_products_by_code_fn,
            on_select=self._on_product_code_selected, width=20, font=FONT
        )
        self.item_code_entry.grid(row=0, column=3, padx=4)

        tk.Label(add_frame, text="Ціна:", font=FONT).grid(row=0, column=4, padx=4)
        self.item_price_var = tk.StringVar()
        tk.Entry(add_frame, textvariable=self.item_price_var, width=8, font=FONT, state="readonly").grid(row=0, column=5)

        tk.Label(add_frame, text="Вага/од:", font=FONT).grid(row=0, column=6, padx=4)
        self.item_weight_var = tk.StringVar()
        tk.Entry(add_frame, textvariable=self.item_weight_var, width=8, font=FONT, state="readonly").grid(row=0, column=7)

        tk.Label(add_frame, text="К-сть:", font=FONT).grid(row=0, column=8, padx=4)
        self.item_qty_var = tk.StringVar(value="1")
        tk.Entry(add_frame, textvariable=self.item_qty_var, width=6, font=FONT).grid(row=0, column=9)

        tk.Button(add_frame, text="+", width=3, font=FONT_BOLD, bg=COLOR_ACCENT, fg="white",
                  activebackground=COLOR_ACCENT_DARK, activeforeground="white",
                  command=self._add_item).grid(row=0, column=10, padx=8)

        # -- таблиця товарів (з вертикальною прокруткою — заявка може мати
        # багато позицій) --
        table_frame = tk.Frame(canvas_wrap)
        table_frame.pack(fill="both", expand=True, padx=14, pady=4)

        cols = ("code", "name", "unit", "qty", "price", "sum", "weight_unit", "weight_total")
        headers = ["Код", "Найменування", "Од.вим", "К-сть", "Ціна", "Сума", "Вага/од", "Вага всього"]
        self.items_tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=8)
        for c, h in zip(cols, headers):
            self.items_tree.heading(c, text=h)
            self.items_tree.column(c, width=100, anchor="center")
        self.items_tree.column("name", width=200, anchor="w")

        items_scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.items_tree.yview)
        self.items_tree.configure(yscrollcommand=items_scrollbar.set)
        self.items_tree.pack(side="left", fill="both", expand=True)
        items_scrollbar.pack(side="right", fill="y")

        def on_items_wheel(event):
            delta = -1 if getattr(event, "num", None) == 5 or event.delta < 0 else 1
            self.items_tree.yview_scroll(-delta, "units")
        self.items_tree.bind("<MouseWheel>", on_items_wheel)
        self.items_tree.bind("<Button-4>", on_items_wheel)
        self.items_tree.bind("<Button-5>", on_items_wheel)

        btn_row = tk.Frame(canvas_wrap)
        btn_row.pack(fill="x", padx=14, pady=(4, 0))
        tk.Button(btn_row, text="Видалити вибраний рядок", font=FONT,
                  command=self._remove_selected_item).pack(side="left")

        # "Разом" і кнопка формування заявки — в один рядок одразу під
        # таблицею товарів, а не окремими рядками нижче
        totals_row = tk.Frame(canvas_wrap)
        totals_row.pack(fill="x", padx=14, pady=14)
        tk.Button(totals_row, text="Сформувати заявку", bg=COLOR_ACCENT, fg="white",
                  activebackground=COLOR_ACCENT_DARK, activeforeground="white",
                  font=FONT_BOLD, padx=22, pady=10,
                  command=self._generate_order).pack(side="left")
        self.totals_label = tk.Label(totals_row, text="Разом: 0.00 грн,  0.00 кг", font=FONT_BOLD)
        self.totals_label.pack(side="right", anchor="s", pady=(0, 4))

        # -- колесо миші прокручує область під курсором: над формою — форму,
        # над таблицею товарів — саму таблицю (вона виключена через skip) --
        self._bind_wheel_deep(canvas_wrap, order_canvas, skip={self.items_tree})

    def _reload_payment_methods(self):
        self.payment_combo["values"] = [s["payment_method"] for s in db.get_senders()]

    def _on_recipient_type_changed(self):
        if self.recipient_type_var.get() == "legal":
            self.recipient_edrpou_label.grid()
            self.recipient_edrpou_entry.grid()
        else:
            self.recipient_edrpou_label.grid_remove()
            self.recipient_edrpou_entry.grid_remove()
            self.recipient_edrpou_var.set("")

    # -- логіка перевізник / тип доставки --
    def _apply_delivery_state(self):
        carrier = self.carrier_var.get()
        is_pickup = (carrier == "Самовивіз")

        for rb in self.delivery_radios:
            rb.configure(state="disabled" if is_pickup else "normal")

        if is_pickup:
            self.carrier_branch_entry.set("")
            self.street_var.set("")
            self.building_var.set("")
            self.apartment_var.set("")
            self.carrier_branch_entry.set_state("disabled")
            self.street_entry.configure(state="disabled")
            self.building_entry.configure(state="disabled")
            self.apartment_entry.configure(state="disabled")
            return

        delivery_type = self.delivery_type_var.get()
        if delivery_type == "branch":
            self.carrier_branch_entry.set_state("normal")
            self.street_entry.configure(state="disabled")
            self.building_entry.configure(state="disabled")
            self.apartment_entry.configure(state="disabled")
            self.street_var.set("")
            self.building_var.set("")
            self.apartment_var.set("")
        else:
            self.carrier_branch_entry.set_state("disabled")
            self.carrier_branch_entry.set("")
            self.street_entry.configure(state="normal")
            self.building_entry.configure(state="normal")
            self.apartment_entry.configure(state="normal")

    def _on_carrier_changed(self, event=None):
        self._apply_delivery_state()
        self._update_ttn_availability_hint()

    def _on_delivery_type_changed(self):
        self._apply_delivery_state()
        self._update_ttn_availability_hint()

    def _update_ttn_availability_hint(self):
        """Показує під прапорцем «Створити ТТН автоматично» коротку підказку
        про те, чи налаштовано автоматичне створення для поточного відправника."""
        carrier = self.carrier_var.get()
        if carrier == "Самовивіз":
            self.auto_ttn_check.configure(state="disabled")
            self.auto_ttn_var.set(False)
            self.ttn_status_label.configure(text="Самовивіз не потребує ТТН.")
            return

        self.auto_ttn_check.configure(state="normal")

        if carrier != "Нова Пошта":
            self.ttn_status_label.configure(
                text=f"Автоматичне ТТН для «{carrier}» поки не підключено — "
                     f"потрібна документація API цього перевізника."
            )
            return

        method = self.payment_var.get().strip()
        if not method:
            self.ttn_status_label.configure(
                text="Оберіть спосіб оплати (відправника) — від нього залежить API-ключ для ТТН."
            )
            return

        sender = db.get_sender(method)
        if not sender or not sender.get("api_key"):
            self.ttn_status_label.configure(
                text=f"У відправника «{method}» не вказано API-ключ "
                     f"(Налаштування → Відправники)."
            )
            return
        if sender.get("carrier") != carrier:
            self.ttn_status_label.configure(
                text=f"Відправник «{method}» налаштований для перевізника "
                     f"«{sender.get('carrier') or '—'}», а обрано «{carrier}». "
                     f"Перевірте Налаштування → Відправники."
            )
            return
        extra = sender.get("extra") or {}
        required = ["sender_city", "sender_counterparty_ref", "sender_contact_ref"]
        if not all(extra.get(f) for f in required):
            self.ttn_status_label.configure(
                text=f"У відправника «{method}» не вистачає даних для ТТН "
                     f"(Налаштування → Відправники)."
            )
            return
        if self.delivery_type_var.get() != "branch":
            self.ttn_status_label.configure(
                text="Автоматичне ТТН підтримується лише для доставки «На відділення»."
            )
            return
        self.ttn_status_label.configure(text="Готово до автоматичного створення ТТН.")

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

    def _search_recipient_warehouses_fn(self, text):
        """
        Підказки номерів відділень одержувача — підтягуються напряму з
        довідника Нової Пошти для обраного міста (кешується по місту, щоб
        не бити API-запитами на кожну натиснуту клавішу). Якщо API
        недоступне (немає ключа/мережі) — поле лишається звичайним
        текстовим і номер можна ввести вручну, підказки просто не з'являться.
        """
        if self.carrier_var.get() != "Нова Пошта":
            return []
        city = self.city_entry.get().strip()
        if not city:
            return []
        cache_key = city.lower()
        if cache_key not in self._warehouse_cache:
            self._start_warehouse_fetch(city)
            return []
        warehouses = self._warehouse_cache[cache_key]
        prefix = text.strip().lower()
        if prefix:
            warehouses = [w for w in warehouses
                          if prefix in w["number"].lower() or prefix in w["description"].lower()]
        return [(f"№{w['number']} — {w['description']}", w["number"]) for w in warehouses[:15]]

    def _on_recipient_warehouse_selected(self, label, number):
        self.carrier_branch_entry.set(str(number))

    def _get_np_api_key_for_current_sender(self):
        sender = db.get_sender(self.payment_var.get().strip())
        if sender and sender.get("carrier") == "Нова Пошта" and sender.get("api_key"):
            return sender["api_key"]
        return None

    def _start_warehouse_fetch(self, city):
        cache_key = city.lower()
        if cache_key in self._warehouse_fetch_in_progress:
            return
        api_key = self._get_np_api_key_for_current_sender()
        if not api_key:
            return  # без ключа підказки просто недоступні — поле лишається ручним
        self._warehouse_fetch_in_progress.add(cache_key)

        def worker():
            try:
                result = carriers.get_warehouses_for_city(api_key, city)
            except carriers.CarrierAPIError:
                result = []
            self.after(0, lambda: self._apply_warehouse_fetch_result(cache_key, result))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_warehouse_fetch_result(self, cache_key, result):
        self._warehouse_cache[cache_key] = result
        self._warehouse_fetch_in_progress.discard(cache_key)
        # якщо користувач усе ще друкує в полі відділення — одразу
        # перепоказати підказки, тепер уже з довантаженими даними
        if self.focus_get() == self.carrier_branch_entry.entry:
            self.carrier_branch_entry._on_text_changed()

    def _search_products_fn(self, text):
        products = db.search_products(text)
        return [(f"{p['name']} ({p['code']})" if p["code"] else p["name"], p) for p in products]

    def _search_products_by_code_fn(self, text):
        products = db.search_products_by_code(text)
        return [(f"{p['code']} — {p['name']}", p) for p in products]

    def _search_clients_by_phone_fn(self, text):
        clients = db.search_clients_by_phone(text)
        return [(c["phone"], c) for c in clients if c.get("phone")]

    # -- обробники вибору --
    def _on_client_selected(self, label, client):
        self.selected_client = client
        self.buyer_address_var.set(client.get("address") or "")
        self.recipient_phone_entry.set(db.format_phone_display(client.get("phone") or ""))
        if not self.buyer_entry.get().strip():
            self.buyer_entry.set(client.get("full_name") or "")
        self.oblast_entry.set(client.get("oblast") or "")
        self.city_entry.set(client.get("city") or "")
        self.recipient_name_var.set(client.get("full_name") or "")
        if client.get("carrier"):
            self.carrier_var.set(client["carrier"])
        if client.get("carrier_branch"):
            self.carrier_branch_entry.set(client["carrier_branch"] or "")
        if client.get("delivery_type"):
            self.delivery_type_var.set(client["delivery_type"])
        self.street_var.set(client.get("street") or "")
        self.building_var.set(client.get("building") or "")
        self.apartment_var.set(client.get("apartment") or "")
        self._apply_delivery_state()

    def _on_buyer_name_focus_out(self, event=None):
        """Покупець і одержувач зазвичай одна й та сама особа: якщо
        покупця вписано вручну (без вибору з підказок) і поле одержувача
        ще порожнє — підставляємо туди те саме ім'я."""
        buyer_name = self.buyer_entry.get().strip()
        if buyer_name and not self.recipient_name_var.get().strip():
            self.recipient_name_var.set(buyer_name)

    def _on_sender_phone_focus_out(self, event=None):
        """Телефон відправника завжди приводимо до вигляду +380XXXXXXXXX —
        саме такий формат вимагають перевізники для ТТН."""
        value = self.sender_phone_var.get().strip()
        if value:
            self.sender_phone_var.set(db.format_phone_display(value))

    def _on_recipient_phone_focus_out(self, event=None):
        """Те саме для телефону одержувача."""
        value = self.recipient_phone_entry.get().strip()
        if value:
            self.recipient_phone_entry.set(db.format_phone_display(value))

    def _on_payment_selected(self, event=None):
        method = self.payment_var.get()
        sender = db.get_sender(method)
        if sender:
            self.sender_phone_var.set(db.format_phone_display(sender.get("phone") or ""))
            self.sender_name_var.set(sender.get("sender_name") or "")
            if sender.get("carrier"):
                self.carrier_var.set(sender["carrier"])
                self._apply_delivery_state()
        self._update_ttn_availability_hint()

    def _on_oblast_selected(self, label, payload):
        self.city_entry.set("")

    def _on_product_selected(self, label, product):
        self._selected_product = product
        self.item_code_entry.set(product.get("code") or "")
        self.item_price_var.set(str(product.get("price") or ""))
        self.item_weight_var.set(str(product.get("weight") or ""))

    def _on_product_code_selected(self, label, product):
        self._selected_product = product
        self.product_entry.set(product.get("name") or "")
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
        self.item_code_entry.set("")
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

        # телефони завжди приводимо до єдиного вигляду +380XXXXXXXXX
        recipient_phone = db.format_phone_display(self.recipient_phone_entry.get().strip())
        sender_phone = db.format_phone_display(self.sender_phone_var.get().strip())
        if recipient_phone:
            self.recipient_phone_entry.set(recipient_phone)
        if sender_phone:
            self.sender_phone_var.set(sender_phone)

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
        self.buyer_address_var.set(recipient_address)

        client_id = db.upsert_client(
            full_name=buyer_name,
            phone=recipient_phone or None,
            oblast=oblast or None,
            city=city or None,
            address=recipient_address or None,
            carrier=carrier or None,
            carrier_branch=self.carrier_branch_entry.get().strip() or None,
            delivery_type=delivery_type or None,
            street=self.street_var.get().strip() or None,
            building=self.building_var.get().strip() or None,
            apartment=self.apartment_var.get().strip() or None,
        )
        try:
            seats_amount = max(1, int(self.seats_amount_var.get().strip() or "1"))
        except ValueError:
            messagebox.showerror("Помилка", "Кількість місць має бути цілим числом.")
            return

        cod_amount = None
        if self.cod_enabled_var.get():
            try:
                cod_amount = float(self.cod_amount_var.get().strip().replace(",", "."))
            except ValueError:
                messagebox.showerror("Помилка", "Вкажіть суму накладеного платежу числом.")
                return

        db.remember_city(oblast, city)

        order_date = date.today()
        header = {
            "order_number": self.order_number_var.get().strip(),
            "order_date": datetime(order_date.year, order_date.month, order_date.day),
            "buyer_name": buyer_name,
            "buyer_address": recipient_address,
            "responsible": self.responsible_var.get().strip() or "ЧСМ",
            "payment_method": self.payment_var.get().strip(),
            "sender_phone": sender_phone,
            "sender_name": self.sender_name_var.get().strip(),
            "recipient_phone": recipient_phone,
            "carrier": carrier,
            "carrier_branch": self.carrier_branch_entry.get().strip() if delivery_type == "branch" else "",
            "delivery_type": delivery_type,
            "street": self.street_var.get().strip(),
            "building": self.building_var.get().strip(),
            "apartment": self.apartment_var.get().strip(),
            "recipient_oblast": oblast,
            "recipient_city": city,
            "recipient_address": recipient_address,
            "recipient_name": self.recipient_name_var.get().strip() or buyer_name,
            "recipient_type": self.recipient_type_var.get(),
            "recipient_edrpou": self.recipient_edrpou_var.get().strip() or None,
            "payer_type": self.payer_type_var.get(),
            "seats_amount": seats_amount,
            "cod_amount": cod_amount,
            "sender_warehouse_number": self.sender_warehouse_var.get(),
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

        # -- автоматичне створення ТТН (якщо увімкнено і перевізник підтримується) --
        header["ttn"] = None
        header["ttn_ref"] = None
        header["ttn_status"] = None
        header["ttn_error"] = None
        header["ttn_pdf_path"] = None
        if self.auto_ttn_var.get() and carrier != "Самовивіз":
            sender = db.get_sender(self.payment_var.get().strip())
            if sender and sender.get("carrier") == carrier:
                sender_extra = dict(sender.get("extra") or {})
                # відділення відправника обирається щоразу прямо в заявці
                # (1 або 7), а не зберігається в профілі відправника
                sender_extra["sender_warehouse"] = header["sender_warehouse_number"]
                credentials = {"api_key": sender.get("api_key"), "extra": sender_extra}
            else:
                credentials = None
            try:
                if sender is None:
                    raise carriers.CarrierAPIError(
                        "Оберіть спосіб оплати (відправника) — від нього залежить, "
                        "яким API-ключем створювати ТТН."
                    )
                if sender.get("carrier") != carrier:
                    raise carriers.CarrierAPIError(
                        f"Відправник «{self.payment_var.get().strip()}» налаштований для "
                        f"перевізника «{sender.get('carrier') or '—'}», а в заявці обрано "
                        f"«{carrier}». Перевірте Налаштування → Відправники."
                    )
                self.config(cursor="watch")
                self.update_idletasks()
                result = carriers.create_ttn(carrier, header, self.current_items, credentials)
                header["ttn"] = result["ttn"]
                header["ttn_ref"] = result.get("ref")
                header["ttn_status"] = "created"

                # -- одразу пробуємо завантажити друкований бланк ТТН; якщо
                # не вийде — не критично, заявка все одно збережеться, а
                # бланк можна буде довантажити пізніше з "Історії заявок".
                # Тут навмисно ловимо БУДЬ-яку помилку (не лише CarrierAPIError) —
                # збереження самої заявки не повинно залежати від того, чи
                # вдалось довантажити PDF-бланк. --
                try:
                    pdf_bytes = carriers.fetch_ttn_pdf(header["ttn_ref"], credentials["api_key"])
                    pdf_name = filename.rsplit(".", 1)[0] + "_ттн.pdf"
                    pdf_path = os.path.join(OUTPUT_DIR, pdf_name)
                    os.makedirs(OUTPUT_DIR, exist_ok=True)
                    with open(pdf_path, "wb") as f:
                        f.write(pdf_bytes)
                    header["ttn_pdf_path"] = pdf_path
                except Exception:
                    pass  # бланк можна довантажити пізніше вручну з історії
            except Exception as e:
                header["ttn_status"] = "failed"
                header["ttn_error"] = str(e)
                if isinstance(e, carriers.CarrierAPIError):
                    reason_text = str(e)
                else:
                    reason_text = f"Технічна помилка в програмі: {e}"
                messagebox.showwarning(
                    "ТТН не створено",
                    f"Заявку буде сформовано без ТТН. Причина:\n\n{reason_text}\n\n"
                    f"Ви можете створити ТТН вручну на сайті перевізника і "
                    f"пізніше повернутись до цього."
                )
            finally:
                self.config(cursor="")

        order_export.generate_order_excel(header, items_for_export, output_path)

        db.save_order(header, self.current_items, filename)

        if header.get("ttn"):
            messagebox.showinfo("Готово", f"Заявку збережено:\n{output_path}\n\n№ ТТН: {header['ttn']}")
        else:
            messagebox.showinfo("Готово", f"Заявку збережено:\n{output_path}")
        self._reset_order_form()

    def _reset_order_form(self):
        self.order_number_var.set("")
        self.buyer_entry.set("")
        self.buyer_address_var.set("")
        self.payment_var.set("")
        self.sender_phone_var.set("")
        self.sender_name_var.set("")
        self.recipient_phone_entry.set("")
        self.carrier_var.set(CARRIERS[0])
        self.delivery_type_var.set("branch")
        self.carrier_branch_entry.set("")
        self.street_var.set("")
        self.building_var.set("")
        self.apartment_var.set("")
        self.oblast_entry.set("")
        self.city_entry.set("")
        self.recipient_name_var.set("")
        self.recipient_type_var.set("individual")
        self._on_recipient_type_changed()
        self.payer_type_var.set("recipient")
        self.seats_amount_var.set("1")
        self.cod_enabled_var.set(False)
        self.cod_amount_var.set("")
        self.cod_amount_entry.configure(state="disabled")
        self.sender_warehouse_var.set("1")
        self.auto_ttn_var.set(True)
        self.current_items = []
        self.items_tree.delete(*self.items_tree.get_children())
        self._update_totals()
        self._apply_delivery_state()
        self._update_ttn_availability_hint()

    # ------------------------------------------------------------------
    # Фонове відстеження статусу доставок
    # ------------------------------------------------------------------
    def _run_tracking_check_async(self):
        if self._tracking_in_progress:
            return
        orders = db.list_active_ttn_orders()
        if not orders:
            self._schedule_next_tracking_check()
            return
        self._tracking_in_progress = True
        threading.Thread(target=self._tracking_check_worker, args=(orders,), daemon=True).start()

    def _tracking_check_worker(self, orders):
        results = []
        for o in orders:
            carrier = o.get("carrier")
            ttn = o.get("ttn")
            if not carrier or not ttn:
                continue
            sender = db.get_sender(o.get("payment_method") or "")
            if sender and sender.get("carrier") == carrier:
                credentials = {"api_key": sender.get("api_key"), "extra": sender.get("extra") or {}}
            else:
                credentials = None
            try:
                result = carriers.track_status(carrier, ttn, credentials, o.get("recipient_phone"))
                results.append((o, result, None))
            except carriers.CarrierAPIError as e:
                results.append((o, None, str(e)))
        self.after(0, lambda: self._apply_tracking_results(results))

    def _apply_tracking_results(self, results):
        show_notifications = self._get_show_notifications_setting()
        for o, result, error in results:
            if result is None:
                continue  # тиха помилка перевірки одного ТТН не повинна заважати іншим
            new_status = result["status"]
            delivered = result["delivered"]
            old_status = o.get("tracking_status")
            db.update_order_tracking(o["id"], new_status,
                                      json.dumps(result.get("raw") or {}, ensure_ascii=False),
                                      delivered)
            if new_status != old_status and show_notifications:
                recipient_name = o.get("recipient_name") or o.get("buyer_name") or "Одержувач"
                city = o.get("recipient_city") or ""
                city_part = f" м. {city}" if city else ""
                if delivered:
                    message = f"Відправлення для {recipient_name}{city_part} отримано."
                else:
                    message = f"Відправлення для {recipient_name}{city_part}: {new_status}."
                self._show_notification_toast(message)

        if results:
            self._refresh_history()

        self._tracking_in_progress = False
        self._schedule_next_tracking_check()

    def _schedule_next_tracking_check(self):
        if self._tracking_after_id is not None:
            try:
                self.after_cancel(self._tracking_after_id)
            except (ValueError, tk.TclError):
                pass
        interval_ms = self._get_tracking_interval_minutes() * 60 * 1000
        self._tracking_after_id = self.after(interval_ms, self._run_tracking_check_async)

    # ------------------------------------------------------------------
    # Спливаючі повідомлення (знизу справа екрана)
    # ------------------------------------------------------------------
    def _show_notification_toast(self, message):
        toast = tk.Toplevel(self)
        toast.overrideredirect(True)
        try:
            toast.attributes("-topmost", True)
        except tk.TclError:
            pass
        toast.configure(bg=COLOR_CARD, highlightthickness=1, highlightbackground=COLOR_BORDER)

        content = tk.Frame(toast, bg=COLOR_CARD, padx=12, pady=10)
        content.pack(fill="both", expand=True)

        header = tk.Frame(content, bg=COLOR_CARD)
        header.pack(fill="x")
        tk.Label(header, text="Ordex — статус доставки", font=FONT_BOLD, bg=COLOR_CARD,
                 fg=COLOR_ACCENT_DARK).pack(side="left")
        tk.Button(header, text="✕", font=FONT_SMALL, bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                  bd=0, relief="flat", cursor="hand2", padx=4, pady=0,
                  activebackground=COLOR_CARD,
                  command=lambda: self._close_toast(toast)).pack(side="right")

        tk.Label(content, text=message, font=FONT_SMALL, bg=COLOR_CARD, fg=COLOR_TEXT,
                 wraplength=TOAST_WIDTH - 24, justify="left").pack(fill="x", pady=(6, 0), anchor="w")

        toast.update_idletasks()
        req_h = toast.winfo_reqheight()
        toast.geometry(f"{TOAST_WIDTH}x{req_h}")

        self._toast_stack.append(toast)
        self._reposition_toasts()

    def _close_toast(self, toast):
        if toast in self._toast_stack:
            self._toast_stack.remove(toast)
        if toast.winfo_exists():
            toast.destroy()
        self._reposition_toasts()

    def _reposition_toasts(self):
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        margin_right = 20
        margin_bottom = 60  # орієнтовно над панеллю завдань, біля годинника
        gap = 8
        y_cursor = screen_h - margin_bottom
        for toast in reversed(self._toast_stack):
            if not toast.winfo_exists():
                continue
            h = toast.winfo_height() or toast.winfo_reqheight()
            y_cursor -= h
            x = screen_w - TOAST_WIDTH - margin_right
            toast.geometry(f"+{x}+{y_cursor}")
            y_cursor -= gap

    # ------------------------------------------------------------------
    # "Історія заявок"
    # ------------------------------------------------------------------
    def _build_history_view(self):
        parent = tk.Frame(self.content)
        self.views["history"] = parent

        header_row = tk.Frame(parent)
        header_row.pack(fill="x", padx=14, pady=(14, 6))
        tk.Label(header_row, text="Історія заявок", font=FONT_TITLE).pack(side="left")
        tk.Button(header_row, text="Перевірити статуси зараз", font=FONT,
                  command=self._run_tracking_check_async).pack(side="right")

        cols = ("number", "date", "buyer", "sum", "weight", "ttn", "status", "file")
        headers = ["№", "Дата", "Покупець", "Сума", "Вага", "№ ТТН", "Статус доставки", "Файл"]
        self.history_tree = ttk.Treeview(parent, columns=cols, show="headings")
        for c, h in zip(cols, headers):
            # клік по заголовку сортує за цією колонкою (з прив'язкою рядка
            # цілком — не тільки значення колонки)
            self.history_tree.heading(c, text=h, command=lambda col=c: self._sort_history(col))
            self.history_tree.column(c, width=110, anchor="center")
        self.history_tree.column("buyer", width=190, anchor="w")
        self.history_tree.column("ttn", width=130, anchor="center")
        self.history_tree.column("status", width=200, anchor="w")

        self.history_tree.tag_configure("delivered", background="#DCF3E6")
        self.history_tree.tag_configure("in_transit", background="#FFF6DA")
        self.history_tree.tag_configure("ttn_failed", background="#FBE1E1")
        self.history_tree.tag_configure("cancelled", background="#E5E5E5")
        self.history_tree.tag_configure("order_cancelled", background="#F5C6C6")
        self.history_tree.tag_configure("no_ttn", background=COLOR_CARD)

        self.history_tree.pack(fill="both", expand=True, padx=14, pady=10)
        self.history_tree.bind("<Double-1>", lambda e: self._open_order_details_from_selection())

        btn_row = tk.Frame(parent)
        btn_row.pack(fill="x", padx=14, pady=4)
        tk.Button(btn_row, text="Оновити список", font=FONT,
                  command=self._refresh_history).pack(side="left")
        tk.Button(btn_row, text="Переглянути деталі", font=FONT,
                  command=self._open_order_details_from_selection).pack(side="left", padx=8)
        tk.Button(btn_row, text="Скасувати ТТН", font=FONT, bg="#FBE1E1", fg=COLOR_TEXT,
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  command=self._cancel_selected_ttn).pack(side="left")
        tk.Button(btn_row, text="Видалити заявку", font=FONT, bg="#E5A3A3", fg="white",
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  command=self._cancel_selected_order).pack(side="left", padx=8)

        # стан сортування: (ключ_колонки, reverse)
        self._history_orders = []
        self._history_sort_column = None
        self._history_sort_reverse = False

    def _refresh_history(self):
        self._history_orders = db.list_orders()
        self._render_history_rows(self._history_orders)

    def _render_history_rows(self, orders):
        self.history_tree.delete(*self.history_tree.get_children())
        for o in orders:
            ttn_display = o.get("ttn") or ("не створено" if o.get("ttn_status") == "failed" else "")
            if o.get("order_status") == "cancelled":
                status_display = "ЗАЯВКУ СКАСОВАНО"
            elif o.get("ttn_status") == "cancelled":
                status_display = "ТТН скасовано"
            else:
                status_display = o.get("tracking_status") or ""

            if o.get("order_status") == "cancelled":
                tag = "order_cancelled"
            elif o.get("ttn_status") == "cancelled":
                tag = "cancelled"
            elif o.get("ttn_status") == "failed" and not o.get("ttn"):
                tag = "ttn_failed"
            elif o.get("tracking_delivered"):
                tag = "delivered"
            elif o.get("ttn") and status_display:
                tag = "in_transit"
            else:
                tag = "no_ttn"

            self.history_tree.insert("", "end", iid=str(o["id"]), values=(
                o["order_number"], o["order_date"][:10] if o["order_date"] else "",
                o["buyer_name"], o["total_sum"], o["total_weight"], ttn_display,
                status_display, o["file_name"]
            ), tags=(tag,))

    def _sort_history(self, column):
        if self._history_sort_column == column:
            self._history_sort_reverse = not self._history_sort_reverse
        else:
            self._history_sort_column = column
            self._history_sort_reverse = False

        def sort_key(o):
            if column == "number":
                val = o.get("order_number") or ""
                try:
                    return (0, float(val))
                except (TypeError, ValueError):
                    return (1, str(val))
            if column == "date":
                return o.get("order_date") or ""
            if column == "buyer":
                return (o.get("buyer_name") or "").lower()
            if column == "sum":
                return o.get("total_sum") or 0
            if column == "weight":
                return o.get("total_weight") or 0
            if column == "ttn":
                return o.get("ttn") or ""
            if column == "status":
                if o.get("order_status") == "cancelled":
                    return "ЗАЯВКУ СКАСОВАНО"
                return o.get("tracking_status") or ""
            if column == "file":
                return (o.get("file_name") or "").lower()
            return ""

        sorted_orders = sorted(self._history_orders, key=sort_key, reverse=self._history_sort_reverse)
        self._render_history_rows(sorted_orders)

        # позначаємо колонку стрілкою напряму в заголовку, щоб було видно,
        # за чим і в якому напрямку зараз відсортовано
        cols = ("number", "date", "buyer", "sum", "weight", "ttn", "status", "file")
        headers = ["№", "Дата", "Покупець", "Сума", "Вага", "№ ТТН", "Статус доставки", "Файл"]
        arrow = " ▼" if self._history_sort_reverse else " ▲"
        for c, h in zip(cols, headers):
            text = h + (arrow if c == column else "")
            self.history_tree.heading(c, text=text)

    def _cancel_selected_ttn(self):
        sel = self.history_tree.selection()
        if not sel:
            messagebox.showwarning("Увага", "Виберіть заявку в списку.")
            return
        self._cancel_ttn_for_order(int(sel[0]))

    def _perform_ttn_cancel(self, order):
        """Сама дія скасування ТТН без жодних діалогів — повертає
        (True, None) при успіху або (False, текст_помилки) при невдачі.
        Викликається і зі скасування самого ТТН, і зі скасування заявки
        цілком."""
        sender = db.get_sender(order.get("payment_method") or "")
        if sender and sender.get("carrier") == order.get("carrier"):
            credentials = {"api_key": sender.get("api_key"), "extra": sender.get("extra") or {}}
        else:
            credentials = None
        try:
            carriers.cancel_ttn(order["carrier"], order.get("ttn_ref"), credentials)
            db.mark_order_ttn_cancelled(order["id"])
            return True, None
        except carriers.CarrierAPIError as e:
            return False, str(e)

    def _cancel_ttn_for_order(self, order_id, refresh_dialog_callback=None):
        order = db.get_order(order_id)
        if not order:
            return
        if not order.get("ttn"):
            messagebox.showinfo("Немає ТТН", "У цієї заявки немає створеного ТТН.")
            return
        if order.get("ttn_status") == "cancelled":
            messagebox.showinfo("Вже скасовано", "ТТН цієї заявки вже позначено як скасований.")
            return

        confirm = messagebox.askyesno(
            "Скасувати ТТН?",
            f"Скасувати ТТН №{order['ttn']} для заявки №{order['order_number']}?\n\n"
            f"Сама заявка залишиться в історії — скасовується лише накладна "
            f"на перевізника. Це можливо, поки посилку ще не забрали на "
            f"відправлення."
        )
        if not confirm:
            return

        self.config(cursor="watch")
        self.update_idletasks()
        ok, err = self._perform_ttn_cancel(order)
        self.config(cursor="")
        if ok:
            messagebox.showinfo("Готово", f"ТТН №{order['ttn']} скасовано.")
        else:
            messagebox.showerror(
                "Не вдалось скасувати",
                f"{err}\n\nЯкщо посилку вже прийняв перевізник, скасувати ТТН "
                f"можна лише через його підтримку або кабінет."
            )
        self._refresh_history()
        if refresh_dialog_callback:
            refresh_dialog_callback()

    def _cancel_selected_order(self):
        sel = self.history_tree.selection()
        if not sel:
            messagebox.showwarning("Увага", "Виберіть заявку в списку.")
            return
        self._cancel_order_for_order(int(sel[0]))

    def _cancel_order_for_order(self, order_id, refresh_dialog_callback=None):
        order = db.get_order(order_id)
        if not order:
            return

        has_active_ttn = bool(order.get("ttn")) and order.get("ttn_status") != "cancelled"
        extra_warning = (" Перед видаленням буде автоматично скасовано її ТТН."
                          if has_active_ttn else "")
        confirm = messagebox.askyesno(
            "Видалити заявку?",
            f"Видалити заявку №{order['order_number']} (створена помилково)?"
            f"{extra_warning}\n\n"
            f"Це остаточно — заявку і її товарні рядки буде видалено з "
            f"історії без можливості відновлення. Номер {order['order_number']} "
            f"після цього можна буде використати повторно."
        )
        if not confirm:
            return

        self.config(cursor="watch")
        self.update_idletasks()
        ttn_note = ""
        if has_active_ttn:
            ok, err = self._perform_ttn_cancel(order)
            if ok:
                ttn_note = f"\nТТН №{order['ttn']} також скасовано."
            else:
                ttn_note = (f"\n\nУвага: ТТН скасувати не вдалось ({err}). "
                            f"Перевірте вручну на сайті перевізника — заявку "
                            f"все одно буде видалено з історії.")
        db.delete_order(order_id)
        self.config(cursor="")
        messagebox.showinfo("Готово", f"Заявку №{order['order_number']} видалено.{ttn_note}")
        self._refresh_history()
        if refresh_dialog_callback:
            refresh_dialog_callback()

    @staticmethod
    def _open_file_externally(path):
        """Відкриває файл програмою за замовчуванням у Windows/macOS/Linux."""
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
            return True
        except Exception as e:
            messagebox.showerror("Не вдалось відкрити файл", str(e))
            return False

    def _open_order_details_from_selection(self):
        sel = self.history_tree.selection()
        if not sel:
            messagebox.showwarning("Увага", "Виберіть заявку в списку.")
            return
        self._open_order_details(int(sel[0]))

    def _open_order_details(self, order_id):
        order = db.get_order(order_id)
        if not order:
            return
        items = db.get_order_items(order_id)

        win = tk.Toplevel(self)
        win.title(f"Заявка № {order['order_number']}")
        win.configure(bg=COLOR_BG)
        win.transient(self)

        wrap = tk.Frame(win, bg=COLOR_BG, padx=16, pady=16)
        wrap.pack(fill="both", expand=True)

        title_row = tk.Frame(wrap, bg=COLOR_BG)
        title_row.pack(fill="x", pady=(0, 10))
        tk.Label(title_row, text=f"Заявка № {order['order_number']} від "
                                  f"{(order['order_date'] or '')[:10]}",
                 font=FONT_BOLD, bg=COLOR_BG, fg=COLOR_TEXT).pack(side="left", anchor="w")
        if order.get("order_status") == "cancelled":
            tk.Label(title_row, text="ЗАЯВКУ СКАСОВАНО", font=FONT_BOLD, bg=COLOR_BG,
                     fg="#C0392B").pack(side="left", padx=(14, 0))
        else:
            def cancel_order_and_refresh():
                self._cancel_order_for_order(order_id, refresh_dialog_callback=lambda: win.destroy())
            tk.Button(title_row, text="Видалити заявку", font=FONT_SMALL, bg="#E5A3A3", fg="white",
                      relief="flat", padx=10, pady=4, cursor="hand2",
                      command=cancel_order_and_refresh).pack(side="right")

        info_frame = tk.Frame(wrap, bg=COLOR_BG)
        info_frame.pack(fill="x")

        left_info = tk.Frame(info_frame, bg=COLOR_BG)
        left_info.pack(side="left", fill="both", expand=True, anchor="n")
        right_info = tk.Frame(info_frame, bg=COLOR_BG)
        right_info.pack(side="left", fill="both", expand=True, padx=(24, 0), anchor="n")

        def add_row(parent_frame, row_idx, label, value):
            tk.Label(parent_frame, text=label, font=FONT_SMALL, bg=COLOR_BG,
                     fg=COLOR_TEXT_MUTED).grid(row=row_idx, column=0, sticky="w", pady=2)
            tk.Label(parent_frame, text=value or "—", font=FONT, bg=COLOR_BG,
                     fg=COLOR_TEXT, wraplength=280, justify="left").grid(
                row=row_idx, column=1, sticky="w", padx=(8, 0), pady=2)

        add_row(left_info, 0, "Відповідальний:", order.get("responsible"))
        add_row(left_info, 1, "Спосіб оплати:", order.get("payment_method"))
        add_row(left_info, 2, "Телефон відправника:", order.get("sender_phone"))
        add_row(left_info, 3, "Ім'я відправника:", order.get("sender_name"))
        add_row(left_info, 4, "Відділення відправника:", order.get("sender_warehouse_number"))
        add_row(left_info, 5, "Покупець:", order.get("buyer_name"))

        recipient_type_display = "Юридична особа" if order.get("recipient_type") == "legal" else "Фізична особа"
        add_row(right_info, 0, "Одержувач:", order.get("recipient_name"))
        add_row(right_info, 1, "Тип одержувача:", recipient_type_display)
        if order.get("recipient_type") == "legal":
            add_row(right_info, 2, "ЄДРПОУ:", order.get("recipient_edrpou"))
        add_row(right_info, 3, "Телефон одержувача:", order.get("recipient_phone"))
        add_row(right_info, 4, "Перевізник:", order.get("carrier"))
        addr_bits = [order.get("recipient_oblast"), order.get("recipient_city")]
        if order.get("delivery_type") == "branch":
            addr_bits.append(f"відділення №{order.get('carrier_branch')}" if order.get("carrier_branch") else None)
        else:
            addr_bits.append(order.get("street"))
        add_row(right_info, 5, "Адреса:", ", ".join(b for b in addr_bits if b))

        # -- товари --
        tk.Label(wrap, text="Товари", font=FONT_BOLD, bg=COLOR_BG, fg=COLOR_TEXT).pack(
            anchor="w", pady=(14, 4))
        cols = ("code", "name", "unit", "qty", "price", "sum")
        headers = ["Код", "Найменування", "Од.вим", "К-сть", "Ціна", "Сума"]
        items_tree = ttk.Treeview(wrap, columns=cols, show="headings", height=min(8, max(3, len(items))))
        for c, h in zip(cols, headers):
            items_tree.heading(c, text=h)
            items_tree.column(c, width=100, anchor="center")
        items_tree.column("name", width=220, anchor="w")
        for it in items:
            items_tree.insert("", "end", values=(
                it.get("code"), it.get("name"), it.get("unit"), it.get("qty"),
                it.get("price"), it.get("sum")
            ))
        items_tree.pack(fill="x")

        totals_text = f"Разом: {order.get('total_sum') or 0:.2f} грн, {order.get('total_weight') or 0:.2f} кг"
        tk.Label(wrap, text=totals_text, font=FONT_BOLD, bg=COLOR_BG, fg=COLOR_TEXT).pack(
            anchor="e", pady=(4, 0))

        # -- ТТН --
        ttn_frame = tk.LabelFrame(wrap, text="ТТН", font=FONT_SMALL, bg=COLOR_BG,
                                   fg=COLOR_TEXT_MUTED, padx=12, pady=10)
        ttn_frame.pack(fill="x", pady=(14, 0))

        if order.get("ttn"):
            ttn_status_text = {
                "created": "створено",
                "cancelled": "скасовано",
                "failed": "не вдалось створити",
            }.get(order.get("ttn_status"), order.get("ttn_status") or "")
            tk.Label(ttn_frame, text=f"№ {order['ttn']} ({ttn_status_text})",
                     font=FONT_BOLD, bg=COLOR_BG, fg=COLOR_ACCENT_DARK).pack(anchor="w")
            if order.get("tracking_status"):
                tk.Label(ttn_frame, text=f"Статус доставки: {order['tracking_status']}",
                         font=FONT_SMALL, bg=COLOR_BG, fg=COLOR_TEXT_MUTED).pack(anchor="w", pady=(2, 0))

            btns = tk.Frame(ttn_frame, bg=COLOR_BG)
            btns.pack(anchor="w", pady=(8, 0))

            def download_pdf():
                pdf_path = order.get("ttn_pdf_path")
                if pdf_path and os.path.exists(pdf_path):
                    self._open_file_externally(pdf_path)
                    return
                sender = db.get_sender(order.get("payment_method") or "")
                if not sender or sender.get("carrier") != order.get("carrier") or not sender.get("api_key"):
                    messagebox.showerror("Не вдалось", "Немає доступного API-ключа для цього "
                                          "відправника, щоб довантажити бланк.")
                    return
                self.config(cursor="watch")
                self.update_idletasks()
                try:
                    pdf_bytes = carriers.fetch_ttn_pdf(order.get("ttn_ref"), sender["api_key"])
                    pdf_name = order["file_name"].rsplit(".", 1)[0] + "_ттн.pdf"
                    new_path = os.path.join(OUTPUT_DIR, pdf_name)
                    with open(new_path, "wb") as f:
                        f.write(pdf_bytes)
                    db.set_order_ttn_pdf_path(order_id, new_path)
                    order["ttn_pdf_path"] = new_path
                    self._open_file_externally(new_path)
                except carriers.CarrierAPIError as e:
                    messagebox.showerror("Не вдалось завантажити бланк", str(e))
                finally:
                    self.config(cursor="")

            tk.Button(btns, text="Відкрити бланк ТТН (PDF)", font=FONT_SMALL,
                      bg=COLOR_ACCENT, fg="white", relief="flat", padx=10, pady=4,
                      cursor="hand2", command=download_pdf).pack(side="left")

            if order.get("ttn_status") != "cancelled":
                def cancel_and_refresh():
                    self._cancel_ttn_for_order(order_id, refresh_dialog_callback=lambda: win.destroy())
                tk.Button(btns, text="Скасувати ТТН", font=FONT_SMALL, bg="#FBE1E1", fg=COLOR_TEXT,
                          relief="flat", padx=10, pady=4, cursor="hand2",
                          command=cancel_and_refresh).pack(side="left", padx=8)
        else:
            reason = order.get("ttn_error") or "ТТН не створювався для цієї заявки."
            tk.Label(ttn_frame, text=reason, font=FONT_SMALL, bg=COLOR_BG,
                     fg=COLOR_TEXT_MUTED, wraplength=500, justify="left").pack(anchor="w")

        # -- файл заявки --
        file_btns = tk.Frame(wrap, bg=COLOR_BG)
        file_btns.pack(fill="x", pady=(14, 0))
        order_file_path = os.path.join(OUTPUT_DIR, order["file_name"])
        tk.Button(file_btns, text="Відкрити файл заявки (Excel)", font=FONT_BOLD,
                  bg=COLOR_ACCENT, fg="white", activebackground=COLOR_ACCENT_DARK,
                  activeforeground="white", relief="flat", padx=14, pady=8,
                  cursor="hand2",
                  command=lambda: self._open_file_externally(order_file_path)
                  if os.path.exists(order_file_path) else
                  messagebox.showerror("Не знайдено", "Файл заявки не знайдено на диску.")
                  ).pack(side="left")

        win.update_idletasks()
        req_w = max(win.winfo_reqwidth(), 620)
        req_h = win.winfo_reqheight()
        x = self.winfo_rootx() + (self.winfo_width() - req_w) // 2
        y = self.winfo_rooty() + (self.winfo_height() - req_h) // 2
        win.geometry(f"{req_w}x{req_h}+{max(x, 0)}+{max(y, 0)}")

    # ------------------------------------------------------------------
    # "Клієнти"
    # ------------------------------------------------------------------
    def _build_clients_view(self):
        parent = tk.Frame(self.content)
        self.views["clients"] = parent

        header_row = tk.Frame(parent)
        header_row.pack(fill="x", padx=14, pady=(14, 6))
        tk.Label(header_row, text="База клієнтів", font=FONT_TITLE).pack(side="left")
        tk.Button(header_row, text="Експортувати в Excel", font=FONT, bg=COLOR_ACCENT,
                  fg="white", activebackground=COLOR_ACCENT_DARK, activeforeground="white",
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  command=self._export_clients).pack(side="right")
        tk.Button(header_row, text="Оновити", font=FONT,
                  command=self._refresh_clients).pack(side="right", padx=8)

        cols = ("name", "phone", "oblast", "city", "address", "carrier", "branch")
        headers = ["ПІБ", "Телефон", "Область", "Місто", "Адреса", "Перевізник", "Відділення"]
        self.clients_tree = ttk.Treeview(parent, columns=cols, show="headings")
        for c, h in zip(cols, headers):
            self.clients_tree.heading(c, text=h)
            self.clients_tree.column(c, width=120, anchor="center")
        self.clients_tree.column("name", width=200, anchor="w")
        self.clients_tree.column("address", width=200, anchor="w")
        self.clients_tree.pack(fill="both", expand=True, padx=14, pady=10)

        self._clients_count_label = tk.Label(parent, text="", font=FONT_SMALL, fg=COLOR_TEXT_MUTED)
        self._clients_count_label.pack(anchor="w", padx=14, pady=(0, 10))

    def _refresh_clients(self):
        self.clients_tree.delete(*self.clients_tree.get_children())
        clients = db.list_clients()
        for c in clients:
            self.clients_tree.insert("", "end", values=(
                c.get("full_name") or "", c.get("phone") or "", c.get("oblast") or "",
                c.get("city") or "", c.get("address") or "", c.get("carrier") or "",
                c.get("carrier_branch") or ""
            ))
        self._clients_count_label.configure(text=f"Усього клієнтів: {len(clients)}")

    def _export_clients(self):
        clients = db.list_clients()
        if not clients:
            messagebox.showinfo("Немає даних", "База клієнтів поки порожня.")
            return
        path = filedialog.asksaveasfilename(
            title="Зберегти базу клієнтів", defaultextension=".xlsx",
            initialfile="клієнти.xlsx",
            filetypes=[("Excel files", "*.xlsx")]
        )
        if not path:
            return
        headers = ["ПІБ", "Телефон", "Область", "Місто", "Адреса", "Перевізник", "Відділення"]
        rows = [(c.get("full_name") or "", c.get("phone") or "", c.get("oblast") or "",
                 c.get("city") or "", c.get("address") or "", c.get("carrier") or "",
                 c.get("carrier_branch") or "") for c in clients]
        reports.export_table_to_excel(headers, rows, "База клієнтів", path)
        messagebox.showinfo("Готово", f"Базу клієнтів збережено:\n{path}")

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
                  command=lambda: self._copy_report(key)).pack(side="left", padx=(0, 8))
        toggle_btn = tk.Button(filter_frame, text="Графік", font=FONT, bg=COLOR_ACCENT, fg="white",
                                activebackground=COLOR_ACCENT_DARK, activeforeground="white",
                                relief="flat", padx=10, pady=4, cursor="hand2",
                                command=lambda: self._toggle_report_view(key))
        toggle_btn.pack(side="left")

        # -- таблиця й графік більше не тісняться поруч: показуємо по черзі
        # на весь доступний простір, перемикаючись кнопкою "Графік" вище --
        body = tk.Frame(parent)
        body.pack(fill="both", expand=True, padx=14, pady=8)

        table_frame = tk.Frame(body)
        tree = ttk.Treeview(table_frame, show="headings", height=16)
        tree.pack(fill="both", expand=True)
        table_frame.pack(side="left", fill="both", expand=True)

        chart_frame = tk.Frame(body)

        summary_label = tk.Label(parent, text="", font=FONT_BOLD, anchor="w", justify="left")
        summary_label.pack(fill="x", padx=14, pady=(0, 10))

        # зберігаємо посилання на віджети та поточні дані звіту для цієї вкладки
        parent.date_from_var = date_from_var
        parent.date_to_var = date_to_var
        parent.tree = tree
        parent.table_frame = table_frame
        parent.chart_frame = chart_frame
        parent.toggle_btn = toggle_btn
        parent.view_mode = "table"
        parent.summary_label = summary_label
        parent.current_headers = []
        parent.current_rows = []
        parent.canvas = None

    def _toggle_report_view(self, key):
        view = self.views[key]
        if view.view_mode == "table":
            view.table_frame.pack_forget()
            view.chart_frame.pack(side="left", fill="both", expand=True)
            view.view_mode = "chart"
            view.toggle_btn.configure(text="Таблиця")
        else:
            view.chart_frame.pack_forget()
            view.table_frame.pack(side="left", fill="both", expand=True)
            view.view_mode = "table"
            view.toggle_btn.configure(text="Графік")

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
            fig = Figure(figsize=(9.5, 5.5), dpi=100)
            ax = fig.add_subplot(111)
            if ts:
                days = [r["day"][5:] for r in ts]
                sums = [r["total_sum"] for r in ts]
                ax.bar(days, sums, color="#2e7d32")
                ax.set_title("Сума продажів по днях", fontsize=13)
                ax.tick_params(axis="x", labelrotation=90, labelsize=9)
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
            fig = Figure(figsize=(9.5, 5.5), dpi=100)
            ax = fig.add_subplot(111)
            top = data[:10]
            if top:
                names = [d["product_name"][:14] for d in top][::-1]
                sums = [d["total_sum"] for d in top][::-1]
                ax.barh(names, sums, color="#1565c0")
                ax.set_title("Топ-10 товарів за сумою", fontsize=13)
                ax.tick_params(axis="y", labelsize=9)
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
            fig = Figure(figsize=(9.5, 5.5), dpi=100)
            ax = fig.add_subplot(111)
            top = data[:10]
            if top:
                names = [d["buyer_name"][:14] for d in top][::-1]
                sums = [d["total_sum"] for d in top][::-1]
                ax.barh(names, sums, color="#6a1b9a")
                ax.set_title("Топ-10 клієнтів за сумою", fontsize=13)
                ax.tick_params(axis="y", labelsize=9)
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
            fig = Figure(figsize=(9.5, 5.5), dpi=100)
            ax = fig.add_subplot(111)
            top = data[:10]
            if top:
                labels = [f"{d['oblast'][:10]}/{d['city'][:10]}" for d in top][::-1]
                sums = [d["total_sum"] for d in top][::-1]
                ax.barh(labels, sums, color="#ef6c00")
                ax.set_title("Топ-10 напрямків доставки", fontsize=13)
                ax.tick_params(axis="y", labelsize=9)
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
            fig = Figure(figsize=(9.5, 5.5), dpi=100)
            ax = fig.add_subplot(111)
            if data:
                labels = [d["carrier"] for d in data]
                sums = [d["total_sum"] for d in data]
                ax.pie(sums, labels=labels, autopct="%1.0f%%", textprops={"fontsize": 10})
                ax.set_title("Розподіл продажів по перевізниках", fontsize=13)
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
            fig = Figure(figsize=(9.5, 5.5), dpi=100)
            ax = fig.add_subplot(111)
            if data:
                days = [d["day"][5:] for d in data]
                sums = [d["total_sum"] for d in data]
                ax.plot(days, sums, marker="o", color="#c62828")
                ax.set_title("Динаміка суми продажів", fontsize=13)
                ax.tick_params(axis="x", labelrotation=90, labelsize=9)
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
    enable_windows_dpi_awareness()
    app = App()
    app.mainloop()
