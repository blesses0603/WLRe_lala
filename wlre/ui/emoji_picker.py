"""Single, responsive list of verified game emoji; selection only inserts text."""
import math
import tkinter as tk
from tkinter import ttk

from wlre.ui.window_layout import configure_dialog


class EmojiPicker(tk.Toplevel):
    def __init__(self, parent, images, on_select):
        super().__init__(parent)
        self.title('遊戲表情')
        self.buttons = []
        self._columns = 0
        rows = [int(key) for key, entry in images.catalog.items()
                if entry.get('show_in_list', True) and entry.get('available', True)]
        box = ttk.Frame(self, padding=8)
        box.pack(fill='both', expand=True)
        ttk.Label(box, text=(f'共 {len(rows)} 個表情 · 點選插入輸入框'
                            if rows else '官方表情尚未就緒；聊天仍可使用文字'),
                  wraplength=400).pack(side='bottom', fill='x', pady=(6, 0))
        viewport = ttk.Frame(box)
        viewport.pack(fill='both', expand=True)
        background = ttk.Style(self).lookup('TFrame', 'background') or self.cget('background')
        self.canvas = tk.Canvas(viewport, background=background, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(viewport, orient='vertical', command=self.canvas.yview)
        self.scrollbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.grid_frame = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window(0, 0, window=self.grid_frame, anchor='nw')
        for index in rows:
            token = f'[Emoji{index}]'
            picture = images.get(token, 40)
            button = ttk.Button(self.grid_frame, text=str(index), image=picture,
                                compound='top', width=4,
                                command=lambda value=token: on_select(value))
            button.emoji_token = token
            # Keep image references alive even when the source cache is refreshed.
            button.emoji_image = picture
            button.bind('<FocusIn>', self._show_focused)
            self.buttons.append(button)
        self.update_idletasks()
        self._cell_width = max([button.winfo_reqwidth() + 8 for button in self.buttons] or [60])
        self._cell_height = max([button.winfo_reqheight() + 8 for button in self.buttons] or [68])
        width = max(600, self._cell_width * 8 + 40)
        height = max(260, math.ceil(len(rows) / 8) * self._cell_height + 60)
        configure_dialog(self, width, height)
        # Unlike fixed dialogs, this list can shrink/reflow on small displays.
        self.maxsize(self.winfo_screenwidth(), self.winfo_screenheight())
        self.minsize(min(240, self.winfo_screenwidth()), min(180, self.winfo_screenheight()))
        self.resizable(True, True)
        self.canvas.bind('<Configure>', self._layout)
        self.grid_frame.bind('<Configure>', self._update_scrollregion)
        self.bind('<MouseWheel>', self._wheel)
        self.bind('<Button-4>', lambda event: self._scroll(-1))
        self.bind('<Button-5>', lambda event: self._scroll(1))
        self.bind('<Escape>', lambda event: self.destroy())

    def _layout(self, event):
        width = max(1, event.width)
        columns = max(1, width // self._cell_width)
        self.canvas.itemconfigure(self._window, width=width)
        if columns != self._columns:
            for column in range(self._columns):
                self.grid_frame.columnconfigure(column, weight=0, uniform='', minsize=0)
            for column in range(columns):
                self.grid_frame.columnconfigure(column, weight=1, uniform='emoji')
            for position, button in enumerate(self.buttons):
                button.grid(row=position // columns, column=position % columns,
                            padx=4, pady=4, sticky='nsew')
            self._columns = columns

    def _update_scrollregion(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def _scroll(self, units):
        self.canvas.yview_scroll(units, 'units')
        return 'break'

    def _wheel(self, event):
        if not event.delta:
            return None
        return self._scroll(-max(1, abs(event.delta) // 120) if event.delta > 0
                            else max(1, abs(event.delta) // 120))

    def _show_focused(self, event):
        self.update_idletasks()
        top = event.widget.winfo_y()
        bottom = top + event.widget.winfo_height()
        visible_top = self.canvas.canvasy(0)
        height = self.canvas.winfo_height()
        total = max(1, self.grid_frame.winfo_height())
        if top < visible_top:
            self.canvas.yview_moveto(top / total)
        elif bottom > visible_top + height:
            self.canvas.yview_moveto((bottom - height) / total)
