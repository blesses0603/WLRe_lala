"""Build and wire the existing expedition preference controls without changing layout."""
import tkinter as tk
from tkinter import ttk


def build_controls(self, app):
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


def bind_control_changes(self):
    for variable in (self.hours, self.faith, self.min_success, self.auto_claim, self.item):
        variable.trace_add('write', self.preferences_changed)
