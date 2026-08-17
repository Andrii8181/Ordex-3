# -*- coding: utf-8 -*-
"""
main.py — головне вікно програми ведення заявок ЧСМ.
Запуск: python3 main.py
"""
import os
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
    Повертає абсолютний шлях до файлу ресурсу (наприклад, іконки),
    коректно як при звичайному запуску python main.py, так і всередині
    зібраного PyInstaller-ом .exe (--onefile розпаковує дані у тимчасову
    папку, шлях до якої лежить у sys._MEIPASS).
    """
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, *parts)


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

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orders")

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

        self.selected_client = None
        self.current_items = []
        self._selected_product = None

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

    # ------------------------------------------------------------------
    # Верхня панель: Файл / Налаштування / Звіти
    # ------------------------------------------------------------------
    def _build_topbar(self):
        topbar = tk.Frame(self, bg=COLOR_TOPBAR, height=48)
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
                # 256px джерело -> ~29px у топбарі (subsample приймає лише цілий коефіцієнт)
                self._logo_img = img.subsample(9, 9)
                tk.Label(brand, image=self._logo_img, bg=COLOR_TOPBAR).pack(side="left")
            except tk.TclError:
                pass
        tk.Label(brand, text="Ordex", bg=COLOR_TOPBAR, fg="white",
                 font=("Segoe UI", 15, "bold")).pack(side="left", padx=(8, 0))

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

        # -- місто/відділення відправника: потрібні для будь-якого перевізника --
        common_frame = tk.Frame(form, bg=COLOR_BG)
        common_frame.grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))

        tk.Label(common_frame, text="Місто відправника:", bg=COLOR_BG, font=FONT).grid(
            row=0, column=0, sticky="w", pady=3)
        sender_city_var = tk.StringVar()
        tk.Entry(common_frame, textvariable=sender_city_var, width=22, font=FONT).grid(
            row=0, column=1, sticky="w", padx=(8, 0), pady=3)

        tk.Label(common_frame, text="№ відділення відправника:", bg=COLOR_BG, font=FONT).grid(
            row=1, column=0, sticky="w", pady=3)
        sender_warehouse_var = tk.StringVar()
        tk.Entry(common_frame, textvariable=sender_warehouse_var, width=22, font=FONT).grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=3)

        # -- API-ключ і Ref-и: наразі є лише для Нової Пошти --
        np_frame = tk.Frame(form, bg=COLOR_BG)
        np_frame.grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 0))

        tk.Label(np_frame, text="API-ключ:", bg=COLOR_BG, font=FONT).grid(
            row=0, column=0, sticky="w", pady=3)
        api_key_var = tk.StringVar()
        api_key_entry = tk.Entry(np_frame, textvariable=api_key_var, width=22, font=FONT, show="•")
        api_key_entry.grid(row=0, column=1, sticky="w", padx=(8, 0), pady=3)
        show_key_var = tk.BooleanVar(value=False)
        tk.Checkbutton(np_frame, text="показати", variable=show_key_var, bg=COLOR_BG,
                        font=FONT_SMALL,
                        command=lambda: api_key_entry.configure(
                            show="" if show_key_var.get() else "•")
                        ).grid(row=0, column=2, sticky="w", padx=(6, 0))

        tk.Label(np_frame, text="Ref контрагента-відправника:", bg=COLOR_BG, font=FONT).grid(
            row=1, column=0, sticky="w", pady=3)
        sender_cp_ref_var = tk.StringVar()
        tk.Entry(np_frame, textvariable=sender_cp_ref_var, width=22, font=FONT).grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=3)

        tk.Label(np_frame, text="Ref контактної особи відправника:", bg=COLOR_BG, font=FONT).grid(
            row=2, column=0, sticky="w", pady=3)
        sender_contact_ref_var = tk.StringVar()
        tk.Entry(np_frame, textvariable=sender_contact_ref_var, width=22, font=FONT).grid(
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
            sender_warehouse_var.set(extra.get("sender_warehouse") or "")
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
            sender_warehouse_var.set("")
            sender_cp_ref_var.set("")
            sender_contact_ref_var.set("")
            update_carrier_fields()

        def save_sender():
            if not method_var.get().strip() or not phone_var.get().strip():
                messagebox.showwarning("Увага", "Вкажіть спосіб оплати і телефон.")
                return
            extra = {}
            if carrier_var.get():
                extra = {
                    "sender_city": sender_city_var.get().strip(),
                    "sender_warehouse": sender_warehouse_var.get().strip(),
                }
                if carrier_var.get() == "Нова Пошта":
                    extra["sender_counterparty_ref"] = sender_cp_ref_var.get().strip()
                    extra["sender_contact_ref"] = sender_contact_ref_var.get().strip()
            db.set_sender(method_var.get().strip(), phone_var.get().strip(),
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
        tk.Entry(left, textvariable=self.sender_phone_var, width=32, font=FONT).grid(row=r, column=1, sticky="w")
        r += 1

        tk.Label(left, text="Ім'я відправника (для ТТН):", font=FONT).grid(row=r, column=0, sticky="w", pady=3)
        self.sender_name_var = tk.StringVar()
        tk.Entry(left, textvariable=self.sender_name_var, width=32, font=FONT).grid(row=r, column=1, sticky="w")
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
        r2 += 1

        tk.Label(right, text="Покупець:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        self.buyer_entry = AutocompleteEntry(
            right, search_fn=self._search_clients_fn, on_select=self._on_client_selected,
            width=30, font=FONT
        )
        self.buyer_entry.grid(row=r2, column=1, sticky="w")
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

        tk.Label(right, text="№ ТТН:", font=FONT).grid(row=r2, column=0, sticky="w", pady=3)
        self.ttn_var = tk.StringVar()
        tk.Entry(right, textvariable=self.ttn_var, width=32, font=FONT_BOLD,
                 state="readonly", readonlybackground="white",
                 fg=COLOR_ACCENT_DARK).grid(row=r2, column=1, sticky="w")
        r2 += 1

        self._apply_delivery_state()
        self._update_ttn_availability_hint()

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
        self.item_code_entry = AutocompleteEntry(
            add_frame, search_fn=self._search_products_by_code_fn,
            on_select=self._on_product_code_selected, width=13, font=FONT
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
        btn_row.pack(fill="x", padx=14)
        tk.Button(btn_row, text="Видалити вибраний рядок", font=FONT,
                  command=self._remove_selected_item).pack(side="left")

        self.totals_label = tk.Label(canvas_wrap, text="Разом: 0.00 грн,  0.00 кг", font=FONT_BOLD)
        self.totals_label.pack(anchor="e", padx=14, pady=4)

        tk.Button(canvas_wrap, text="Сформувати заявку", bg=COLOR_ACCENT, fg="white",
                  activebackground=COLOR_ACCENT_DARK, activeforeground="white",
                  font=FONT_BOLD, padx=22, pady=10, command=self._generate_order).pack(pady=14)

        # -- колесо миші прокручує область під курсором: над формою — форму,
        # над таблицею товарів — саму таблицю (вона виключена через skip) --
        self._bind_wheel_deep(canvas_wrap, order_canvas, skip={self.items_tree})

    def _reload_payment_methods(self):
        self.payment_combo["values"] = [s["payment_method"] for s in db.get_senders()]

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
        required = ["sender_city", "sender_warehouse",
                    "sender_counterparty_ref", "sender_contact_ref"]
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
        self.recipient_phone_entry.set(client.get("phone") or "")
        if not self.buyer_entry.get().strip():
            self.buyer_entry.set(client.get("full_name") or "")
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
        sender = db.get_sender(method)
        if sender:
            self.sender_phone_var.set(sender.get("phone") or "")
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
            phone=self.recipient_phone_entry.get().strip() or None,
            oblast=oblast or None,
            city=city or None,
            address=recipient_address or None,
            carrier=carrier or None,
            carrier_branch=self.carrier_branch_var.get().strip() or None,
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
            "sender_phone": self.sender_phone_var.get().strip(),
            "sender_name": self.sender_name_var.get().strip(),
            "recipient_phone": self.recipient_phone_entry.get().strip(),
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
            "payer_type": self.payer_type_var.get(),
            "seats_amount": seats_amount,
            "cod_amount": cod_amount,
            "total_sum": round(sum(i["sum"] for i in self.current_items), 2),
            "total_weight": round(sum(i["weight_total"] for i in self.current_items), 2),
            "client_id": client_id,
        }

        items_for_export = []
        for i, it in enumerate(self.current_items, start=1):
            row = dict(it)
            row["seq_no"] = i
            items_for_export.append(row)

        # -- автоматичне створення ТТН (якщо увімкнено і перевізник підтримується) --
        header["ttn"] = None
        header["ttn_status"] = None
        header["ttn_error"] = None
        self.ttn_var.set("")
        if self.auto_ttn_var.get() and carrier != "Самовивіз":
            sender = db.get_sender(self.payment_var.get().strip())
            if sender and sender.get("carrier") == carrier:
                credentials = {"api_key": sender.get("api_key"), "extra": sender.get("extra") or {}}
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
                header["ttn_status"] = "created"
                self.ttn_var.set(result["ttn"])
            except carriers.CarrierAPIError as e:
                header["ttn_status"] = "failed"
                header["ttn_error"] = str(e)
                messagebox.showwarning(
                    "ТТН не створено",
                    f"Заявку буде сформовано без ТТН. Причина:\n\n{e}\n\n"
                    f"Ви можете створити ТТН вручну на сайті перевізника і "
                    f"пізніше повернутись до цього."
                )
            finally:
                self.config(cursor="")

        filename = order_export.build_filename(buyer_name, order_date, header["order_number"])
        output_path = os.path.join(OUTPUT_DIR, filename)
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
        self.carrier_branch_var.set("")
        self.street_var.set("")
        self.building_var.set("")
        self.apartment_var.set("")
        self.oblast_entry.set("")
        self.city_entry.set("")
        self.recipient_name_var.set("")
        self.payer_type_var.set("recipient")
        self.seats_amount_var.set("1")
        self.cod_enabled_var.set(False)
        self.cod_amount_var.set("")
        self.cod_amount_entry.configure(state="disabled")
        self.ttn_var.set("")
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
            self.history_tree.heading(c, text=h)
            self.history_tree.column(c, width=110, anchor="center")
        self.history_tree.column("buyer", width=190, anchor="w")
        self.history_tree.column("ttn", width=130, anchor="center")
        self.history_tree.column("status", width=200, anchor="w")

        self.history_tree.tag_configure("delivered", background="#DCF3E6")
        self.history_tree.tag_configure("in_transit", background="#FFF6DA")
        self.history_tree.tag_configure("ttn_failed", background="#FBE1E1")
        self.history_tree.tag_configure("no_ttn", background=COLOR_CARD)

        self.history_tree.pack(fill="both", expand=True, padx=14, pady=10)

        tk.Button(parent, text="Оновити список", font=FONT, command=self._refresh_history).pack(pady=4)

    def _refresh_history(self):
        self.history_tree.delete(*self.history_tree.get_children())
        for o in db.list_orders():
            ttn_display = o.get("ttn") or ("не створено" if o.get("ttn_status") == "failed" else "")
            status_display = o.get("tracking_status") or ""

            if o.get("ttn_status") == "failed" and not o.get("ttn"):
                tag = "ttn_failed"
            elif o.get("tracking_delivered"):
                tag = "delivered"
            elif o.get("ttn") and status_display:
                tag = "in_transit"
            else:
                tag = "no_ttn"

            self.history_tree.insert("", "end", values=(
                o["order_number"], o["order_date"][:10] if o["order_date"] else "",
                o["buyer_name"], o["total_sum"], o["total_weight"], ttn_display,
                status_display, o["file_name"]
            ), tags=(tag,))

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
    enable_windows_dpi_awareness()
    app = App()
    app.mainloop()
