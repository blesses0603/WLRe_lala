"""Expedition overview and opt-in automatic dispatch preferences."""
import json
import time
import tkinter as tk
from tkinter import ttk, messagebox

from wlre.services.expedition import preferences, validate, faith_gain, duration, recovery_stock, choose_members
from wlre.services.expedition_data import data_root, load_catalog
from wlre.services.items.combat_resources import CAT, item_name
from wlre.storage.atomic import file_lock, write_json
from wlre.ui.layout import heading, scroll_table
from wlre.ui.expedition_display import task_name, time_text, rewards_text


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
        self.item = tk.StringVar(value='自動從背包選擇')
        self.selected_item_id = 0
        self.items = {'自動從背包選擇': 0}
        self.item_combo = ttk.Combobox(row, textvariable=self.item, values=list(self.items), state='readonly', width=28)
        self.item_combo.pack(side='left', fill='x', expand=True, padx=6)
        self.start_button = ttk.Button(row, text='啟動自動派遣', command=self.start)
        self.start_button.pack(side='left')
        ttk.Button(row, text='停止', command=lambda: app.send({'type': 'stop_expedition'})).pack(side='left', padx=4)
        ttk.Button(row, text='儲存', command=self.save).pack(side='left')
        body = ttk.Frame(self)
        body.pack(fill='both', expand=True, pady=4)
        body.columnconfigure(0, weight=3); body.columnconfigure(1, weight=2); body.rowconfigure(1, weight=1)
        ttk.Label(body, text='可用任務（依設定門檻篩選；顯示等級減免後時間）').grid(row=0, column=0, sticky='w')
        ttk.Label(body, text='駐紮所夥伴').grid(row=0, column=1, sticky='w')
        frame, self.tasks = scroll_table(body, ('name', 'duration', 'rewards'),
            ('任務名稱', '所需時間', '任務獎勵'), (150, 100, 270))
        frame.grid(row=1, column=0, sticky='nsew', padx=(0, 8))
        self.task_rows = {}
        self.task_detail = tk.StringVar(value='選取任務可查看完整獎勵與派遣條件。')
        self.tasks.bind('<<TreeviewSelect>>', lambda event: self.show_task())
        frame, self.roles = scroll_table(body, ('name', 'faith', 'state'), ('夥伴', '好友度', '狀態'), (110, 55, 65))
        frame.grid(row=1, column=1, sticky='nsew')
        ttk.Label(self, textvariable=self.task_detail, wraplength=760).pack(fill='x', pady=3)
        self.note = tk.StringVar()
        self.team_status = tk.StringVar()
        ttk.Label(self, textvariable=self.team_status, wraplength=700).pack(fill='x', pady=3)
        ttk.Label(self, textvariable=self.note, style='Muted.TLabel', wraplength=700).pack(fill='x', pady=3)
        self.hours.trace_add('write', self.update_filter)
        self.render({})

    def config(self):
        return validate({'min_hours': float(self.hours.get()), 'faith_min': int(self.faith.get()),
                         'item_id': self.items.get(self.item.get(), self.selected_item_id), 'auto_claim': self.auto_claim.get()})

    def show_task(self):
        selected = self.tasks.selection()
        row = self.task_rows.get(selected[0]) if selected else None
        if row:
            quest, result, seconds = row
            self.task_detail.set(f"{task_name(quest)}｜{time_text(seconds)}｜消耗好友度 {quest['faith_cost']}｜{result}\n{rewards_text(quest)}")
        else:
            self.task_detail.set('選取任務可查看完整獎勵與派遣條件。')

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
            self.selected_item_id = value['item_id']
            self.item.set('')
            self.update_inventory(self.app.snapshot.get('inventory', {}))
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

    def update_inventory(self, inventory):
        selected = self.items.get(self.item.get(), self.selected_item_id)
        self.selected_item_id = selected
        self.items = {'自動從背包選擇': 0}
        for sid, count in sorted(recovery_stock(inventory).items()):
            self.items[f'{item_name(sid)}（+{faith_gain(sid)}，可用 {count}）'] = sid
        if selected and selected not in self.items.values():
            self.items[f'{item_name(selected)}（目前無可用庫存）'] = selected
        self.item_combo.configure(values=list(self.items))
        self.item.set(next(label for label, sid in self.items.items() if sid == selected))

    def render(self, state):
        e = state.get('expedition', {})
        live = self.app.live_active
        if live and self.app._settings_key != self.key:
            self.load_settings(self.app._settings_key)
        self.update_inventory(state.get('inventory', {}))
        self.start_button.configure(state='normal' if live and e.get('ready') and e.get('outpost_ready')
                                    and self.catalog.get('tasks') and not e.get('enabled') and not e.get('uncertain') else 'disabled')
        for control in (self.hours_input, self.faith_input, self.claim_option):
            control.configure(state='disabled' if e.get('enabled') or e.get('pending') else 'normal')
        self.item_combo.configure(state='disabled' if e.get('enabled') or e.get('pending') else 'readonly')
        if live and not e.get('enabled') and not e.get('pending') and not e.get('uncertain'):
            status = (f"已自動檢查伺服器任務與駐紮所資料（{len(set(e.get('quests', {}).values()) - {0})} 筆任務）"
                      if e.get('ready') and e.get('outpost_ready') else '上線後等待伺服器任務與駐紮所資料同步。')
        else:
            status = e.get('status', '等待遠征與駐紮所資料同步。')
        self.status.set(('' if live else '已離線｜') + status)
        teams = []
        for t in e.get('teams', {}).values():
            if not t.get('quest'): continue
            remaining = max(0, t.get('due', 0) - time.monotonic())
            text = f'剩餘 {remaining/3600:.1f} 小時' if remaining else '待領取結果'
            quest = self.catalog.get('tasks', {}).get(str(t['quest']), {})
            teams.append(f"隊伍 {t['index']}：{task_name(quest)}（{text}）")
        self.team_status.set(('｜'.join(teams) or '目前沒有進行中的遠征。') + f"　已自動領獎 {e.get('claimed', 0)} 次")
        try: hours = float(self.hours.get())
        except ValueError: hours = 5
        signature = repr((e.get('revision'), e.get('roles'), e.get('quests'), e.get('teams'),
                          e.get('level'), hours, self.faith.get(), recovery_stock(state.get('inventory', {}))))
        if signature != self.signature:
            self.signature = signature
            selected = self.tasks.selection()
            self.task_rows = {}
            self.tasks.delete(*self.tasks.get_children()); self.roles.delete(*self.roles.get_children())
            lv = self.catalog.get('levels', {}).get(str(e.get('level')))
            busy = {npc for team in e.get('teams', {}).values() if team['quest'] for npc in team['members'] if npc}
            idle = [r for r in e.get('roles', {}).values() if r['state'] == 0 and r['npc_id'] not in busy]
            occupied = {self.catalog.get('tasks', {}).get(str(t['quest']), {}).get('area') for t in e.get('teams', {}).values() if t['quest']}
            for qid in sorted(set(e.get('quests', {}).values())):
                q = self.catalog.get('tasks', {}).get(str(qid))
                if q and lv and duration(q, lv) > hours * 3600 and q['difficulty'] <= lv['difficulty']:
                    try: threshold = int(self.faith.get())
                    except ValueError: threshold = 80
                    members = choose_members(q, idle, threshold)
                    result = ('同區域遠征中' if q['area'] in occupied else
                              '可派遣' if members else '夥伴不足／條件未符')
                    if result == '可派遣' and any(r['faith'] < max(threshold, q['faith_cost']) for r in members):
                        result = '需補好友度'
                    seconds = duration(q, lv)
                    self.task_rows[str(qid)] = (q, result, seconds)
                    self.tasks.insert('', 'end', iid=str(qid), values=(task_name(q), time_text(seconds), rewards_text(q)))
                elif qid and not q:
                    self.tasks.insert('', 'end', iid=str(qid), values=('任務資料待更新', '待更新', '待更新'))
            if selected and self.tasks.exists(selected[0]): self.tasks.selection_set(selected[0])
            self.show_task()
            for r in sorted(e.get('roles', {}).values(), key=lambda r: r['index']):
                name = CAT['npcs'].get(str(r['npc_id']), {}).get('name', f"夥伴 {r['npc_id']}")
                self.roles.insert('', 'end', values=(name, r['faith'], '閒置' if r['state'] == 0 else '遠征中'))
        self.note.set('內建遠征資料不完整，請更新完整程式。' if not self.catalog.get('tasks') else
                      '內建官方遠征資料；上線後自動檢查任務與背包。可與自動戰鬥、徘徊同時啟用。')
