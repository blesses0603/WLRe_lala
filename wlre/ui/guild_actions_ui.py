"""Guild automation controls: explicit type, daily target and bounded gold spend."""
import tkinter as tk
from tkinter import ttk

OPTIONS={'初級捐獻':8,'中級捐獻':9,'高級捐獻':10}


class GuildActionsPanel(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,padding=16);self.app=app;self.signature=None;self.config_identity=None
        self.sign=tk.BooleanVar(value=True);self.donate=tk.BooleanVar(value=True)
        self.kind=tk.StringVar(value='初級捐獻');self.target=tk.StringVar(value='3');self.budget=tk.StringVar(value='450')
        self.summary=tk.StringVar();self.progress=tk.StringVar();self.status=tk.StringVar()
        ttk.Label(self,text='組織自動簽到與捐獻',style='Heading.TLabel').pack(anchor='w',pady=(0,12))
        ttk.Label(self,textvariable=self.summary,wraplength=760).pack(anchor='w',pady=6)
        checks=ttk.Frame(self);checks.pack(fill='x',pady=10)
        ttk.Checkbutton(checks,text='自動簽到',variable=self.sign).pack(side='left')
        ttk.Checkbutton(checks,text='自動捐獻',variable=self.donate).pack(side='left',padx=20)
        form=ttk.Frame(self);form.pack(fill='x',pady=8)
        for i,text in enumerate(('捐獻方案','每日總目標','金幣上限（本輪）')):
            ttk.Label(form,text=text).grid(row=i,column=0,sticky='w',pady=8,padx=(0,12))
        self.combo=ttk.Combobox(form,textvariable=self.kind,values=tuple(OPTIONS),state='readonly',width=22)
        self.combo.grid(row=0,column=1,sticky='w')
        ttk.Spinbox(form,from_=1,to=5,textvariable=self.target,width=12).grid(row=1,column=1,sticky='w')
        ttk.Entry(form,textvariable=self.budget,width=22).grid(row=2,column=1,sticky='w')
        bar=ttk.Frame(self);bar.pack(fill='x',pady=12)
        self.apply=ttk.Button(bar,text='套用設定',command=self.apply_settings);self.apply.pack(side='left')
        self.pause=ttk.Button(bar,text='暫停組織自動操作',command=lambda:self.app.send(dict(type='guild_actions',action='pause')))
        self.pause.pack(side='left',padx=8)
        self.sign_button=ttk.Button(bar,text='立即簽到',command=lambda:self.app.send(dict(type='guild_actions',action='sign')))
        self.sign_button.pack(side='left',padx=8)
        self.donate_button=ttk.Button(bar,text='捐獻一次',command=lambda:self.app.send(dict(type='guild_actions',action='donate')))
        self.donate_button.pack(side='left')
        ttk.Label(self,textvariable=self.progress,wraplength=760).pack(anchor='w',pady=8)
        ttk.Label(self,textvariable=self.status,wraplength=760,style='Muted.TLabel').pack(anchor='w',pady=8)
        ttk.Label(self,text='自動捐獻僅允許官方資料確認的金幣／免費方案；中、高級若需鑽石會拒絕執行。\n'
                  '每日目標包含伺服器已記錄的捐獻；重新登入或伺服器日更會開始新一輪額度。\n'
                  '關閉視窗仍繼續；套用設定不會清除未確認操作或已要求額度。',
                  wraplength=760).pack(anchor='w',pady=8)
        self.render({})

    def apply_settings(self):
        try:target,budget=int(self.target.get()),int(self.budget.get());sell=OPTIONS[self.kind.get()]
        except (ValueError,KeyError):self.status.set('請輸入正確的捐獻方案、整數次數及金幣上限');return
        self.app.send(dict(type='guild_actions',action='settings',sign_enabled=self.sign.get(),
                           donate_enabled=self.donate.get(),sell_id=sell,target=target,budget=budget))

    def render(self,state):
        d=state.get('guild_actions',{});g=state.get('guild',{});live=self.app.live_active and state.get('phase')=='world_ready'
        signature=(repr(d),repr(g),live,state.get('automation',{}).get('enabled',True))
        if signature==self.signature:return
        self.signature=signature
        config=(d.get('settings_revision',0),d.get('role'),d.get('guild'))
        if self.config_identity!=config:
            self.config_identity=config
            self.sign.set(d.get('sign_enabled',True));self.donate.set(d.get('donate_enabled',True))
            self.target.set(str(d.get('target',3)));self.budget.set(str(d.get('budget',450)))
            self.kind.set(next((k for k,v in OPTIONS.items() if v==d.get('sell_id',8)),'初級捐獻'))
        label={None:'等待同步',0:'等待明確簽到狀態',1:'可簽到',2:'今日已簽到',3:'新成員今日不可簽到'}
        self.summary.set('組織：'+g.get('name','尚未同步')+'｜簽到：'+label.get(d.get('sign_state'),'未知'))
        done=d.get('donated');price=d.get('price');remaining=d.get('remaining')
        self.progress.set(f'今日已捐獻：{done if done is not None else "等待同步"}／目標 {d.get("target",3)} 次｜'
                          f'剩餘 {remaining if remaining is not None else "待確認"} 次\n'
                          f'目前每次價格：{price if price is not None else "等待官方資料"} 金幣｜'
                          f'已要求額度 {d.get("reserved",0)}／已確認扣款 {d.get("confirmed",0)}／上限 {d.get("budget",450)}')
        blocked=d.get('pending') or d.get('uncertain')
        self.apply.configure(state='normal' if live and not d.get('pending') else 'disabled')
        self.pause.configure(state='normal' if live else 'disabled')
        self.sign_button.configure(state='normal' if live and d.get('sign_state')==1 and not blocked else 'disabled')
        self.donate_button.configure(state='normal' if live and d.get('allow') and d.get('catalog_ready') and not blocked else 'disabled')
        note=d.get('status','等待組織與消費狀態同步')
        if not state.get('automation',{}).get('enabled',True):note='全域自動接續已暫停；組織自動操作暫停'
        self.status.set(note)
