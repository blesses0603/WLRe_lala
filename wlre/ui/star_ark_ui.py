"""Star Ark status, sequential daily automation and server-provided questions."""
import tkinter as tk
from tkinter import ttk
from wlre.ui.layout import scroll_table


class StarArkPanel(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,padding=12);self.app=app;self.signature=None;self.config_identity=None;self.rows={}
        self.enabled=tk.BooleanVar(value=True);self.dispatch=tk.BooleanVar(value=True);self.fights=tk.BooleanVar(value=True)
        self.hours=tk.StringVar(value='1');self.budget=tk.StringVar(value='120')
        self.summary=tk.StringVar();self.status=tk.StringVar();self.question=tk.StringVar()
        self.columnconfigure(0,weight=1)
        self.rowconfigure(5,weight=2,minsize=70)
        self.rowconfigure(6,weight=1,minsize=65)
        ttk.Label(self,text='星之方舟',style='Heading.TLabel').grid(row=0,column=0,sticky='w',pady=(0,4))
        self.summary_label=ttk.Label(self,textvariable=self.summary,wraplength=720,width=1)
        self.summary_label.grid(row=1,column=0,sticky='ew',pady=3)
        bar=ttk.Frame(self);bar.grid(row=2,column=0,sticky='ew',pady=3)
        for text,var in (('自動接續每日方舟任務',self.enabled),('派遣情報員',self.dispatch),('戰鬥事件',self.fights)):
            ttk.Checkbutton(bar,text=text,variable=var).pack(side='left',padx=(0,12))
        form=ttk.Frame(self);form.grid(row=3,column=0,sticky='ew',pady=3)
        ttk.Label(form,text='採集小時').pack(side='left')
        ttk.Spinbox(form,from_=1,to=6,textvariable=self.hours,width=5).pack(side='left',padx=8)
        ttk.Label(form,text='星力上限（本次登入）').pack(side='left')
        ttk.Entry(form,textvariable=self.budget,width=10).pack(side='left',padx=8)
        actions=ttk.Frame(self);actions.grid(row=4,column=0,sticky='ew',pady=3)
        self.apply=ttk.Button(actions,text='套用設定',command=self.settings);self.apply.pack(side='left')
        self.pause=ttk.Button(actions,text='暫停',command=lambda:self.act('pause'));self.pause.pack(side='left',padx=8)
        self.send=ttk.Button(actions,text='派遣一次',command=lambda:self.act('dispatch'));self.send.pack(side='left')
        self.event_button=ttk.Button(actions,text='執行選取事件',command=self.execute)
        self.event_button.pack(side='left',padx=8)
        ttk.Button(actions,text='功能限制',command=self.toggle_help).pack(side='right')
        frame,self.tree=scroll_table(self,('name','planet','kind','execution'),
                                    ('事件','星球','類型','執行方式'),(220,55,75,340),height=3)
        frame.grid(row=5,column=0,sticky='nsew',pady=4)
        self.tree.bind('<<TreeviewSelect>>',lambda _:self.selection())
        self.question_frame=ttk.Frame(self)
        self.question_frame.grid(row=6,column=0,sticky='nsew',pady=4)
        self.question_frame.columnconfigure(0,weight=1);self.question_frame.rowconfigure(0,weight=1)
        self.question_text=tk.Text(self.question_frame,height=3,width=1,wrap='word',state='disabled',
                                  background='#16364b',foreground='#eff7ff',relief='flat',
                                  borderwidth=0,highlightthickness=0,padx=8,pady=6)
        self.question_text.grid(row=0,column=0,sticky='nsew')
        self.question_scroll=ttk.Scrollbar(self.question_frame,orient='vertical',command=self.question_text.yview)
        self.question_scroll.grid(row=0,column=1,sticky='ns')
        self.question_text.configure(yscrollcommand=self.question_scroll.set)
        self.answer_frame=ttk.Frame(self);self.answer_frame.grid(row=7,column=0,sticky='ew',pady=3)
        self.answers=[]
        for i in range(1,5):
            b=ttk.Button(self.answer_frame,text=f'回答選項 {i}',command=lambda i=i:self.act('answer',index=i))
            b.grid(row=0,column=i-1,sticky='ew',padx=(0,6));self.answers.append(b)
            self.answer_frame.columnconfigure(i-1,weight=1)
        self.status_label=ttk.Label(self,textvariable=self.status,wraplength=720,width=1,style='Muted.TLabel')
        self.status_label.grid(row=8,column=0,sticky='ew',pady=4)
        self.help_label=ttk.Label(self,text='派遣使用第一星球的一名空閒情報員，依官方價格與技能計算星力。\n'
                  '一般戰鬥沿用已啟用的自動戰鬥；主線、交付物品、商人購買不自動代做。\n'
                  '未知問答需選擇答案；僅重用伺服器確認答對的答案，不付費刷新、加速或升級技能。',
                  wraplength=720,width=1)
        self.help_label.grid(row=9,column=0,sticky='ew',pady=3);self.help_label.grid_remove()
        for label in (self.summary_label,self.status_label,self.help_label):
            label.bind('<Configure>',lambda event,w=label:w.configure(wraplength=max(120,event.width)))
        self.render({})

    def act(self,action,**values):self.app.send(dict(type='star_ark',action=action,**values))

    def toggle_help(self):
        if self.help_label.winfo_manager():self.help_label.grid_remove()
        else:self.help_label.grid()

    def settings(self):
        try:hours,budget=int(self.hours.get()),int(self.budget.get())
        except ValueError:self.status.set('請輸入整數小時與星力上限');return
        self.act('settings',enabled=self.enabled.get(),dispatch_enabled=self.dispatch.get(),
                 fights_enabled=self.fights.get(),hours=hours,budget=budget)

    def selection(self):
        selected=self.tree.selection();row=self.rows.get(selected[0]) if selected else None
        self.event_button.configure(text='問答進行中，請選下方答案' if self.awaiting_answer else '執行選取事件',
            state='normal' if self.live and not self.blocked and row
            and not row['main'] and row['kind'] in (1,3) else 'disabled')

    def execute(self):
        selected=self.tree.selection();row=self.rows.get(selected[0]) if selected else None
        if row and not row['main'] and row['kind'] in (1,3):
            self.act('fight' if row['kind']==1 else 'question',index=row['index'])

    def render(self,state):
        d=state.get('star_ark',{});self.live=self.app.live_active and state.get('phase')=='world_ready'
        signature=(repr(d),self.live,state.get('automation',{}).get('enabled',True))
        if signature==self.signature:return
        self.signature=signature;self.blocked=bool(d.get('pending') or d.get('uncertain'))
        pending=d.get('pending') or {};question=d.get('question')
        self.awaiting_answer=bool(question and question['selected'] is None and pending.get('kind')=='question' and not d.get('uncertain'))
        config=d.get('role'),d.get('settings_revision',0),d.get('catalog_token')
        if config!=self.config_identity:
            self.config_identity=config
            for var,key in ((self.enabled,'enabled'),(self.dispatch,'dispatch_enabled'),(self.fights,'fights_enabled')):
                var.set(d.get(key,True))
            self.hours.set(str(d.get('hours',1)));self.budget.set(str(d.get('budget',120)))
        ship=d.get('ship',{});coin=d.get('starcoin',{});q=d.get('quote')
        amount=coin.get('amount') if coin.get('reliable') else '待同步'
        self.summary.set(f'已探索至星球 {d.get("planet", "待同步")}｜情報員 {len(d.get("agents",{}))} 名｜星力 {amount}\n'
            f'搜索艇：{"採集中" if ship.get("total") else "空閒／待同步"}｜'
            f'可派遣價格：{q["price"] if q else "待確認"}｜'
            f'已要求／已確認／上限：{d.get("reserved",0)}／{d.get("confirmed",0)}／{d.get("budget",120)} 星力')
        self.apply.configure(state='normal' if self.live and not d.get('pending') else 'disabled')
        self.pause.configure(state='normal' if self.live else 'disabled')
        self.send.configure(state='normal' if self.live and q and not self.blocked else 'disabled')
        selected=self.tree.selection();self.tree.delete(*self.tree.get_children());self.rows={}
        for row in d.get('rows',[]):
            key=f'{int(row["main"])}:{row["index"]}';self.rows[key]=row
            self.tree.insert('','end',iid=key,values=(row['name'],row['planet'],
                {1:'戰鬥',2:'交付物品',3:'問答',4:'商人'}[row['kind']],row['execution']))
        if selected and selected[0] in self.rows:self.tree.selection_set(selected[0])
        self.selection()
        question=d.get('question');pending=d.get('pending') or {}
        self.question.set(question.get('text','等待同版問答文字')+'\n'+'\n'.join(f'{i+1}. {text}' for i,text in enumerate(question['labels']))
                          if question else '選取問答事件可查看伺服器題目。')
        content=self.question.get()
        if content!=self.question_text.get('1.0','end-1c'):
            self.question_text.configure(state='normal')
            self.question_text.delete('1.0','end');self.question_text.insert('1.0',content)
            self.question_text.configure(state='disabled');self.question_text.yview_moveto(0)
        for i,b in enumerate(self.answers):
            b.configure(text=f'回答選項 {i+1}',state='normal'
                if self.live and question and question['selected'] is None and pending.get('kind')=='question'
                and not d.get('uncertain') else 'disabled')
        note=d.get('status','等待星之方舟同步')
        if not state.get('automation',{}).get('enabled',True):note='全域自動接續已暫停；已送出操作仍等待確認'
        self.status.set(note)
