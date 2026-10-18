"""Scrollable quest details and recommended party conditions."""
import tkinter as tk
from tkinter import ttk
from wlre.ui.expedition_display import task_name, time_text, rewards_text


def build_task_detail(self, body):
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


class ExpeditionTaskDetailMixin:
    def update_detail(self, *args):
        self.detail_text.configure(state='normal')
        self.detail_text.delete('1.0', 'end')
        self.detail_text.insert('1.0', self.task_detail.get())
        self.detail_text.configure(state='disabled')

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

