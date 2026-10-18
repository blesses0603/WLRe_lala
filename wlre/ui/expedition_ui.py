"""Expedition overview and opt-in automatic dispatch preferences."""
import json
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from wlre.services.expedition import preferences, validate, faith_gain, duration
from wlre.services.expedition_data import data_root, load_catalog, import_catalog
from wlre.services.items.combat_resources import CAT, item_name
from wlre.storage.atomic import file_lock, write_json
from wlre.ui.layout import heading, scroll_table


class ExpeditionPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=6)
        self.app = app
        self.key = None
        self.signature = None
        self.loading_settings = False
        self.catalog = load_catalog()
        heading(self, '遠征', '自動領獎、補好友度並接續派遣；不使用縮時或支援物品。')
        self.status = tk.StringVar(value='等待遠征與駐紮所資料同步。')
        ttk.Label(self, textvariable=self.status, wraplength=700).pack(fill='x', pady=(0, 4))
        controls = ttk.Frame(self)
        controls.pack(fill='x', pady=3)
        ttk.Label(controls, text='任務時間大於').pack(side='left')
        self.hours = tk.StringVar(value='5')
        self.hours_input = ttk.Spinbox(controls, from_=0, to=24, increment=.5, width=5, textvariable=self.hours)
        self.hours_input.pack(side='left', padx=4)
        ttk.Label(controls, text='小時　好友度低於').pack(side='left')
        self.faith = tk.StringVar(value='80')
        self.faith_input = ttk.Spinbox(controls, from_=1, to=100, width=4, textvariable=self.faith)
        self.faith_input.pack(side='left', padx=4)
        ttk.Label(controls, text='時補充').pack(side='left')
        self.auto_claim = tk.BooleanVar(value=True)
        self.claim_option = ttk.Checkbutton(controls, text='自動領獎', variable=self.auto_claim)
        self.claim_option.pack(side='left', padx=8)
        row = ttk.Frame(self)
        row.pack(fill='x', pady=3)
        ttk.Label(row, text='恢復物品').pack(side='left')
        self.item = tk.StringVar(value='不使用物品')
        self.items = {'不使用物品': 0}
        self.items.update({f"{item_name(int(sid))}（{sid}，+{faith_gain(int(sid))}）": int(sid)
                           for sid in CAT['items'] if faith_gain(int(sid))})
        self.item_combo = ttk.Combobox(row, textvariable=self.item, values=list(self.items), state='readonly', width=28)
        self.item_combo.pack(side='left', fill='x', expand=True, padx=6)
        self.start_button = ttk.Button(row, text='啟動自動派遣', command=self.start)
        self.start_button.pack(side='left')
        ttk.Button(row, text='停止', command=lambda: app.send({'type': 'stop_expedition'})).pack(side='left', padx=4)
        ttk.Button(row, text='儲存', command=self.save).pack(side='left')
        body = ttk.Frame(self)
        body.pack(fill='both', expand=True, pady=4)
        body.columnconfigure(0, weight=1); body.columnconfigure(1, weight=1); body.rowconfigure(1, weight=1)
        ttk.Label(body, text='可用任務（依設定門檻篩選；顯示等級減免後時間）').grid(row=0, column=0, sticky='w')
        ttk.Label(body, text='駐紮所夥伴').grid(row=0, column=1, sticky='w')
        frame, self.tasks = scroll_table(body, ('id', 'duration', 'faith'), ('任務 ID', '小時', '消耗好友度'), (70, 70, 90))
        frame.grid(row=1, column=0, sticky='nsew', padx=(0, 8))
        frame, self.roles = scroll_table(body, ('name', 'faith', 'state'), ('夥伴', '好友度', '狀態'), (140, 65, 70))
        frame.grid(row=1, column=1, sticky='nsew')
        self.note = tk.StringVar()
        self.team_status = tk.StringVar()
        ttk.Label(self, textvariable=self.team_status, wraplength=700).pack(fill='x', pady=3)
        ttk.Label(self, textvariable=self.note, style='Muted.TLabel', wraplength=700).pack(fill='x', pady=3)
        ttk.Button(self, text='載入官方遠征資料表', command=self.import_data).pack(anchor='w')
        self.hours.trace_add('write', self.update_filter)
        self.render({})

    def config(self):
        return validate({'min_hours': float(self.hours.get()), 'faith_min': int(self.faith.get()),
                         'item_id': self.items.get(self.item.get(), 0), 'auto_claim': self.auto_claim.get()})

    def update_filter(self, *args):
        if not self.loading_settings:
            self.render(self.app.snapshot)

    def settings_path(self):
        key = self.app.settings_identity()
        if not key: raise ValueError('請先選擇帳號再儲存遠征設定')
        return data_root() / 'accounts' / (key + '.expedition.json')

    def load_settings(self, key):
        self.key = key
        value = preferences()
        if key:
            path = data_root() / 'accounts' / (key + '.expedition.json')
            try:
                with file_lock(path):
                    if path.exists(): value = validate(json.loads(path.read_text(encoding='utf8')))
            except (OSError, ValueError) as exc:
                self.status.set('遠征設定讀取失敗：' + str(exc))
        self.loading_settings = True
        try:
            self.hours.set(str(value['min_hours'])); self.faith.set(str(value['faith_min']))
            self.auto_claim.set(value['auto_claim'])
            self.item.set(next((label for label, sid in self.items.items() if sid == value['item_id']), '不使用物品'))
        finally:
            self.loading_settings = False

    def save(self):
        try:
            path = self.settings_path()
            with file_lock(path): write_json(path, self.config())
            self.status.set('已儲存遠征設定；登入後不會自動啟動。')
        except (OSError, ValueError) as exc:
            messagebox.showerror('遠征設定', str(exc), parent=self.app.root)

    def start(self):
        try:
            settings = self.config()
        except ValueError as exc:
            messagebox.showerror('遠征設定', str(exc), parent=self.app.root)
            return
        if self.app.send({'type': 'start_expedition', 'settings': settings}) is False:
            self.status.set('連線已結束，請重新登入後再啟動遠征。')

    def import_data(self):
        paths = []
        for name in ('AdventureData_C', 'AdventureLvData_C'):
            path = filedialog.askopenfilename(parent=self.app.root, title='選擇官方 ' + name + ' 原始資料檔')
            if not path: return
            paths.append(path)
        try:
            self.catalog = import_catalog(*paths)
            self.signature = None
            self.render(self.app.snapshot)
        except (OSError, ValueError) as exc:
            messagebox.showerror('遠征資料', str(exc), parent=self.app.root)

    def render(self, state):
        e = state.get('expedition', {})
        live = self.app.live_active
        if live and self.app._settings_key != self.key:
            self.load_settings(self.app._settings_key)
        self.start_button.configure(state='normal' if live and e.get('ready') and e.get('outpost_ready')
                                    and self.catalog.get('tasks') and not e.get('enabled') and not e.get('uncertain') else 'disabled')
        for control in (self.hours_input, self.faith_input, self.claim_option):
            control.configure(state='disabled' if e.get('enabled') or e.get('pending') else 'normal')
        self.item_combo.configure(state='disabled' if e.get('enabled') or e.get('pending') else 'readonly')
        self.status.set(('' if live else '已離線｜') + e.get('status', '等待遠征與駐紮所資料同步。'))
        teams = []
        for t in e.get('teams', {}).values():
            if not t.get('quest'): continue
            remaining = max(0, t.get('due', 0) - time.monotonic())
            text = f'剩餘 {remaining/3600:.1f} 小時' if remaining else '待領取結果'
            teams.append(f"隊伍 {t['index']}：任務 {t['quest']}（{text}）")
        self.team_status.set(('｜'.join(teams) or '目前沒有進行中的遠征。') + f"　已自動領獎 {e.get('claimed', 0)} 次")
        try: hours = float(self.hours.get())
        except ValueError: hours = 5
        signature = repr((e.get('revision'), e.get('roles'), e.get('quests'), e.get('level'), hours))
        if signature != self.signature:
            self.signature = signature
            self.tasks.delete(*self.tasks.get_children()); self.roles.delete(*self.roles.get_children())
            lv = self.catalog.get('levels', {}).get(str(e.get('level')))
            for qid in sorted(set(e.get('quests', {}).values())):
                q = self.catalog.get('tasks', {}).get(str(qid))
                if q and lv and duration(q, lv) > hours * 3600:
                    self.tasks.insert('', 'end', values=(qid, f'{duration(q, lv)/3600:.2f}', q['faith_cost']))
                elif qid and not q:
                    self.tasks.insert('', 'end', values=(qid, '缺資料', '待同步'))
            for r in sorted(e.get('roles', {}).values(), key=lambda r: r['index']):
                name = CAT['npcs'].get(str(r['npc_id']), {}).get('name', f"夥伴 {r['npc_id']}")
                self.roles.insert('', 'end', values=(name, r['faith'], '閒置' if r['state'] == 0 else '遠征中'))
        self.note.set('缺少官方任務／等級資料，目前無法自動派遣。' if not self.catalog.get('tasks') else
                      '只從駐紮所閒置夥伴挑選；未支援的條件會跳過。領獎前檢查背包空間，回覆與物品入包確認後才繼續。')
