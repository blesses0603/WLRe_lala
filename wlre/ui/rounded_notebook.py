"""Notebook page management with a separate row of real rounded tab buttons."""
from tkinter import ttk


class RoundedNotebook(ttk.Frame):
    def __init__(self, parent, borderless=True, **kwargs):
        super().__init__(parent, **kwargs)
        style = ttk.Style(self)
        style.configure('PillBody.TNotebook', borderwidth=0, tabmargins=0)
        style.layout('PillBody.TNotebook.Tab', [])
        style.configure('Pill.Tab.TButton', padding=(12, 6))
        style.map('Pill.Tab.TButton', foreground=[('selected', '#ffffff')])
        self.bar = ttk.Frame(self, padding=(0, 2, 0, 6))
        self.bar.pack(fill='x')
        body_style='FlatPillBody.TNotebook' if borderless else 'PillBody.TNotebook'
        if borderless:
            style.layout(body_style, [])
            style.layout(body_style+'.Tab', [])
            style.configure(body_style,borderwidth=0,tabmargins=0)
        self.book = ttk.Notebook(self, style=body_style)
        self.book.pack(fill='both', expand=True)
        self.buttons = {}
        self.book.bind('<<NotebookTabChanged>>', self._changed)
        self.book.enable_traversal()

    def add(self, child, **kwargs):
        self.book.add(child, **kwargs)
        self._rebuild()

    def insert(self, pos, child, **kwargs):
        self.book.insert(pos, child, **kwargs)
        self._rebuild()

    def forget(self, tab):
        self.book.forget(tab)
        self._rebuild()

    def hide(self, tab):
        self.book.hide(tab)
        self._rebuild()

    def tabs(self):
        return self.book.tabs()

    def index(self, tab):
        return self.book.index(tab)

    def tab(self, tab, option=None, **kwargs):
        result = self.book.tab(tab, option, **kwargs)
        if kwargs:
            self._rebuild()
        return result

    def select(self, tab=None):
        if tab is None:
            return self.book.select()
        self.book.select(tab)
        self._sync()

    def _rebuild(self):
        for button in self.buttons.values():
            button.destroy()
        self.buttons = {}
        for page in self.book.tabs():
            options = self.book.tab(page)
            if options['state'] == 'hidden':
                continue
            button = ttk.Button(self.bar, text=options['text'], style='Pill.Tab.TButton',
                                command=lambda p=page: self.select(p), takefocus=True, width=0)
            button.pack(side='left', padx=(0, 6))
            if options['state'] == 'disabled':
                button.state(['disabled'])
            button.bind('<Right>', lambda event, p=page: self._step(p, 1))
            button.bind('<Left>', lambda event, p=page: self._step(p, -1))
            self.buttons[page] = button
        self._sync()

    def _step(self, page, direction):
        enabled = [p for p in self.buttons if self.book.tab(p, 'state') != 'disabled']
        if enabled:
            target = enabled[(enabled.index(page) + direction) % len(enabled)]
            self.select(target)
            self.buttons[target].focus_set()
        return 'break'

    def _sync(self):
        selected = self.book.select()
        for page, button in self.buttons.items():
            button.state(['selected'] if page == selected else ['!selected'])

    def _changed(self, event):
        self._sync()
        self.event_generate('<<NotebookTabChanged>>')
