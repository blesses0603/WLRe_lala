"""Inline storage confirmation: no modal grab or nested Tk wait loop."""
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

from wlre.services.items.catalog import item_display_name
from wlre.services.items.reservations import available, identity
from wlre.services.items.room_storage_transfer import plan_transfer


def transfer_command(snapshot, target, action, index, expected, text):
    """Revalidate the selected identity against the latest displayed state."""
    value = text.strip()
    if not value or not value.isascii() or not value.isdecimal() or len(value) > 5:
        raise ValueError('數量請輸入 1～65535 的整數')
    source = snapshot['inventory'] if action == 'deposit' else snapshot['room_storage'][target]
    item = source.get('items', {}).get(str(index))
    if item is None or identity(item) != identity(expected):
        raise ValueError('所選格位的物品已變更，請重新選取')
    command = {'type': 'room_storage', 'target': target, 'action': action,
               'index': index, 'item_id': item['item_id'], 'count': int(value),
               'bag_revision': snapshot['inventory'].get('revision'),
               'storage_revision': snapshot['room_storage']['revision']}
    plan_transfer(SimpleNamespace(**snapshot), command)
    return command


class StorageTransferForm(ttk.Frame):
    def __init__(self, parent, app, sent, cancel):
        super().__init__(parent, padding=(12, 8))
        self.app = app
        self.sent = sent
        self.cancel = cancel
        self.submitted = False
        self.target = self.action = self.index = self.expected = None
        summary = ttk.Frame(self)
        summary.pack(fill='x')
        self.heading = tk.StringVar(self)
        ttk.Label(summary, textvariable=self.heading, style='Heading.TLabel').pack(side='left')
        self.stock = tk.StringVar(self)
        ttk.Label(summary, textvariable=self.stock, style='Muted.TLabel').pack(side='right')
        controls = ttk.Frame(self)
        controls.pack(fill='x', pady=(4, 0))
        ttk.Label(controls, text='數量').pack(side='left')
        self.count = tk.StringVar(self, value='1')
        self.entry = ttk.Spinbox(controls, textvariable=self.count, from_=1, to=65535, width=8)
        self.entry.pack(side='left', padx=6)
        self.maximum = ttk.Button(controls, text='最多', command=self.use_maximum)
        self.maximum.pack(side='left')
        self.message = tk.StringVar(self)
        ttk.Label(controls, textvariable=self.message, wraplength=480).pack(side='left',padx=8)
        self.confirm = ttk.Button(controls, text='確認', command=self.submit)
        self.confirm.pack(side='right')
        ttk.Button(controls, text='取消', command=cancel).pack(side='right', padx=6)
        self.entry.bind('<Return>', self.submit)
        self.entry.bind('<Escape>', lambda event: cancel())
        self.entry.bind('<Map>', lambda event: self.after_idle(self.focus_entry), add='+')

    def present(self, target, action, index, expected):
        self.target, self.action, self.index = target, action, index
        self.expected = dict(expected)
        self.submitted = False
        self.count.set('1')
        verb = '存入' if action == 'deposit' else '取出'
        container = '儲藏室' if target == 'garage' else '雜物櫃'
        route = f'背包 → {container}' if action == 'deposit' else f'{container} → 背包'
        self.heading.set(f'{verb}：{item_display_name(expected["item_id"])}｜{route}')
        self.confirm.configure(text=f'確認{verb}')
        self.message.set('核對物品與數量後確認；送出後等待伺服器庫存更新。')
        self.render(self.app.snapshot)
        # The existing resource window owns focus; no new transient window,
        # wait_visibility(), wait_window() or grab can trap remote input.
        self.after_idle(self.focus_entry)

    def focus_entry(self):
        if self.winfo_ismapped() and not self.submitted:
            self.entry.focus_set()
            self.entry.selection_range(0, 'end')

    def limit(self, snapshot):
        source = snapshot['inventory'] if self.action == 'deposit' else snapshot['room_storage'][self.target]
        return min(available(source, self.index), 65535 if self.target == 'materials' and self.action == 'withdraw' else 255)

    def render(self, snapshot):
        if self.target is None:
            return
        limit = self.limit(snapshot)
        self.stock.set(f'來源可用：{limit} 個')
        self.entry.configure(to=max(1, limit))
        state = 'disabled' if self.submitted else 'normal'
        for widget in (self.entry, self.maximum, self.confirm):
            widget.configure(state=state)
        if self.submitted:
            self.message.set(snapshot.get('room_storage', {}).get('status') or '已送出，等待伺服器確認')

    def use_maximum(self):
        if not self.submitted:
            self.count.set(str(self.limit(self.app.snapshot)))

    def submit(self, event=None):
        if self.submitted:
            return 'break'
        try:
            if not self.app.live_active:
                raise ValueError('連線已結束，請先登入角色')
            command = transfer_command(self.app.snapshot, self.target, self.action,
                                       self.index, self.expected, self.count.get())
        except (ValueError, KeyError, AttributeError) as exc:
            self.message.set(str(exc))
            self.focus_entry()
            return 'break'
        self.submitted = True
        self.render(self.app.snapshot)
        self.message.set('已送出，等待伺服器確認；請勿重複操作。')
        if self.app.send(command) is False:
            self.rejected('尚未送出，請檢查連線後再操作')
        else:
            self.sent(command)
        return 'break'

    def rejected(self, message):
        self.submitted = False
        self.render(self.app.snapshot)
        self.message.set(message)
