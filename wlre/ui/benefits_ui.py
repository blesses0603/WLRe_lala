"""Benefits > Cube presentation; commands are handled by the network thread."""
import time
import tkinter as tk
from tkinter import ttk
from wlre.ui.rounded_notebook import RoundedNotebook
from wlre.ui.daily_tasks_ui import DailyTaskPanel
from wlre.ui.daily_assistant_ui import DailyAssistantPanel


class BenefitsPanel(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,padding=12)
        self.app=app
        self.tabs=RoundedNotebook(self,icons=True)
        self.tabs.pack(fill='both',expand=True)
        self.cube=ttk.Frame(self.tabs,padding=16)
        self.tabs.add(self.cube,text='魔方')
        ttk.Label(self.cube,text='時間魔方',style='Heading.TLabel').pack(anchor='w',pady=(0,14))
        self.enabled=tk.BooleanVar(value=True)
        self.auto=ttk.Checkbutton(self.cube,text='自動開啟已分析完成的魔方',
                                  variable=self.enabled,command=self.set_auto)
        self.auto.pack(anchor='w',pady=(0,14))
        self.count=tk.StringVar();self.analysis=tk.StringVar();self.status=tk.StringVar()
        ttk.Label(self.cube,textvariable=self.count,style='Section.TLabel').pack(anchor='w',pady=6)
        ttk.Label(self.cube,textvariable=self.analysis).pack(anchor='w',pady=6)
        self.open_button=ttk.Button(self.cube,text='開啟魔方',command=self.open_cube)
        self.open_button.pack(anchor='w',pady=14)
        ttk.Label(self.cube,textvariable=self.status,wraplength=590).pack(anchor='w',fill='x',pady=6)
        ttk.Label(self.cube,text='最多儲存 3 次。分析由伺服器自動累積；可開啟時自動送出，關閉視窗仍繼續。',
                  style='Muted.TLabel',wraplength=590).pack(anchor='w',fill='x',pady=6)
        self.daily_panel=DailyTaskPanel(self.tabs,app,1)
        self.weekly_panel=DailyTaskPanel(self.tabs,app,2)
        self.tabs.add(self.daily_panel,text='每日任務')
        self.tabs.add(self.weekly_panel,text='每週任務')
        self.assistant_panel=DailyAssistantPanel(self.tabs,app)
        self.tabs.add(self.assistant_panel,text='每日助手')
        self.render({})
        self.timer=self.after(1000,self.refresh_clock)
        self.bind('<Destroy>',self.cleanup,add='+')

    def cleanup(self,event):
        if event.widget is self:self.after_cancel(self.timer)

    def refresh_clock(self):
        if self.winfo_ismapped():self.render(self.app.snapshot)
        self.timer=self.after(1000,self.refresh_clock)

    def set_auto(self):
        self.app.send(dict(type='time_cube',action='auto',enabled=self.enabled.get()))

    def open_cube(self):
        self.app.send(dict(type='time_cube',action='open'))

    def render(self,state):
        self.assistant_panel.render(state)
        self.daily_panel.render(state)
        self.weekly_panel.render(state)
        cube=state.get('time_cube',{})
        live=self.app.live_active and state.get('phase')=='world_ready'
        self.auto.configure(state='normal' if live else 'disabled')
        self.enabled.set(cube.get('enabled',True))
        count=cube.get('count')
        self.count.set(f'可開啟：{count} / 3' if cube.get('ready') else '可開啟：等待同步')
        deadline=cube.get('deadline')
        if count==3:text='儲存已滿，等待開啟'
        elif deadline is None:text='分析時間：等待伺服器同步'
        else:
            seconds=max(0,int(deadline-time.monotonic()))
            text=(f'分析中：{seconds//3600}時{seconds//60%60:02d}分{seconds%60:02d}秒'
                  if seconds else '等待伺服器確認分析完成')
        self.analysis.set(text)
        status=cube.get('status','等待登入及魔方同步')
        if cube.get('enabled') and not state.get('automation',{}).get('enabled',True):
            status='全域自動接續已暫停；魔方自動開啟暫停'
        self.status.set(status)
        self.open_button.configure(state='normal' if live and cube.get('ready') and count
                                   and not cube.get('pending') and not cube.get('uncertain') else 'disabled')
