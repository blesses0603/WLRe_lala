"""Main/cooperative instance browser using only verified server snapshots."""
import tkinter as tk
from tkinter import ttk

from wlre.ui.rounded_notebook import RoundedNotebook


class InstanceModePage(ttk.Frame):
    """Room browser; mutations remain locked pending official live validation."""

    def __init__(self, parent, *, cooperative, app=None):
        super().__init__(parent, padding=12)
        self.cooperative = cooperative
        self.mode = 'coop' if cooperative else 'main'
        self.app = app
        title = '協力副本' if cooperative else '主要副本'
        ttk.Label(self, text=title, style='Heading.TLabel').pack(anchor='w', pady=(2, 6))
        self.note = tk.StringVar(value='尚未查詢房間。請登入後手動更新。')
        ttk.Label(self, textvariable=self.note, style='Muted.TLabel', anchor='w').pack(fill='x', pady=(0, 10))
        self.columns = ('name', 'requirement', 'status')
        self.entries = ttk.Treeview(
            self, columns=self.columns, show='headings', selectmode='browse', height=10
        )
        for key, heading, width in (
            ('name', '房間／副本', 240),
            ('requirement', '人數／條件', 220),
            ('status', '公開狀態', 150),
        ):
            self.entries.heading(key, text=heading)
            self.entries.column(key, width=width, stretch=True, anchor='w')
        self.entries.pack(fill='both', expand=True)
        self.details = tk.StringVar(value='沒有已確認的副本房間；進入與領獎功能尚未開放。')
        ttk.Label(self, textvariable=self.details, style='Muted.TLabel',
                  anchor='w').pack(fill='x', pady=(10, 8))
        controls = ttk.Frame(self)
        controls.pack(fill='x')
        self.refresh_button = ttk.Button(
            controls, text='更新房間清單', command=self.refresh_rooms, state='disabled')
        self.refresh_button.pack(side='left')
        self.enter_button = ttk.Button(controls, text='進入副本', state='disabled')
        self.enter_button.pack(side='right')

    def refresh_rooms(self):
        if self.app is not None and self.app.live_active:
            self.app.send({'type': 'instance_refresh', 'mode': self.mode})

    def render(self, data, *, live=False):
        self.refresh_button.state(['!disabled'] if live else ['disabled'])
        self.note.set(data.get('status', '尚未查詢房間') if live else '尚未連線，無法查詢副本房間')
        rooms = data.get('rooms', ())
        # Refresh a small, bounded list; never invent known dungeon names.
        self.entries.delete(*self.entries.get_children())
        for room in rooms:
            room_id = room['room_id']
            capacity = room.get('capacity')
            count = room.get('members', 0)
            occupancy = '%s/%s 人' % (count, capacity) if capacity is not None else '%s 人' % count
            self.entries.insert('', 'end', values=(
                '房間 #%s' % room_id,
                occupancy,
                '公開' if room.get('public') else '私人',
            ))
        current = data.get('room')
        if current is not None:
            count = len(data.get('members') or ())
            status = '目前房間 #%s' % current.get('room_id', '待確認')
            self.details.set('%s；已知成員 %s 人，階段：%s' % (
                status, count, data.get('phase', '待確認')))
        elif self.cooperative and data.get('reward'):
            reward = data['reward']
            self.details.set('協力獎勵旗標 %s，已完成階段 %s；領獎功能未開放' % (
                reward['reward_mark'], reward['win_stage']))
        else:
            self.details.set('未加入房間；進入、準備、領獎功能仍待正式伺服器驗證。')
        # Under no circumstances does a snapshot alone enable mutation.
        self.enter_button.state(['disabled'])


class InstancePanel(ttk.Frame):
    """Main instance tab with two independent, read-only server snapshots."""

    def __init__(self, parent, app=None):
        super().__init__(parent, padding=6)
        self.tabs = RoundedNotebook(self, borderless=True)
        self.tabs.pack(fill='both', expand=True)
        self.main_page = InstanceModePage(self.tabs, cooperative=False, app=app)
        self.coop_page = InstanceModePage(self.tabs, cooperative=True, app=app)
        self.tabs.add(self.main_page, text='主要')
        self.tabs.add(self.coop_page, text='協力')

    def render(self, state, *, live=False):
        instances = state.get('instances') or {}
        self.main_page.render(instances.get('main', {}), live=live)
        self.coop_page.render(instances.get('coop', {}), live=live)
