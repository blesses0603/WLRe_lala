"""Icon inventory grid and click-to-open item detail for the live bag.

Displays only server-confirmed inventory slots. Item actions are delegated to
ResourceView, preserving the existing combat/field validation and packet path.
"""
import math
import tkinter as tk
from tkinter import ttk

from wlre.services.items.combat_resources import CAT, item_name, heal_effects, available
from wlre.ui.theme import PANEL, CYAN, group

PAGE_SIZE = 25
COLUMNS = 5
SLOT_BG = '#173348'
SLOT_ACTIVE = '#27637c'


def visible_items(inventory, query=''):
    """Return actual inventory slots sorted by index, without inventing slots."""
    search = query.strip().casefold()
    result = []
    for index, record in sorted(inventory.get('items', {}).items(), key=lambda item: int(item[0])):
        name = item_name(record['item_id'])
        if search and search not in (name + ' ' + str(record['item_id'])).casefold():
            continue
        result.append((str(index), record, name))
    return result


def item_details(inventory, index, record):
    """Conservatively label fields present in the decoded catalog."""
    sid = record['item_id']
    info = CAT['items'].get(str(sid), {})
    effects = heal_effects(sid)
    lines = [f"HP +{effects['hp']}" for _ in (0,) if effects.get('hp')]
    lines += [f"SP +{effects['sp']}" for _ in (0,) if effects.get('sp')]
    if not lines:
        # Raw codes are intentionally not translated as unverified game bonuses.
        lines = [
            f"屬性碼 {attr['kind']}：值 {attr['value']}"
            for attr in info.get('attributes', [])
            if attr.get('kind') and attr.get('value') not in (0, 100)
        ][:4]
    return {
        'id': sid,
        'name': item_name(sid),
        'index': int(index),
        'count': record.get('count', 0),
        'reserved': inventory.get('reserved', {}).get(str(index), 0),
        'available': available(inventory, str(index)),
        'kind': info.get('kind'),
        'effects': effects,
        'lines': lines or ['尚無已確認的可顯示效果'],
    }


