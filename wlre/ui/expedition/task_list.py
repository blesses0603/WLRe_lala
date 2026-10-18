"""Expedition quest list, server-backed filtering and live success estimates."""
import tkinter as tk
from wlre.ui.layout import scroll_table
from wlre.services.expedition import duration
from wlre.ui.expedition_display import task_name, time_text


def build_task_table(self, body):
    frame, self.tasks = scroll_table(body, ('name', 'duration', 'success'),
        ('任務名稱', '所需時間', '預估成功率'), (130, 85, 85), horizontal_scrollbar=False)
    frame.grid(row=1, column=0, sticky='nsew', padx=(0, 8))
    self.task_rows = {}
    self.task_detail = tk.StringVar(value='選取任務可查看完整獎勵與派遣條件。')
    self.tasks.bind('<<TreeviewSelect>>', lambda event: self.show_task())


class ExpeditionTaskListMixin:
    def render_catalog_rows(self, e, hours, minimum, signature):
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
            self.render_companion_rows(e)
