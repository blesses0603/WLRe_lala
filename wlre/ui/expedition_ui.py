"""Expedition overview and opt-in automatic dispatch preferences."""
import time
import copy
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk, messagebox

from wlre.services.expedition import preferences, validate, faith_gain, duration, recovery_stock, choose_members
from wlre.services.expedition_data import load_catalog
from wlre.services.items.combat_resources import CAT, item_name
from wlre.storage import expedition_settings
from wlre.ui.layout import heading, scroll_table
from wlre.ui.expedition_display import task_name, time_text, rewards_text
from wlre.services.expedition_teams import success_details


def plan_quests(quests, roles, threshold, npcs):
    result = {}
    for quest in quests:
        team = choose_members(quest, roles, threshold, npcs)
        result[str(quest['id'])] = (team, success_details(quest, team, npcs) if team else {})
    return result


class ExpeditionPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=6)
        self.app = app
        self.key = None
        self.signature = None
        self.loading_settings = False
        self.pending_preferences = None
        self.save_job = None
        self.planner = None
        self.plan_future = None
        self.plan_job = None
        self.plan_key = None
        self.plans = {}
        self.catalog = load_catalog()
        heading(self, '遠征', '自動領獎、補好友度並接續派遣；不使用縮時或支援物品。')
        self.status = tk.StringVar(value='等待遠征與駐紮所資料同步。')
        ttk.Label(self, textvariable=self.status, wraplength=700).pack(fill='x', pady=(0, 4))
        controls = ttk.Frame(self)
        controls.pack(fill='x', pady=3)
        ttk.Label(controls, text='任務時間大於').pack(side='left')
        self.hours = tk.StringVar(value='0')
        self.hours_input = ttk.Spinbox(controls, from_=0, to=24, increment=.5, width=5, textvariable=self.hours)
        self.hours_input.pack(side='left', padx=4)
        ttk.Label(controls, text='小時　好友度低於').pack(side='left')
        self.faith = tk.StringVar(value='80')
        self.faith_input = ttk.Spinbox(controls, from_=1, to=100, width=4, textvariable=self.faith)
        self.faith_input.pack(side='left', padx=4)
        ttk.Label(controls, text='時補充').pack(side='left')
        ttk.Label(controls, text='最低成功率').pack(side='left', padx=(8, 0))
        self.min_success = tk.StringVar(value='75')
        self.success_input = ttk.Spinbox(controls, from_=0, to=100, increment=5, width=4, textvariable=self.min_success)
        self.success_input.pack(side='left', padx=3)
        ttk.Label(controls, text='%').pack(side='left')
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
        for column, weight in enumerate((4, 3, 3)):
            body.columnconfigure(column, weight=weight, uniform='expedition', minsize=0)
        body.rowconfigure(1, weight=1)
        ttk.Label(body, text='可用任務').grid(row=0, column=0, sticky='w')
        ttk.Label(body, text='駐紮所夥伴').grid(row=0, column=1, sticky='w')
        ttk.Label(body, text='任務詳情').grid(row=0, column=2, sticky='w')
        frame, self.tasks = scroll_table(body, ('name', 'duration', 'success'),
            ('任務名稱', '所需時間', '預估成功率'), (130, 85, 85), horizontal_scrollbar=False)
        frame.grid(row=1, column=0, sticky='nsew', padx=(0, 8))
        self.task_rows = {}
        self.task_detail = tk.StringVar(value='選取任務可查看完整獎勵與派遣條件。')
        self.tasks.bind('<<TreeviewSelect>>', lambda event: self.show_task())
        frame, self.roles = scroll_table(body, ('name', 'faith', 'state'),
            ('夥伴', '好友度', '狀態'), (90, 55, 60), horizontal_scrollbar=False)
        frame.grid(row=1, column=1, sticky='nsew', padx=(0, 8))
        detail_frame = ttk.Frame(body)
        detail_frame.grid(row=1, column=2, sticky='nsew')
        detail_frame.rowconfigure(0, weight=1)
        detail_frame.columnconfigure(0, weight=1)
        self.detail_text = tk.Text(detail_frame, width=1, height=4, wrap='word',
                                   state='disabled', borderwidth=0, highlightthickness=0,
                                   background='#142638', foreground='#eff7ff', cursor='arrow',
                                   font=ttk.Style(self).lookup('.', 'font') or 'TkDefaultFont')
        self.detail_text.grid(row=0, column=0, sticky='nsew')
        detail_scroll = ttk.Scrollbar(detail_frame, orient='vertical', command=self.detail_text.yview)
        detail_scroll.grid(row=0, column=1, sticky='ns')
        self.detail_text.configure(yscrollcommand=detail_scroll.set)
        self.task_detail.trace_add('write', self.update_detail)
        self.update_detail()
        self.note = tk.StringVar()
        self.team_status = tk.StringVar()
        ttk.Label(self, textvariable=self.team_status, wraplength=700).pack(fill='x', pady=3)
        ttk.Label(self, textvariable=self.note, style='Muted.TLabel', wraplength=700).pack(fill='x', pady=3)
        for variable in (self.hours, self.faith, self.min_success, self.auto_claim, self.item):
            variable.trace_add('write', self.preferences_changed)
        self.bind('<Destroy>', self.destroyed, add='+')
        self.render({})

    def update_detail(self, *args):
        self.detail_text.configure(state='normal')
        self.detail_text.delete('1.0', 'end')
        self.detail_text.insert('1.0', self.task_detail.get())
        self.detail_text.configure(state='disabled')

    def config(self):
        return validate({'min_hours': float(self.hours.get()), 'faith_min': int(self.faith.get()),
                         'min_success': float(self.min_success.get()),
                         'item_id': self.items.get(self.item.get(), self.selected_item_id), 'auto_claim': self.auto_claim.get()})

    def show_task(self):
        selected = self.tasks.selection()
        row = self.task_rows.get(selected[0]) if selected else None
        if row:
            quest, result, seconds, details = row
            recommendation = []
            for rec in details.get('recommendations', []):
                label = {1:'人數', 2:'指定元素', 3:'排除元素', 4:'指定夥伴', 5:'合計等級', 6:'合計潛能',
                         7:'合計體質', 8:'合計力量', 9:'合計智力', 10:'合計智慧', 11:'合計敏捷',
                         12:'合計轉生階層', 13:'人型夥伴', 14:'獸型夥伴'}.get(rec['condition'][0], '條件')
                met = '達標' if rec['met'] is True else '未達標' if rec['met'] is False else '資料不足'
                recommendation.append(f"{label}：{met}（+{rec['awarded']/10:g}%）")
            self.task_detail.set(f"{task_name(quest)}\n所需時間：{time_text(seconds)}\n消耗好友度：{quest['faith_cost']}\n{result}\n\n任務獎勵\n{rewards_text(quest)}" +
                                 ('\n\n推薦條件\n' + '\n'.join(recommendation) if recommendation else ''))
        else:
            self.task_detail.set('選取任務可查看完整獎勵與派遣條件。')

    def update_filter(self, *args):
        if not self.loading_settings:
            self.render(self.app.snapshot)

    def settings_path(self):
        key = self.app.settings_identity()
        if not key: raise ValueError('請先選擇帳號再儲存遠征設定')
        return expedition_settings.settings_file(key)

    def load_settings(self, key):
        if not self.flush_preferences():raise OSError('前一帳號的遠征設定尚未儲存，未切換帳號')
        value = preferences()
        if key:
            try:
                value = expedition_settings.load(key)
            except (OSError, ValueError) as exc:
                self.status.set('遠征設定讀取失敗：' + str(exc))
                raise
        self.key = key
        self.loading_settings = True
        try:
            self.hours.set(str(value['min_hours'])); self.faith.set(str(value['faith_min']))
            self.min_success.set(str(value['min_success']))
            self.auto_claim.set(value['auto_claim'])
            self.selected_item_id = value['item_id']
            self.item.set('')
            self.update_inventory(self.app.snapshot.get('inventory', {}))
        finally:
            self.loading_settings = False

    def save(self):
        try:
            if not self.flush_preferences():raise OSError('先前遠征設定尚未儲存')
            self.settings_path()
            expedition_settings.save(self.app.settings_identity(), self.config())
            self.status.set('已儲存遠征設定；登入後不會自動啟動。')
        except (OSError, ValueError) as exc:
            messagebox.showerror('遠征設定', str(exc), parent=self.app.root)

    def preferences_changed(self, *args):
        if self.loading_settings: return
        try: value = self.config()
        except ValueError: return  # allow partially typed numbers
        if self.key:
            self.pending_preferences = (self.key, value)
            if self.save_job is not None:
                self.after_cancel(self.save_job)
            self.save_job = self.after(750, self.flush_preferences)
        self.update_filter()

    def flush_preferences(self):
        if self.save_job is not None:
            try: self.after_cancel(self.save_job)
            except tk.TclError: pass
            self.save_job = None
        if self.pending_preferences is None: return True
        key, value = self.pending_preferences
        try:
            expedition_settings.save(key, value)
            self.pending_preferences = None
            return True
        except (OSError, ValueError) as exc:
            self.status.set('遠征設定自動儲存失敗：' + str(exc))
            return False

    def destroyed(self, event):
        if event.widget is not self: return
        self.flush_preferences()
        if self.plan_job is not None:
            try: self.after_cancel(self.plan_job)
            except tk.TclError: pass
        if self.planner is not None: self.planner.shutdown(wait=False, cancel_futures=True)

    def request_plans(self, quests, idle, threshold):
        key = repr(([q['id'] for q in quests], idle, threshold))
        if key == self.plan_key: return
        self.plan_key = key
        self.plans = {}
        if self.plan_future is not None: self.plan_future.cancel()
        if len(idle) <= 10:
            self.plan_future = None
            self.plans = plan_quests(quests, idle, threshold, self.catalog.get('npcs', {}))
            return
        if self.planner is None: self.planner = ThreadPoolExecutor(max_workers=1, thread_name_prefix='expedition-planner')
        self.plan_future = self.planner.submit(plan_quests, quests, copy.deepcopy(idle), threshold, self.catalog.get('npcs', {}))
        if self.plan_job is None: self.plan_job = self.after(50, self.collect_plans)

    def collect_plans(self):
        self.plan_job = None
        if self.plan_future is None: return
        if not self.plan_future.done():
            self.plan_job = self.after(50, self.collect_plans)
            return
        try: self.plans = self.plan_future.result()
        except Exception as exc:
            self.status.set('成功率計算失敗：' + str(exc))
            self.plans = {}
        self.plan_future = None
        self.signature = None
        self.render(self.app.snapshot)

    def start(self):
        try:
            settings = self.config()
            self.save()
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
        loading = self.loading_settings
        self.loading_settings = True
        try: self.item.set(next(label for label, sid in self.items.items() if sid == selected))
        finally: self.loading_settings = loading

    def render(self, state):
        e = state.get('expedition', {})
        live = self.app.live_active
        if live and self.app._settings_key and self.app._settings_key != self.key:
            self.load_settings(self.app._settings_key)
        self.update_inventory(state.get('inventory', {}))
        self.start_button.configure(state='normal' if live and e.get('ready') and e.get('outpost_ready')
                                    and self.catalog.get('tasks') and not e.get('enabled') and not e.get('uncertain') else 'disabled')
        for control in (self.hours_input, self.faith_input, self.claim_option, self.success_input):
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
        except ValueError: hours = 0
        try: minimum = float(self.min_success.get())
        except ValueError: minimum = 75
        signature = repr((e.get('revision'), e.get('roles'), e.get('quests'), e.get('teams'),
                          e.get('level'), hours, self.faith.get(), minimum, recovery_stock(state.get('inventory', {}))))
        if signature != self.signature:
            self.signature = signature
            selected = self.tasks.selection()
            self.task_rows = {}
            self.tasks.delete(*self.tasks.get_children()); self.roles.delete(*self.roles.get_children())
            lv = self.catalog.get('levels', {}).get(str(e.get('level')))
            busy = {npc for team in e.get('teams', {}).values() if team['quest'] for npc in team['members'] if npc}
            idle = [r for r in e.get('roles', {}).values() if r['state'] == 0 and r['npc_id'] not in busy]
            occupied = {self.catalog.get('tasks', {}).get(str(t['quest']), {}).get('area') for t in e.get('teams', {}).values() if t['quest']}
            try: threshold = int(self.faith.get())
            except ValueError: threshold = 80
            visible_quests = [self.catalog['tasks'][str(qid)] for qid in sorted(set(e.get('quests', {}).values()))
                              if str(qid) in self.catalog.get('tasks', {}) and lv
                              and duration(self.catalog['tasks'][str(qid)], lv) > hours * 3600
                              and self.catalog['tasks'][str(qid)]['difficulty'] <= lv['difficulty']]
            self.request_plans(visible_quests, idle, threshold)
            for qid in sorted(set(e.get('quests', {}).values())):
                q = self.catalog.get('tasks', {}).get(str(qid))
                if q and lv and duration(q, lv) > hours * 3600 and q['difficulty'] <= lv['difficulty']:
                    members, details = self.plans.get(str(qid), ([], {}))
                    result = ('同區域遠征中' if q['area'] in occupied else
                              '可派遣' if members else '夥伴不足／條件未符')
                    if result == '可派遣' and any(r['faith'] < max(threshold, q['faith_cost']) for r in members):
                        result = '需補好友度'
                    if members and details['percent'] < minimum:
                        result = f'未達最低成功率 {minimum:g}%'
                    rate = (('至少 ' if not details['complete'] else '') + f"{details['percent']:g}%") if members else '計算中' if self.plan_future is not None else '無可用隊伍'
                    seconds = duration(q, lv)
                    self.task_rows[str(qid)] = (q, result, seconds, details)
                    self.tasks.insert('', 'end', iid=str(qid), values=(task_name(q), time_text(seconds), rate))
                elif qid and not q:
                    self.tasks.insert('', 'end', iid=str(qid), values=('任務資料待更新', '待更新', '待更新'))
            if selected and self.tasks.exists(selected[0]): self.tasks.selection_set(selected[0])
            self.show_task()
            for r in sorted(e.get('roles', {}).values(), key=lambda r: r['index']):
                name = CAT['npcs'].get(str(r['npc_id']), {}).get('name', f"夥伴 {r['npc_id']}")
                self.roles.insert('', 'end', values=(name, r['faith'], '閒置' if r['state'] == 0 else '遠征中'))
        self.note.set('內建遠征資料不完整，請更新完整程式。' if not self.catalog.get('tasks') else
                      '內建官方遠征資料；上線後自動檢查任務與背包。可與自動戰鬥、徘徊同時啟用。')
