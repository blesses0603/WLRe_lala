"""Expedition overview orchestration; presentation is implemented in focused views."""
import time
import tkinter as tk
from tkinter import ttk

from wlre.services.expedition import recovery_stock
from wlre.services.expedition_data import load_catalog
from wlre.ui.layout import heading
from wlre.ui.expedition_display import task_name
from .controls import build_controls, bind_control_changes
from .settings import ExpeditionSettingsMixin
from .planner import ExpeditionPlannerMixin
from .task_list import ExpeditionTaskListMixin, build_task_table
from .team_view import ExpeditionTeamListMixin, build_companion_table
from .task_detail import ExpeditionTaskDetailMixin, build_task_detail


class ExpeditionPanel(
    ExpeditionSettingsMixin, ExpeditionPlannerMixin,
    ExpeditionTaskListMixin, ExpeditionTeamListMixin, ExpeditionTaskDetailMixin,
    ttk.Frame,
):
    def _load_catalog(self):
        return load_catalog()

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
        self.catalog = self._load_catalog()
        heading(self, '遠征', '自動領獎、補好友度並接續派遣；不使用縮時或支援物品。')
        self.status = tk.StringVar(value='等待遠征與駐紮所資料同步。')
        ttk.Label(self, textvariable=self.status, wraplength=700).pack(fill='x', pady=(0, 4))
        build_controls(self, app)
        body = ttk.Frame(self)
        body.pack(fill='both', expand=True, pady=4)
        for column, weight in enumerate((4, 3, 3)):
            body.columnconfigure(column, weight=weight, uniform='expedition', minsize=0)
        body.rowconfigure(1, weight=1)
        ttk.Label(body, text='可用任務').grid(row=0, column=0, sticky='w')
        ttk.Label(body, text='駐紮所夥伴').grid(row=0, column=1, sticky='w')
        ttk.Label(body, text='任務詳情').grid(row=0, column=2, sticky='w')
        build_task_table(self, body)
        build_companion_table(self, body)
        build_task_detail(self, body)
        self.note = tk.StringVar()
        self.team_status = tk.StringVar()
        ttk.Label(self, textvariable=self.team_status, wraplength=700).pack(fill='x', pady=3)
        ttk.Label(self, textvariable=self.note, style='Muted.TLabel', wraplength=700).pack(fill='x', pady=3)
        bind_control_changes(self)
        self.bind('<Destroy>', self.destroyed, add='+')
        self.render({})

    def destroyed(self, event):
        if event.widget is not self: return
        self.flush_preferences()
        if self.plan_job is not None:
            try: self.after_cancel(self.plan_job)
            except tk.TclError: pass
        if self.planner is not None: self.planner.shutdown(wait=False, cancel_futures=True)

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
        self.render_catalog_rows(e, hours, minimum, signature)
        self.note.set('內建遠征資料不完整，請更新完整程式。' if not self.catalog.get('tasks') else
                      '內建官方遠征資料；上線後自動檢查任務與背包。可與自動戰鬥、徘徊同時啟用。')
