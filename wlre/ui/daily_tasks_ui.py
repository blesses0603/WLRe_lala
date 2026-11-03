"""Daily/weekly task progress, guarded claims and explicit existing destinations."""
import tkinter as tk
from tkinter import ttk
from wlre.ui.layout import scroll_table


class DailyTaskPanel(ttk.Frame):
    def __init__(self,parent,app,cycle):
        super().__init__(parent,padding=12)
        self.app=app;self.cycle=cycle;self.rows={};self.live=False;self.signature=None
        self.enabled=tk.BooleanVar(value=True);self.status=tk.StringVar();self.details=tk.StringVar()
        self.value=tk.StringVar();self.chests=tk.StringVar()
        bar=ttk.Frame(self);bar.pack(fill='x',pady=(0,8))
        self.auto=ttk.Checkbutton(bar,text='自動領取已達標任務與活躍寶箱',variable=self.enabled,
                                command=lambda:self.act('auto',enabled=self.enabled.get()))
        self.auto.pack(side='left')
        self.claim_all=ttk.Button(bar,text='領取可領項目',command=lambda:self.act('claim_ready'))
        self.claim_all.pack(side='right')
        ttk.Label(self,textvariable=self.value,style='Section.TLabel').pack(anchor='w',pady=4)
        frame,self.tree=scroll_table(self,('name','progress','condition','state'),
                                    ('任務','進度','條件','狀態'),(300,80,110,100))
        frame.pack(fill='both',expand=True,pady=6);self.tree.configure(height=5)
        self.tree.bind('<<TreeviewSelect>>',lambda _:self.select())
        actions=ttk.Frame(self);actions.pack(fill='x',pady=4)
        self.claim=ttk.Button(actions,text='領取選取任務',command=self.claim_selected)
        self.claim.pack(side='left')
        self.go=ttk.Button(actions,text='開啟相關功能',command=self.open_destination)
        self.go.pack(side='left',padx=8)
        self.chest=ttk.Button(actions,text='領取活躍寶箱',command=lambda:self.act('chest',cycle=self.cycle))
        self.chest.pack(side='right')
        ttk.Label(self,textvariable=self.details,wraplength=760).pack(anchor='w',fill='x',pady=4)
        ttk.Label(self,textvariable=self.chests,wraplength=760).pack(anchor='w',fill='x',pady=4)
        ttk.Label(self,textvariable=self.status,wraplength=760,style='Muted.TLabel').pack(anchor='w',fill='x',pady=4)
        self.render({})

    def act(self,action,**fields):self.app.send(dict(type='daily_tasks',action=action,**fields))

    def claim_selected(self):
        selected=self.tree.selection()
        if selected:self.act('task',index=int(selected[0]))

    def select(self):
        selected=self.tree.selection();row=self.rows.get(selected[0]) if selected else None
        self.details.set(row['name']+'｜'+row['execution'] if row else '選取任務可查看執行方式；進度由伺服器確認。')
        self.claim.configure(state='normal' if self.live and row and row['eligible'] and not self.blocked else 'disabled')
        self.go.configure(state='normal' if row and (row['condition_kind'] in (7,8,12,16) or
            row['condition_kind']==10 and row['condition_params'][0] in (1,2)) else 'disabled')

    def open_destination(self):
        selected=self.tree.selection();row=self.rows.get(selected[0]) if selected else None
        if not row:return
        kind=row['condition_kind']
        if kind in (10,16):
            panel=self.app.benefits_panel
            panel.tabs.select(panel.guild_panel if kind==10 else panel.cube)
        else:self.app.open_feature({7:'alchemy',8:'crafting',12:'instance'}[kind])

    def render(self,state):
        d=state.get('daily_tasks',{});self.live=self.app.live_active and state.get('phase')=='world_ready'
        signature=(repr(d),self.live,state.get('automation',{}).get('enabled',True))
        if signature==self.signature:return
        self.signature=signature
        self.blocked=bool(d.get('pending') or d.get('uncertain'))
        self.enabled.set(d.get('enabled',True));self.auto.configure(state='normal' if self.live else 'disabled')
        prefix='daily_' if self.cycle==1 else 'weekly_';title='每日' if self.cycle==1 else '每週'
        value=d.get(prefix+'value');group=d.get(prefix+'group')
        self.value.set(f'{title}活躍值：{value if value is not None else "等待同步"}｜群組：{group if group is not None else "等待同步"}')
        rows=[r for r in d.get('rows',[]) if r['cycle']==self.cycle]
        selection=self.tree.selection();self.tree.delete(*self.tree.get_children());self.rows={}
        for row in rows:
            key=str(row['index']);self.rows[key]=row
            progress=f'{row["progress"]}/{row["goal"]}' if row['progress'] is not None and row['goal'] else '待確認'
            status='已領取' if row['received'] else '可領取' if row['eligible'] else '進行中' if row['goal'] else '條件待支援'
            self.tree.insert('','end',iid=key,values=(row['name'],progress,row['condition'],status))
        if selection and selection[0] in self.rows:self.tree.selection_set(selection[0])
        chests=[r for r in d.get('chests',[]) if r['cycle']==self.cycle]
        self.chests.set('活躍寶箱：'+'、'.join(f'{r["value"]}分'+('活動' if r['kind'] in (2,4) else '')+
                        ('已領' if r['received'] else '可領' if r['eligible'] else '未達標') for r in chests)
                        if chests else '活躍寶箱：等待同版官方資料與進度')
        ready=self.live and d.get('ready') and d.get('groups_ready') and d.get('catalog_ready') and not self.blocked
        self.claim_all.configure(state='normal' if ready else 'disabled')
        self.chest.configure(state='normal' if ready and any(r['eligible'] for r in chests) else 'disabled')
        note=d.get('status','等待官方每日任務 Runtime 與伺服器進度')
        if not state.get('automation',{}).get('enabled',True):note='全域自動接續已暫停；每日任務自動領獎暫停'
        self.status.set(note);self.select()
