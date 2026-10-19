"""Instance and co-op instance entry surfaces (UI only, no network commands)."""
from tkinter import ttk

from wlre.ui.rounded_notebook import RoundedNotebook


class InstanceModePage(ttk.Frame):
    """Empty verified-data view; never fabricate instance availability."""

    def __init__(self, parent, *, cooperative):
        super().__init__(parent, padding=12)
        self.cooperative = cooperative
        title = '協力副本' if cooperative else '主要副本'
        ttk.Label(self, text=title, style='Heading.TLabel').pack(anchor='w', pady=(2, 6))
        ttk.Label(
            self,
            text='請先核對官方副本清單、進入條件及伺服器回覆；目前僅建立導覽入口。',
            style='Muted.TLabel',
            anchor='w',
        ).pack(fill='x', pady=(0, 12))
        self.columns = ('name', 'requirement', 'status')
        self.entries = ttk.Treeview(
            self, columns=self.columns, show='headings', selectmode='browse', height=10
        )
        for key, heading, width in (
            ('name', '副本名稱', 240),
            ('requirement', '進入條件', 220),
            ('status', '狀態', 150),
        ):
            self.entries.heading(key, text=heading)
            self.entries.column(key, width=width, stretch=True, anchor='w')
        self.entries.pack(fill='both', expand=True)
        ttk.Label(
            self,
            text='目前沒有已核對的副本資料；不會自動查詢、加入隊伍或發送進入指令。',
            style='Muted.TLabel',
            anchor='w',
        ).pack(fill='x', pady=(10, 8))
        controls = ttk.Frame(self)
        controls.pack(fill='x')
        self.enter_button = ttk.Button(controls, text='進入副本', state='disabled')
        self.enter_button.pack(side='right')


class InstancePanel(ttk.Frame):
    """Main instance tab containing the 主要 / 協力 sub-tabs."""

    def __init__(self, parent):
        super().__init__(parent, padding=6)
        self.tabs = RoundedNotebook(self, borderless=True)
        self.tabs.pack(fill='both', expand=True)
        self.main_page = InstanceModePage(self.tabs, cooperative=False)
        self.coop_page = InstanceModePage(self.tabs, cooperative=True)
        self.tabs.add(self.main_page, text='主要')
        self.tabs.add(self.coop_page, text='協力')
