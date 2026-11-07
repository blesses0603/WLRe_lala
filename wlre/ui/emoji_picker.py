"""One fitted page of verified emoji, without canvas or scrollbar surfaces."""
import math
import tkinter as tk
from tkinter import ttk
from wlre.ui.window_layout import configure_dialog


def fitted_columns(count, width, height, cell_width, cell_height):
    """Choose a grid that keeps every cell inside the available rectangle."""
    if not count:
        return 1
    candidates = []
    for columns in range(1, count + 1):
        rows = math.ceil(count / columns)
        if columns * cell_width <= width and rows * cell_height <= height:
            cell_w, cell_h = width / columns, height / rows
            candidates.append((abs(cell_w - cell_h), columns * rows - count, columns))
    return min(candidates)[2] if candidates else None


def preferred_grid(count, cell_width, cell_height, max_width, max_height):
    candidates = []
    for columns in range(1, max(1, count) + 1):
        rows = max(1, math.ceil(count / columns))
        width, height = columns * cell_width, rows * cell_height
        if width <= max_width and height <= max_height:
            candidates.append((abs(width / height - 1.35), width * height, width, height))
    return min(candidates)[2:] if candidates else None


class EmojiPicker(tk.Toplevel):
    def __init__(self, parent, images, on_select):
        super().__init__(parent)
        self.title('遊戲表情')
        self.buttons = []
        self._columns = self._rows = 0
        self._images = images
        self._icon_size = 24
        self.grid_frame = ttk.Frame(self, padding=4)
        self.grid_frame.pack(fill='both', expand=True)
        entries = [int(key) for key, entry in images.catalog.items()
                   if entry.get('show_in_list', True) and entry.get('available', True)]
        for index in entries:
            token = f'[Emoji{index}]'
            picture = images.get(token, 24)
            button = ttk.Button(self.grid_frame, text=str(index), image=picture,
                                compound='top', width=0,
                                command=lambda value=token: on_select(value))
            button.emoji_token = token
            button.emoji_image = picture
            self.buttons.append(button)
        if not self.buttons:
            ttk.Label(self.grid_frame, text='官方表情尚未就緒；聊天仍可使用文字',
                      wraplength=240).pack(padx=12, pady=12)
        self.update_idletasks()
        self._min_width = max([b.winfo_reqwidth() + 4 for b in self.buttons] or [260])
        self._min_height = max([b.winfo_reqheight() + 4 for b in self.buttons] or [80])
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        available_w, available_h = min(1240, sw - 32), min(760, sh - 32)
        minimum = preferred_grid(len(entries), self._min_width, self._min_height,
                                 available_w, available_h)
        if minimum is None:
            self.destroy()
            raise ValueError('螢幕可用空間不足以同頁顯示所有表情，請降低顯示縮放比例')
        preferred = preferred_grid(len(entries), self._min_width + 16,
                                   self._min_height + 16, available_w, available_h) or minimum
        configure_dialog(self, preferred[0] + 8, preferred[1] + 8)
        self.maxsize(sw - 24, sh - 24)
        self.minsize(minimum[0] + 8, minimum[1] + 8)
        self.resizable(True, True)
        self.grid_frame.bind('<Configure>', self._layout)
        self.bind('<Escape>', lambda event: self.destroy())

    def _layout(self, event):
        width, height = max(1, event.width - 8), max(1, event.height - 8)
        columns = fitted_columns(len(self.buttons), width, height,
                                 self._min_width, self._min_height)
        if columns is None:
            return  # Native minimum size prevents this after initial geometry settles.
        rows = max(1, math.ceil(len(self.buttons) / columns))
        icon_size = max(24, min(40, int(min(
            width / columns - (self._min_width - 24),
            height / rows - (self._min_height - 24)))))
        if icon_size != self._icon_size:
            for button in self.buttons:
                picture = self._images.get(button.emoji_token, icon_size)
                button.configure(image=picture)
                button.emoji_image = picture
            self._icon_size = icon_size
        if (columns, rows) != (self._columns, self._rows):
            for column in range(self._columns):
                self.grid_frame.columnconfigure(column, weight=0, uniform='', minsize=0)
            for row in range(self._rows):
                self.grid_frame.rowconfigure(row, weight=0, uniform='', minsize=0)
            for column in range(columns):
                self.grid_frame.columnconfigure(column, weight=1, uniform='emoji')
            for row in range(rows):
                self.grid_frame.rowconfigure(row, weight=1, uniform='emoji')
            for position, button in enumerate(self.buttons):
                button.grid(row=position // columns, column=position % columns,
                            padx=2, pady=2, sticky='nsew')
            self._columns, self._rows = columns, rows
