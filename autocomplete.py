# -*- coding: utf-8 -*-
"""
autocomplete.py — поле вводу Tkinter з випадаючим списком підказок,
що оновлюється під час набору тексту.

Список підказок показується в окремому маленькому вікні (Toplevel)
поверх програми — так він ніколи не "обрізається" батьківським
контейнером (у попередній версії підказки на базі Listbox всередині
Frame фактично малювались, але були невидимі через обрізання
областю батьківського віджета).
"""
import tkinter as tk
import tkinter.font as tkfont


class AutocompleteEntry(tk.Frame):
    """
    search_fn(text) -> список кортежів (label, payload)
        label — те, що показується у випадному списку
        payload — довільний об'єкт, який повертається через on_select
    on_select(label, payload) — викликається при виборі варіанту
    """

    def __init__(self, master, search_fn, on_select=None, width=30, font=None, **kwargs):
        super().__init__(master)
        self.search_fn = search_fn
        self.on_select = on_select
        self._font = font

        self.var = tk.StringVar()
        self.entry = tk.Entry(self, textvariable=self.var, width=width,
                               font=font, **kwargs)
        self.entry.pack(fill="both", expand=True)

        self.popup = None
        self.listbox = None
        self._suppress = False
        self._results = []

        self.var.trace_add("write", self._on_text_changed)
        self.entry.bind("<Down>", self._focus_listbox)
        self.entry.bind("<Escape>", lambda e: self._hide_list())
        self.entry.bind("<FocusOut>", lambda e: self.after(150, self._hide_list))
        self.entry.bind("<Return>", self._on_entry_return)
        self.bind("<Destroy>", lambda e: self._hide_list())

    def get(self):
        return self.var.get()

    def set(self, text):
        self._suppress = True
        self.var.set(text)
        self._suppress = False
        self._hide_list()

    def set_state(self, state):
        """Вмикає/вимикає внутрішнє поле вводу (state='normal'/'disabled')."""
        self.entry.configure(state=state)

    def focus_set_entry(self):
        self.entry.focus_set()

    def _on_text_changed(self, *args):
        if self._suppress:
            return
        text = self.var.get()
        if not text.strip():
            self._hide_list()
            return
        try:
            results = self.search_fn(text)
        except Exception:
            results = []
        if not results:
            self._hide_list()
            return
        self._show_list(results)

    def _show_list(self, results):
        self._results = results
        row_height = min(6, len(results))
        if self.popup is None or not self.popup.winfo_exists():
            self.popup = tk.Toplevel(self)
            self.popup.wm_overrideredirect(True)
            self.popup.attributes("-topmost", True)
            self.listbox = tk.Listbox(self.popup, height=row_height,
                                       font=self._font, activestyle="dotbox",
                                       exportselection=False,
                                       relief="solid", borderwidth=1)
            self.listbox.pack(fill="both", expand=True)
            self.listbox.bind("<ButtonRelease-1>", self._on_pick)
            self.listbox.bind("<Return>", self._on_pick)

        self.listbox.configure(height=row_height)
        self.listbox.delete(0, tk.END)
        for label, _payload in results:
            self.listbox.insert(tk.END, label)

        # -- ширина підказок: підлаштовується під найдовший текст у списку,
        # а не обрізається шириною самого поля вводу (частий випадок для
        # "Назва товару (код)" чи довгих адрес відділень) --
        measure_font = tkfont.Font(font=self._font) if self._font else tkfont.Font()
        longest_px = max((measure_font.measure(label) for label, _ in results), default=0)
        entry_w = self.entry.winfo_width()
        w = min(max(entry_w, longest_px + 36, 220), 560)
        row_px_height = measure_font.metrics("linespace") + 12

        x = self.entry.winfo_rootx()
        y = self.entry.winfo_rooty() + self.entry.winfo_height()
        screen_w = self.winfo_screenwidth()
        if x + w > screen_w:
            x = max(0, screen_w - w)
        self.popup.geometry(f"{w}x{row_height * row_px_height}+{x}+{y}")
        self.popup.deiconify()
        self.popup.lift()

    def _hide_list(self):
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.withdraw()

    def _focus_listbox(self, event):
        if self.popup is not None and self.popup.winfo_ismapped():
            self.listbox.focus_set()
            self.listbox.selection_set(0)

    def _on_entry_return(self, event):
        # Enter в полі вводу підтверджує перший варіант зі списку, якщо він відкритий
        if self.popup is not None and self.popup.winfo_ismapped() and self._results:
            label, payload = self._results[0]
            self.set(label)
            self._hide_list()
            if self.on_select:
                self.on_select(label, payload)

    def _on_pick(self, event):
        if not self.listbox.curselection():
            return
        idx = self.listbox.curselection()[0]
        label, payload = self._results[idx]
        self.set(label)
        self._hide_list()
        self.entry.focus_set()
        if self.on_select:
            self.on_select(label, payload)
