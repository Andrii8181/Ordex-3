# -*- coding: utf-8 -*-
"""
autocomplete.py — поле вводу Tkinter з випадаючим списком підказок,
що оновлюється під час набору тексту.
"""
import tkinter as tk


class AutocompleteEntry(tk.Frame):
    """
    search_fn(text) -> список кортежів (label, payload)
        label — те, що показується у випадному списку
        payload — довільний об'єкт, який повертається через on_select
    on_select(label, payload) — викликається при виборі варіанту
    """

    def __init__(self, master, search_fn, on_select=None, width=30, **kwargs):
        super().__init__(master)
        self.search_fn = search_fn
        self.on_select = on_select

        self.var = tk.StringVar()
        self.entry = tk.Entry(self, textvariable=self.var, width=width, **kwargs)
        self.entry.pack(fill="x")

        self.listbox = None
        self._suppress = False

        self.var.trace_add("write", self._on_text_changed)
        self.entry.bind("<Down>", self._focus_listbox)
        self.entry.bind("<Escape>", lambda e: self._hide_list())
        self.entry.bind("<FocusOut>", lambda e: self.after(150, self._hide_list))

    def get(self):
        return self.var.get()

    def set(self, text):
        self._suppress = True
        self.var.set(text)
        self._suppress = False
        self._hide_list()

    def _on_text_changed(self, *args):
        if self._suppress:
            return
        text = self.var.get()
        if not text.strip():
            self._hide_list()
            return
        results = self.search_fn(text)
        if not results:
            self._hide_list()
            return
        self._show_list(results)

    def _show_list(self, results):
        self._results = results
        if self.listbox is None:
            self.listbox = tk.Listbox(self, height=min(6, len(results)))
            self.listbox.bind("<<ListboxSelect>>", self._on_pick)
            self.listbox.bind("<Return>", self._on_pick)
        self.listbox.delete(0, tk.END)
        for label, _payload in results:
            self.listbox.insert(tk.END, label)
        self.listbox.place(x=0, y=self.entry.winfo_height(),
                            width=self.entry.winfo_reqwidth() or 200)
        self.listbox.lift()

    def _hide_list(self):
        if self.listbox is not None:
            self.listbox.place_forget()

    def _focus_listbox(self, event):
        if self.listbox is not None and self.listbox.winfo_ismapped():
            self.listbox.focus_set()
            self.listbox.selection_set(0)

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
