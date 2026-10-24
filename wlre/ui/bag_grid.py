"""Icon inventory grid and click-to-open item detail for the live bag.

Displays only server-confirmed inventory slots. Item actions are delegated to
ResourceView, preserving the existing combat/field validation and packet path.
"""
import math
import tkinter as tk
from tkinter import ttk

from wlre.services.items.combat_resources import CAT, heal_effects, available
from wlre.services.items.catalog import item_display_name as item_name, verified_item_metadata
from wlre.services.world.feature_resource_index import feature_note
from wlre.ui.theme import PANEL, CYAN, group

COLUMNS = 6
ROWS = 4
PAGE_SIZE = COLUMNS * ROWS
ICON_SIZE = 64
# The nested hyperspace storage tab has a shorter drawable area than the main
# inventory. Never squeeze four rows of 64px icons into that small space.
STORAGE_ROWS = 2
STORAGE_ICON_SIZE = 60
SLOT_HEIGHT = 88
SLOT_BG = '#132d40'
SLOT_ACTIVE = '#244f67'


def grid_profile(compact=False):
    """Columns, rows, and icon size for ordinary vs nested storage pages."""
    return (COLUMNS, STORAGE_ROWS if compact else ROWS,
            STORAGE_ICON_SIZE if compact else ICON_SIZE)


