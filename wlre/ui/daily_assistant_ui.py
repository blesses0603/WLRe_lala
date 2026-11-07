"""Read-only overview and explicit, atomic daily-assistant configuration."""
import tkinter as tk
from tkinter import ttk

from wlre.services.daily_assistant import view
from wlre.ui.guild_actions_ui import OPTIONS
from wlre.ui.layout import scroll_table


TOGGLES = (
    ('cube_enabled', '魔方開啟'), ('rewards_enabled', '任務／寶箱領獎'),
    ('guild_sign_enabled', '組織簽到'), ('guild_donate_enabled', '組織捐獻'),
    ('ark_dispatch_enabled', '方舟派遣'), ('ark_fights_enabled', '方舟戰鬥'),
    ('ark_questions_enabled', '方舟問答'),
)
SERVICES = {'time_cube': '魔方', 'daily_tasks': '任務領獎',
            'guild_actions': '組織', 'star_ark': '方舟'}


class DailyAssistantPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app
        self.config_identity = None
        self.rows = {}
        self.live = False
        self.can_apply = False
        self.variables = {key: tk.BooleanVar() for key, _ in TOGGLES}
        self.variables.update({key: tk.StringVar() for key in
                              ('gold_budget', 'star_budget', 'guild_target', 'ark_hours')})
        self.kind = tk.StringVar()
        self.summary = tk.StringVar()
        self.details = tk.StringVar()
        self.status = tk.StringVar()
        self.budgets = tk.StringVar()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.content = ttk.Frame(self.canvas)
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(4, minsize=120)
        window = self.canvas.create_window((0, 0), window=self.content, anchor='nw')
        self.content.bind('<Configure>', lambda _: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(window, width=event.width))
        self.label(self.summary, 0)
        checks = ttk.Frame(self.content)
        checks.grid(row=1, column=0, sticky='ew')
        for index, (key, title) in enumerate(TOGGLES):
            ttk.Checkbutton(checks, text=title, variable=self.variables[key]).grid(
                row=index // 3, column=index % 3, sticky='w', padx=(0, 12), pady=2)
        form = ttk.Frame(self.content)
        form.grid(row=2, column=0, sticky='ew', pady=4)
        fields = [('gold_budget', '金幣上限（本輪）'), ('star_budget', '星力上限（本次登入）'),
                  ('guild_target', '每日捐獻總次數 1–5'), ('ark_hours', '派遣小時 1–6')]
        for i, (key, title) in enumerate(fields):
            r, c = i // 2, (i % 2) * 2
            ttk.Label(form, text=title).grid(row=r, column=c, sticky='w', padx=(0, 6), pady=2)
            ttk.Entry(form, textvariable=self.variables[key], width=9).grid(
                row=r, column=c+1, sticky='ew', padx=(0, 12))
        ttk.Label(form, text='捐獻方案').grid(row=2, column=0, sticky='w')
        ttk.Combobox(form, textvariable=self.kind, values=tuple(OPTIONS), state='readonly',
                     width=10).grid(row=2, column=1, sticky='ew', padx=(0, 12))
        for c in (1, 3):
            form.columnconfigure(c, weight=1)
        actions = ttk.Frame(self.content)
        actions.grid(row=3, column=0, sticky='ew', pady=4)
        self.apply = ttk.Button(actions, text='套用助手設定', command=self.configure_assistant)
        self.apply.pack(side='left')
        self.pause = ttk.Button(actions, text='暫停全部接續', command=self.stop)
        self.pause.pack(side='left', padx=8)
        frame, self.tree = scroll_table(self.content, ('name', 'progress', 'category', 'reason'),
            ('今日任務', '伺服器進度', '執行分類', '說明'), (190, 100, 100, 300), height=4)
        frame.grid(row=4, column=0, sticky='nsew', pady=4)
        self.tree.bind('<<TreeviewSelect>>', lambda _: self.select())
        self.label(self.details, 5)
        self.label(self.budgets, 6)
        self.label(self.status, 7)
        self.note = tk.StringVar(value='勾選只修改草稿，套用後才接續。暫停不清除未確認操作與額度。'
            '不代做所有每日任務；受阻與需手動項目請依說明處理。')
        self.label(self.note, 8)
        self.render({})

    def label(self, variable, row):
        label = ttk.Label(self.content, textvariable=variable, wraplength=680, width=1)
        label.grid(row=row, column=0, sticky='ew', pady=3)
        label.bind('<Configure>', lambda event: label.configure(wraplength=max(100, event.width)))

    def configure_assistant(self):
        if not self.can_apply:
            return
        try:
            fields = {key: var.get() for key, var in self.variables.items()}
            for key in ('gold_budget', 'star_budget', 'guild_target', 'ark_hours'):
                fields[key] = int(fields[key])
            fields['guild_sell_id'] = OPTIONS[self.kind.get()]
            if not all(0 <= fields[k] <= 0xffffffff for k in ('gold_budget', 'star_budget')):
                raise ValueError
            if not 1 <= fields['guild_target'] <= 5 or not 1 <= fields['ark_hours'] <= 6:
                raise ValueError
        except (ValueError, KeyError, tk.TclError):
            self.status.set('設定未送出：上限須為非負整數，捐獻次數 1–5，派遣小時 1–6。')
            return
        self.app.send(dict(type='daily_assistant', action='configure', **fields))
        self.status.set('已送出整組設定，等待服務確認；未確認操作及額度會保留。')

    def stop(self):
        if self.live:
            self.app.send(dict(type='daily_assistant', action='stop'))

    def select(self):
        selection = self.tree.selection()
        row = self.rows.get(selection[0]) if selection else None
        self.details.set(f'{row["name"]}：{row.get("reason", "")}' if row else
                         '選取任務查看執行方式；進度只採用伺服器資料。')

    def render(self, state):
        data = view(state)
        self.live = bool(self.app.live_active and state.get('phase') == 'world_ready')
        settings = data['settings']
        identity = (tuple(sorted(settings.items())), state.get('player', {}).get('role_id'),
                    state.get('daily_tasks', {}).get('generation'),
                    state.get('guild_actions', {}).get('role'), state.get('star_ark', {}).get('role'))
        if identity != self.config_identity:
            self.config_identity = identity
            for key, var in self.variables.items():
                if settings[key] is not None:
                    var.set(settings[key])
            self.kind.set(next((name for name, value in OPTIONS.items()
                                if value == settings['guild_sell_id']), '初級捐獻'))
        services = data['services']
        self.can_apply = self.live and not any(services.get(key, {}).get('pending') or
            services.get(key, {}).get('uncertain') for key in ('guild_actions', 'star_ark'))
        self.apply.configure(state='normal' if self.can_apply else 'disabled')
        self.pause.configure(state='normal' if self.live else 'disabled')
        daily = state.get('daily_tasks', {})
        value = daily.get('daily_value')
        self.summary.set(f'每日任務助手｜今日活躍值：{value if value is not None else "等待同步"}'
                         + ('｜全域自動接續已暫停' if not state.get('automation', {}).get('enabled', True) else ''))
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        categories = {'automatic': '可自動', 'manual': '需手動', 'blocked': '受阻', 'progress': '進度／等待確認'}
        for row in data['rows']:
            key = str(row['index'])
            self.rows[key] = row
            progress = (f'{row["progress"]}/{row["goal"]}' if row.get('progress') is not None
                        and row.get('goal') else '待確認')
            if row.get('received'):
                progress += ' 已領取'
            self.tree.insert('', 'end', iid=key, values=(row['name'], progress,
                categories.get(row.get('classification'), row.get('classification', '受阻')), row.get('reason', '')))
        if selected and selected[0] in self.rows:
            self.tree.selection_set(selected[0])
        self.select()
        amounts = []
        for key, title in (('gold', '金幣'), ('star', '星力')):
            budget = {field: value if value is not None else '等待同步'
                      for field, value in data['budgets'][key].items()}
            amounts.append(f'{title}：已要求額度 {budget["reserved"]}／已確認扣款 {budget["confirmed"]}／上限 {budget["limit"]}')
        self.budgets.set('\n'.join(amounts))
        notes = [data.get('status', '')]
        for key, title in SERVICES.items():
            service = services.get(key, {})
            flag = '結果未確認' if service.get('uncertain') else '等待回覆' if service.get('pending') else '已啟用' if service.get('enabled') else '已暫停'
            notes.append(f'{title} [{flag}]：{service.get("status", "等待同步")}')
        self.status.set('\n'.join(notes))