class BagGrid(ttk.Frame):
    """Five-by-five icon pages with an item information card on selection."""

    def __init__(self, parent, icons, use_item):
        super().__init__(parent)
        self.icons = icons
        self.use_item = use_item
        self.rows = []
        self.bag_map = {}
        self.index_selected = None
        self.page = 0
        self.inventory = {}
        self.query = ''
        self._signature = None
        self._images = []
        self._detail_image = None

        shell = ttk.Frame(self, padding=(8, 8))
        shell.pack(fill='both', expand=True)
        shell.columnconfigure(0, weight=3)
        shell.columnconfigure(1, weight=2)
        shell.rowconfigure(0, weight=1)

        left = ttk.Frame(shell)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 12))
        title = ttk.Frame(left)
        title.pack(fill='x', pady=(0, 8))
        ttk.Label(title, text='背包格位', style='Heading.TLabel').pack(side='left')
        self.summary = tk.StringVar(value='等待包包同步')
        ttk.Label(title, textvariable=self.summary, style='Muted.TLabel').pack(side='right')

        self.board = tk.Frame(left, bg=PANEL, borderwidth=0)
        self.board.pack(fill='both', expand=True)
        self.cells = []
        for row in range(5):
            self.board.grid_rowconfigure(row, weight=1, uniform='bagrow')
        for column in range(COLUMNS):
            self.board.grid_columnconfigure(column, weight=1, uniform='bagcolumn')
        for position in range(PAGE_SIZE):
            self.cells.append(self._new_cell(position))

        pager = ttk.Frame(left)
        pager.pack(fill='x', pady=(8, 0))
        ttk.Button(pager, text='上一頁', command=lambda: self.change_page(-1)).pack(side='left')
        self.page_label = tk.StringVar(value='1 / 1')
        ttk.Label(pager, textvariable=self.page_label).pack(side='left', expand=True)
        ttk.Button(pager, text='下一頁', command=lambda: self.change_page(1)).pack(side='right')

        self.hover_text = tk.StringVar(value='選擇道具格位，即可查看道具資訊')
        ttk.Label(left, textvariable=self.hover_text, style='Muted.TLabel').pack(fill='x', pady=(6, 0))

        # Use the same GlassGroup and themed ttk widgets as the other LaLa panels.
        # Avoid a separate light-coloured backplate which ignores GlassTheme.
        self.card = group(shell, text='道具資訊', padding=10)
        self.card.grid(row=0, column=1, sticky='nsew')
        self.card.grid_propagate(False)
        self.card_title = tk.StringVar(value='物品資訊')
        head = ttk.Frame(self.card)
        head.pack(fill='x', pady=(0, 8))
        ttk.Label(head, textvariable=self.card_title, style='Heading.TLabel',
                  anchor='w', wraplength=220).pack(
                      side='left', fill='x', expand=True, padx=(0, 8), pady=(0, 4))
        ttk.Button(head, text='×', width=3, command=self.clear_selection).pack(side='right')

        self.info = ttk.Frame(self.card)
        self.info.pack(fill='both', expand=True)
        self.large_icon = ttk.Label(self.info)
        self.large_icon.pack(pady=(4, 8))
        self.meta = tk.StringVar(value='請點選左側道具')
        ttk.Label(self.info, textvariable=self.meta, anchor='w',
                  justify='left', wraplength=270).pack(fill='x', padx=4, pady=(0, 6))
        self.effect = tk.StringVar(value='')
        ttk.Label(self.info, textvariable=self.effect, anchor='nw',
                  justify='left', wraplength=270).pack(fill='x', padx=4, pady=(0, 8))
        self.note = tk.StringVar(value='道具使用仍由原本程式驗證；未確認的操作不會送出')
        ttk.Label(self.info, textvariable=self.note, style='Muted.TLabel',
                  anchor='w', justify='left', wraplength=270).pack(
                      fill='x', padx=4, pady=(6, 8))

        buttons = ttk.Frame(self.card)
        buttons.pack(fill='x', side='bottom', pady=(6, 0))
        self.hp_button = ttk.Button(buttons, text='補 HP', command=lambda: self.use_item('hp'))
        self.hp_button.pack(side='left', expand=True, fill='x', padx=2)
        self.sp_button = ttk.Button(buttons, text='補 SP', command=lambda: self.use_item('sp'))
        self.sp_button.pack(side='left', expand=True, fill='x', padx=2)
        self._clear_card()

    def _new_cell(self, position):
        row, col = divmod(position, COLUMNS)
        frame = tk.Frame(self.board, bg=SLOT_BG, highlightthickness=1,
                         highlightbackground='#426985', cursor='hand2')
        frame.grid(row=row, column=col, sticky='nsew', padx=4, pady=4)
        frame.grid_propagate(False)
        icon = tk.Label(frame, bg=SLOT_BG, bd=0, cursor='hand2')
        icon.place(relx=0.5, rely=0.48, anchor='center')
        count = tk.Label(frame, bg=SLOT_BG, fg='#f9e6b5', bd=0, font=('TkDefaultFont', 10, 'bold'))
        count.place(relx=0.96, rely=0.96, anchor='se')
        entry = {'frame': frame, 'icon': icon, 'count': count, 'index': None}
        for widget in (frame, icon, count):
            widget.bind('<Button-1>', lambda _event, p=position: self.pick(p))
            widget.bind('<Enter>', lambda _event, p=position: self.show_hover(p))
        return entry

    def selection(self):
        return ('bag' + self.index_selected,) if self.index_selected is not None and ('bag' + self.index_selected) in self.bag_map else ()

    def selection_set(self, iid):
        index = str(iid)[3:] if str(iid).startswith('bag') else None
        if index is not None and 'bag' + index in self.bag_map:
            self.index_selected = index
            self.page = next((n // PAGE_SIZE for n, row in enumerate(self.rows) if row[0] == index), self.page)
            self._paint()

    def render(self, inventory, query=''):
        self.inventory = inventory or {}
        self.query = query
        rows = visible_items(self.inventory, query)
        self.rows = rows
        self.bag_map = {'bag' + index: item for index, item, _name in rows}
        if self.index_selected is not None and 'bag' + self.index_selected not in self.bag_map:
            self.index_selected = None
        pages = max(1, math.ceil(len(rows) / PAGE_SIZE))
        self.page = min(self.page, pages - 1)
        self.summary.set(f"{len(rows)} / {self.inventory.get('capacity', '?')} 格")
        self.page_label.set(f'{self.page + 1} / {pages}')
        signature = (tuple((index, item['item_id'], item.get('count'),
                           self.inventory.get('reserved', {}).get(index, 0))
                           for index, item, _name in rows), self.page, self.index_selected,
                     self.inventory.get('ready'), self.inventory.get('reliable'),
                     self.inventory.get('use_failed'),
                     tuple(self.inventory.get('alchemy_slots', ())))
        if signature != self._signature:
            self._signature = signature
            self._paint()
        return self.bag_map

    def change_page(self, direction):
        pages = max(1, math.ceil(len(self.rows) / PAGE_SIZE))
        self.page = min(max(0, self.page + direction), pages - 1)
        self.page_label.set(f'{self.page + 1} / {pages}')
        self._signature = None
        self._paint()

    def _paint(self):
        self._images = []
        page_rows = self.rows[self.page * PAGE_SIZE: (self.page + 1) * PAGE_SIZE]
        for position, cell in enumerate(self.cells):
            row = page_rows[position] if position < len(page_rows) else None
            index = row[0] if row else None
            cell['index'] = index
            selected = index is not None and index == self.index_selected
            bg = SLOT_ACTIVE if selected else SLOT_BG
            for widget in (cell['frame'], cell['icon'], cell['count']):
                widget.configure(bg=bg)
            cell['frame'].configure(highlightbackground=CYAN if selected else '#426985')
            if row:
                _index, item, _name = row
                photo = self.icons.get(item['item_id'], 46)
                self._images.append(photo)
                cell['icon'].configure(image=photo)
                cell['count'].configure(text=str(item.get('count', 0)))
            else:
                cell['icon'].configure(image='')
                cell['count'].configure(text='')
        self._show_card()

    def pick(self, position):
        index = self.cells[position]['index']
        if index is None:
            return
        self.index_selected = index
        self._signature = None
        self._paint()

    def show_hover(self, position):
        index = self.cells[position]['index']
        if index is None:
            self.hover_text.set('空格')
            return
        item = self.bag_map.get('bag' + index)
        if item:
            self.hover_text.set(f"#{index}  {item_name(item['item_id'])} ×{item.get('count', 0)}")

    def clear_selection(self):
        self.index_selected = None
        self._signature = None
        self._paint()

    def _clear_card(self):
        self.card_title.set('物品資訊')
        self.large_icon.configure(image='')
        self._detail_image = None
        self.meta.set('請點選左側道具格位')
        self.effect.set('')
        self.note.set('依遊戲同步資料顯示；未提供的欄位不會推測')
        self.hp_button.configure(state='disabled')
        self.sp_button.configure(state='disabled')

    def _show_card(self):
        index = self.index_selected
        record = self.bag_map.get('bag' + index) if index is not None else None
        if not record:
            self._clear_card()
            return
        details = item_details(self.inventory, index, record)
        self.card_title.set(details['name'])
        self._detail_image = self.icons.get(details['id'], 78)
        self.large_icon.configure(image=self._detail_image)
        self.meta.set(
            f"道具 ID：{details['id']}\n"
            f"格位：{details['index']}  |  類型碼：{details['kind'] if details['kind'] is not None else '未知'}\n"
            f"持有：{details['count']}  |  待扣：{details['reserved']}  |  可用：{details['available']}"
        )
        self.effect.set('效果\n' + '\n'.join(details['lines']))
        self.note.set('未驗證的交易與一般道具使用功能暫不提供')
        enabled = (details['available'] > 0 and self.inventory.get('ready')
                   and self.inventory.get('reliable') and not self.inventory.get('use_failed')
                   and str(index) not in self.inventory.get('alchemy_slots', ())
                   and not record.get('locked') and not record.get('limited_time')
                   and not record.get('available_time'))
        self.hp_button.configure(state='normal' if enabled and details['effects'].get('hp') else 'disabled')
        self.sp_button.configure(state='normal' if enabled and details['effects'].get('sp') else 'disabled')