def responsive_profile(width, height, compact=False):
    """Fit whole inventory tiles into the drawable board, without overlap.

    The published default 6x4 (storage 6x2) geometry stays unchanged on
    ordinary desktops. Smaller dialogs use fewer columns and/or rows, keeping
    the icon size and click targets intact rather than squeezing artwork.
    """
    _columns, maximum_rows, size = grid_profile(compact)
    columns = min(COLUMNS, max(2, int(width) // (size + 32)))
    rows = min(maximum_rows, max(1, int(height) // SLOT_HEIGHT))
    return columns, rows, size


def page_count(item_count, compact=False, *, columns=None, rows=None):
    default_columns, default_rows, _size = grid_profile(compact)
    columns = default_columns if columns is None else columns
    rows = default_rows if rows is None else rows
    return max(1, math.ceil(item_count / (columns * rows)))


def reflow_page(old_page, old_size, new_size, item_count, selected_position=None):
    """Keep the selected item, or the previous top-left item, visible."""
    anchor = selected_position if selected_position is not None else old_page * old_size
    return min(max(0, anchor // new_size), max(0, math.ceil(item_count / new_size) - 1))


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
    official = verified_item_metadata(sid)
    if official:
        # 1275 has checked base prices / restrictions but no approved item
        # effects schema. Do not render 1262 healing values as 1275 truth,
        # nor enable bag-grid healing buttons from historical metadata.
        price = official['base_price']
        level = official['need_level']
        status = 'NPC 不可販售' if not official['npc_sale_allowed'] else 'NPC 可販售（基礎資料）'
        lines = [f'正式 1275 基礎價：{price} 金幣',
                 f'需求等級：{level}；{status}',
                 '1275 道具使用效果尚未核對，不依舊版資料啟用快捷補給']
        return {
            'id': sid, 'name': official['name'], 'index': int(index),
            'count': record.get('count', 0),
            'reserved': inventory.get('reserved', {}).get(str(index), 0),
            'available': available(inventory, str(index)),
            'kind': None, 'effects': {}, 'lines': lines,
            'metadata_source': 'verified_1275_itemdata',
        }
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
    """Roomy icon pages with a compact bottom details strip."""

    def __init__(self, parent, icons, use_item, read_only=False, title='背包格位', compact=False):
        super().__init__(parent)
        self.read_only = read_only
        self.compact = compact
        self.columns, self.row_count, self.icon_size = grid_profile(compact)
        self.page_size = self.columns * self.row_count
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

        # Layout is one contiguous themed column.  Solid independent backplates
        # previously left offset artwork and conspicuous borders at the edges.
        shell = ttk.Frame(self, padding=0)
        shell.pack(fill='both', expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        header = ttk.Frame(shell)
        header.grid(row=0, column=0, sticky='ew', pady=(0, 4))
        ttk.Label(header, text=title, style='Heading.TLabel').pack(side='left')
        self.summary = tk.StringVar(value='等待包包同步')
        ttk.Label(header, textvariable=self.summary, style='Muted.TLabel').pack(side='right')

        self.board = ttk.Frame(shell)
        self.board.grid(row=1, column=0, sticky='nsew')
        self.cells = []
        # Do not force six column minimums on smaller windows: allow the
        # board's actual width and height to determine its active tile count.
        for row in range(ROWS):
            self.board.grid_rowconfigure(row, weight=1, minsize=0, uniform='bagrow')
        for column in range(COLUMNS):
            self.board.grid_columnconfigure(column, weight=1, minsize=0, uniform='bagcolumn')
        for position in range(COLUMNS * self.row_count):
            self.cells.append(self._new_cell(position))
        self.board.bind('<Configure>', self._board_resized, add='+')

        pager = ttk.Frame(shell)
        pager.grid(row=2, column=0, sticky='ew', pady=(4, 2))
        ttk.Button(pager, text='上一頁', command=lambda: self.change_page(-1)).pack(side='left')
        self.page_label = tk.StringVar(value='1 / 1')
        ttk.Label(pager, textvariable=self.page_label).pack(side='left', expand=True)
        ttk.Button(pager, text='下一頁', command=lambda: self.change_page(1)).pack(side='right')

        # Small, inline information strip rather than a full-height side panel.
        self.card = ttk.Frame(shell, padding=(4, 4))
        self.card.grid(row=3, column=0, sticky='ew', pady=(2, 0))
        self.card.columnconfigure(1, weight=1)
        self.card_title = tk.StringVar(value='物品資訊')
        self.large_icon = ttk.Label(self.card)
        self.large_icon.grid(row=0, column=0, rowspan=3, padx=(0, 12), sticky='w')
        ttk.Label(self.card, textvariable=self.card_title, style='Heading.TLabel').grid(
            row=0, column=1, sticky='w')
        self.meta = tk.StringVar(value='請點選道具')
        ttk.Label(self.card, textvariable=self.meta, anchor='w').grid(
            row=1, column=1, sticky='ew')
        self.effect = tk.StringVar(value='')
        ttk.Label(self.card, textvariable=self.effect, style='Muted.TLabel',
                  anchor='w', wraplength=570).grid(row=2, column=1, sticky='ew')
        self.note = tk.StringVar(value='')
        # Keep the original healing validation, but show only context actions
        # inside the selected item's strip, not duplicate buttons below the bag.
        buttons = ttk.Frame(self.card)
        buttons.grid(row=0, column=2, rowspan=3, sticky='e', padx=(8, 0))
        self.hp_button = ttk.Button(buttons, text='補 HP', command=lambda: self.use_item('hp'))
        self.hp_button.pack(pady=2)
        self.sp_button = ttk.Button(buttons, text='補 SP', command=lambda: self.use_item('sp'))
        self.sp_button.pack(pady=2)
        if self.read_only:
            buttons.grid_remove()

        self.hover_text = tk.StringVar(value='點擊圖示查看道具詳情')
        if not self.compact:
            ttk.Label(shell, textvariable=self.hover_text, style='Muted.TLabel').grid(
                row=4, column=0, sticky='w', pady=(0, 2))
        self._clear_card()

    def _new_cell(self, position):
        row, col = divmod(position, self.columns)
        frame = tk.Frame(self.board, bg=SLOT_BG, borderwidth=0,
                         highlightthickness=1, highlightbackground='#3a627a',
                         highlightcolor=CYAN, cursor='hand2')
        frame.grid(row=row, column=col, sticky='nsew', padx=4, pady=4)
        frame.grid_propagate(False)
        icon = tk.Label(frame, bg=SLOT_BG, bd=0, cursor='hand2')
        icon.place(relx=0.5, rely=0.46, anchor='center')
        count = tk.Label(frame, bg=SLOT_BG, fg='#f9e6b5', bd=0, font=('TkDefaultFont', 10, 'bold'))
        count.place(relx=0.97, rely=0.96, anchor='se')
        entry = {'frame': frame, 'icon': icon, 'count': count, 'index': None}
        for widget in (frame, icon, count):
            widget.bind('<Button-1>', lambda _event, p=position: self.pick(p))
            widget.bind('<Enter>', lambda _event, p=position: self.show_hover(p))
        return entry

    def _board_resized(self, event):
        if event.widget is not self.board or event.width < 80 or event.height < 50:
            return
        columns, rows, _size = responsive_profile(event.width, event.height, self.compact)
        if (columns, rows) == (self.columns, self.row_count):
            return
        old_size = self.page_size
        selected_position = next(
            (i for i, row in enumerate(self.rows) if row[0] == self.index_selected),
            None,
        )
        self.columns, self.row_count = columns, rows
        self.page_size = columns * rows
        self.page = reflow_page(self.page, old_size, self.page_size,
                                len(self.rows), selected_position)
        for row in range(ROWS):
            self.board.grid_rowconfigure(row, weight=1 if row < rows else 0, minsize=0)
        for column in range(COLUMNS):
            self.board.grid_columnconfigure(column, weight=1 if column < columns else 0,
                                            minsize=0)
        for position, cell in enumerate(self.cells):
            if position < self.page_size:
                row, col = divmod(position, columns)
                cell['frame'].grid(row=row, column=col, sticky='nsew', padx=4, pady=4)
            else:
                cell['frame'].grid_remove()
                cell['index'] = None
        self.page_label.set(f'{self.page + 1} / {page_count(len(self.rows), self.compact, columns=columns, rows=rows)}')
        self._signature = None
        self._paint()

    def selection(self):
        return ('bag' + self.index_selected,) if self.index_selected is not None and ('bag' + self.index_selected) in self.bag_map else ()

    def selection_set(self, iid):
        index = str(iid)[3:] if str(iid).startswith('bag') else None
        if index is not None and 'bag' + index in self.bag_map:
            self.index_selected = index
            self.page = next((n // self.page_size for n, row in enumerate(self.rows) if row[0] == index), self.page)
            self._paint()

    def render(self, inventory, query=''):
        self.inventory = inventory or {}
        self.query = query
        rows = visible_items(self.inventory, query)
        self.rows = rows
        self.bag_map = {'bag' + index: item for index, item, _name in rows}
        if self.index_selected is not None and 'bag' + self.index_selected not in self.bag_map:
            self.index_selected = None
        pages = page_count(len(rows), self.compact, columns=self.columns, rows=self.row_count)
        self.page = min(self.page, pages - 1)
        capacity = self.inventory.get('capacity')
        self.summary.set(f"{len(rows)} / {capacity if capacity is not None else '?'} 格｜{feature_note('bag')}")
        self.page_label.set(f'{self.page + 1} / {pages}')
        signature = (tuple((index, item['item_id'], item.get('count'),
                           item.get('locked'), item.get('limited_time'),
                           item.get('available_time'), available(self.inventory, index))
                           for index, item, _name in rows), self.page, self.index_selected,
                     self.columns, self.row_count,
                     self.inventory.get('ready'), self.inventory.get('reliable'),
                     self.inventory.get('use_failed'),
                     tuple(self.inventory.get('alchemy_slots', ())),
                     tuple(self.inventory.get('expedition_slots', ())),
                     tuple(self.inventory.get('maintenance_slots', ())))
        if signature != self._signature:
            self._signature = signature
            self._paint()
        return self.bag_map

    def change_page(self, direction):
        pages = page_count(len(self.rows), self.compact, columns=self.columns, rows=self.row_count)
        self.page = min(max(0, self.page + direction), pages - 1)
        self.page_label.set(f'{self.page + 1} / {pages}')
        self._signature = None
        self._paint()

    def _paint(self):
        self._images = []
        page_rows = self.rows[self.page * self.page_size: (self.page + 1) * self.page_size]
        for position, cell in enumerate(self.cells[:self.page_size]):
            row = page_rows[position] if position < len(page_rows) else None
            index = row[0] if row else None
            cell['index'] = index
            selected = index is not None and index == self.index_selected
            bg = SLOT_ACTIVE if selected else SLOT_BG
            for widget in (cell['frame'], cell['icon'], cell['count']):
                widget.configure(bg=bg)
            cell['frame'].configure(bg=bg, highlightbackground=CYAN if selected else '#3a627a')
            if row:
                _index, item, _name = row
                photo = self.icons.get(item['item_id'], self.icon_size)
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
        self.note.set('')
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
        self._detail_image = self.icons.get(details['id'], 56)
        self.large_icon.configure(image=self._detail_image)
        if self.read_only:
            self.meta.set(f"ID {details['id']}　格位 {details['index']}　數量 {details['count']}（唯讀）")
        else:
            self.meta.set(
                f"ID {details['id']}　格位 {details['index']}　"
                f"持有 {details['count']}　待扣 {details['reserved']}　可用 {details['available']}"
            )
        self.effect.set('效果：' + ' / '.join(details['lines'][:3]))
        self.note.set('')
        enabled = (not self.read_only and details['available'] > 0 and self.inventory.get('ready')
                   and self.inventory.get('reliable') and not self.inventory.get('use_failed')
                   and str(index) not in self.inventory.get('alchemy_slots', ())
                   and not record.get('locked') and not record.get('limited_time')
                   and not record.get('available_time'))
        self.hp_button.configure(state='normal' if enabled and details['effects'].get('hp') else 'disabled')
        self.sp_button.configure(state='normal' if enabled and details['effects'].get('sp') else 'disabled')
