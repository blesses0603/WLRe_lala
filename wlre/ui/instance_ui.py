"""Main/cooperative instance browser using only verified server snapshots."""
import tkinter as tk
from tkinter import ttk

from wlre.ui.rounded_notebook import RoundedNotebook
from wlre.services.instance_browser import entries_for


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
        self.catalog_records = entries_for(self.mode)
        ttk.Label(self, text="1262 官方副本清單（靜態資料，非房間即時狀態）",
                  style='Muted.TLabel').pack(anchor='w', pady=(0, 3))
        self.catalog_columns = ('id', 'name', 'level', 'players', 'time')
        catalog_host = ttk.Frame(self)
        catalog_host.pack(fill='x', pady=(0, 4))
        self.catalog_table = ttk.Treeview(
            catalog_host, columns=self.catalog_columns,
            show='headings', selectmode='browse', height=7)
        for field, title, width in (
            ('id', 'ID', 48), ('name', '官方中文名稱／版本', 210),
            ('level', '等級', 66), ('players', '人數', 76),
            ('time', '時間', 80)
        ):
            self.catalog_table.heading(field, text=title)
            self.catalog_table.column(field, width=width, anchor='w', stretch=True)
        scroll = ttk.Scrollbar(catalog_host, orient='vertical',
                               command=self.catalog_table.yview)
        self.catalog_table.configure(yscrollcommand=scroll.set)
        self.catalog_table.pack(side='left', fill='x', expand=True)
        scroll.pack(side='right', fill='y')
        for index, record in enumerate(self.catalog_records):
            variant = (' (版本 %s)' % record['variant']) if record['variant'] else ''
            members = ('%s～%s' % (record['min_members'], record['max_members'])
                       if record['max_members'] else '依活動')
            duration = ('%s 分' % record['time_minutes']
                        if record['time_minutes'] else '依活動')
            self.catalog_table.insert('', 'end', iid='catalog_%s' % index,
                values=(record['id'], record['name'] + variant,
                        record['min_level'] or '依活動', members, duration))
        self.catalog_detail = tk.StringVar(value='點選官方副本名稱可查看來源 ID 與獎勵資料筆數。')
        ttk.Label(self, textvariable=self.catalog_detail,
                  style='Muted.TLabel').pack(fill='x', pady=(0, 5))
        self.catalog_table.bind('<<TreeviewSelect>>', self.on_catalog_selected)
        ttk.Label(self, text='伺服器房間清單', style='Muted.TLabel').pack(
            anchor='w', pady=(0, 2))
        self.columns = ('name', 'requirement', 'status')
        self.entries = ttk.Treeview(
            self, columns=self.columns, show='headings', selectmode='browse', height=5
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

    def on_catalog_selected(self, _event=None):
        selection = self.catalog_table.selection()
        if not selection:
            return
        index = int(selection[0].removeprefix('catalog_'))
        record = self.catalog_records[index]
        self.catalog_detail.set(
            '副本 ID %s｜場景 %s｜獎勵資料 %s 筆；是否可進入仍以伺服器為準' %
            (record['id'], record['map_id'], len(record['awards'])))

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
