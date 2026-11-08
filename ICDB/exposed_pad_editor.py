"""Optional underside terminal, kept outside the normal lead table."""
import tkinter as tk
from tkinter import ttk
from pinout import ROLES, exposed_pad


class ExposedPadEditor(ttk.Frame):
    def __init__(self, parent, changed):
        super().__init__(parent)
        self.changed = changed
        self.loading = False
        self.enabled = tk.BooleanVar(value=False)
        self.toggle = ttk.Checkbutton(self, text='Exposed pad', variable=self.enabled,
                                      command=self._toggle)
        self.toggle.grid(row=0, column=0, sticky='w', padx=5)
        self.details = ttk.Frame(self)
        self.details.grid(row=1, column=0, sticky='ew')
        self.columnconfigure(0, weight=1)
        self.fields = {}
        for column, (key, label, default, width) in enumerate([
                ('number', 'Identifier', 'EP', 8), ('name', 'Connection / name', '', 20),
                ('role', 'Role', 'Signal', 12)]):
            ttk.Label(self.details, text=label).grid(row=0, column=column, sticky='w', padx=5)
            value = tk.StringVar(value=default)
            self.fields[key] = value
            widget = (ttk.Combobox(self.details, textvariable=value, values=ROLES,
                                   state='readonly', width=width) if key == 'role' else
                      ttk.Entry(self.details, textvariable=value, width=width))
            widget.grid(row=1, column=column, sticky='ew', padx=5, pady=(0,3))
            value.trace_add('write', self._changed)
        self.details.columnconfigure(1, weight=1)
        ttk.Label(self.details, text='Description').grid(row=2, column=0, sticky='w', padx=5)
        self.fields['description'] = tk.StringVar()
        ttk.Entry(self.details, textvariable=self.fields['description']).grid(
            row=2, column=1, columnspan=2, sticky='ew', padx=5, pady=(0,4))
        self.fields['description'].trace_add('write', self._changed)
        self.details.grid_remove()

    def _changed(self, *_):
        if not self.loading:
            self.changed()

    def _toggle(self):
        if self.enabled.get(): self.details.grid()
        else: self.details.grid_remove()
        self._changed()

    def fill(self, data):
        self.loading = True
        try:
            pad = exposed_pad(data)
            self.enabled.set(pad is not None)
            defaults = dict(number='EP', name='', role='Signal', description='')
            for key, value in self.fields.items(): value.set((pad or defaults)[key])
            if pad: self.details.grid()
            else: self.details.grid_remove()
        finally:
            self.loading = False

    def value(self):
        if not self.enabled.get(): return None
        return {key: value.get().strip() for key, value in self.fields.items()}
