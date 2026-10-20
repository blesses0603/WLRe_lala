"""Small, fixed team and auto-alchemy pages; update only relevant state."""
import json,time
import tkinter as tk
from tkinter import ttk,messagebox
from wlre.services.battle.party import own_team, player_name
from wlre.services.items.alchemy import modes, prepare, material_problem
from wlre.services.items.combat_resources import item_name
from wlre.ui.crafting_browser import ItemIcons
from wlre.ui.layout import heading,scroll_table


class PartyPanel(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,padding=6);self.app=app;self.signature=None
        self.guard_host=ttk.Frame(self,width=300)
        self.guard_host.pack(side='right',fill='y',padx=(12,0));self.guard_host.pack_propagate(False)
        body=ttk.Frame(self);body.pack(side='left',fill='both',expand=True)
        heading(body,'隊伍管理')
        self.status=tk.StringVar(value='尚無隊伍資料');self.membership=tk.StringVar(value='目前未組隊')
        ttk.Label(body,textvariable=self.membership).pack(anchor='w')
        bar=ttk.Frame(body);bar.pack(fill='x',pady=(4,2))
        ttk.Label(bar,text='目標').pack(side='left')
        self.target=tk.StringVar();self.targets={}
        self.target_combo=ttk.Combobox(bar,textvariable=self.target,width=23);self.target_combo.pack(side='left',fill='x',expand=True,padx=4)
        self.flag=ttk.Button(bar,text='開啟組隊',command=lambda:self.act('flag',enabled=True));self.flag.pack(side='right')
        buttons=ttk.Frame(body);buttons.pack(fill='x',pady=2)
        self.invite=ttk.Button(buttons,text='邀請組隊',command=lambda:self.target_action('invite'));self.invite.pack(side='left')
        self.apply=ttk.Button(buttons,text='申請入隊',command=lambda:self.target_action('apply'));self.apply.pack(side='left',padx=4)
        self.leave=ttk.Button(buttons,text='離隊／解散',command=self.leave_team);self.leave.pack(side='left')
        area=ttk.Frame(body);area.pack(fill='both',expand=True,pady=4)
        area.columnconfigure(0,weight=1);area.columnconfigure(1,weight=1);area.rowconfigure(1,weight=1)
        ttk.Label(area,text='隊伍成員').grid(row=0,column=0,sticky='w');ttk.Label(area,text='待確認邀請／申請').grid(row=0,column=1,sticky='w')
        members_frame,self.members=scroll_table(area,('name','role'),('名稱／ID','身分'),(170,65),scrollbars=False);members_frame.grid(row=1,column=0,sticky='nsew',padx=(0,6))
        requests_frame,self.requests=scroll_table(area,('kind','name'),('請求','名稱／ID'),(85,150),scrollbars=False);requests_frame.grid(row=1,column=1,sticky='nsew')
        self.requests.bind('<<TreeviewSelect>>',lambda event:self.update_buttons())
        self.members.bind('<<TreeviewSelect>>',lambda event:self.update_buttons())
        bar=ttk.Frame(body);bar.pack(fill='x')
        self.kick=ttk.Button(bar,text='移除隊員',command=lambda:self.member_action('kick'));self.kick.pack(side='left')
        self.leader=ttk.Button(bar,text='轉交隊長',command=lambda:self.member_action('leader'));self.leader.pack(side='left',padx=4)
        self.no=ttk.Button(bar,text='拒絕',command=lambda:self.respond(2));self.no.pack(side='right')
        self.yes=ttk.Button(bar,text='接受',command=lambda:self.respond(1));self.yes.pack(side='right',padx=4)
        ttk.Label(body,textvariable=self.status,wraplength=630).pack(fill='x',pady=(4,0))
        self.render({})
    @staticmethod
    def tree(parent,columns,headings,widths):
        tree=ttk.Treeview(parent,columns=columns,show='headings',height=3,selectmode='browse')
        for key,label,width in zip(columns,headings,widths):tree.heading(key,text=label);tree.column(key,width=width,minwidth=40)
        return tree
    def act(self,action,**kw):self.app.send({'type':'team','action':action,**kw})
    def target_action(self,action):
        value=self.target.get().strip()
        try:rid=self.targets.get(value) or int(value)
        except ValueError:messagebox.showinfo('組隊','請從附近玩家選取，或輸入確切角色ID。',parent=self.app.root);return
        self.act(action,role_id=rid)
    def member_action(self,action):
        selected=self.members.selection()
        if not selected:return
        rid=int(selected[0]);name=player_name(self.app.snapshot,rid)
        if messagebox.askyesno('組隊',f'確認對「{name}（{rid}）」執行'+('移除隊員？' if action=='kick' else '轉交隊長？'),parent=self.app.root):self.act(action,role_id=rid)
    def leave_team(self):
        if messagebox.askyesno('離隊／解散','確認離開目前隊伍？隊長離隊會解散隊伍。',parent=self.app.root):self.act('leave')
    def respond(self,answer):
        selected=self.requests.selection()
        if selected:self.act('respond',request=selected[0],answer=answer)
    def update_buttons(self):
        state=self.app.snapshot;party=state.get('party',{});team=own_team(state);pid=state.get('player',{}).get('role_id');live=self.app.live_active
        selected=self.members.selection();is_leader=team and team['leader_id']==pid
        def enabled(button,value):button.configure(state='normal' if value and live else 'disabled')
        enabled(self.invite,not team or is_leader and len(team['members'])<4);enabled(self.apply,not team);enabled(self.leave,team)
        enabled(self.kick,is_leader and selected and int(selected[0])!=pid);enabled(self.leader,is_leader and selected and int(selected[0])!=pid)
        selected=self.requests.selection();request=party.get('requests',{}).get(selected[0]) if selected else None
        pending=request and request['status']=='pending' and request['expires']>time.monotonic()
        enabled(self.yes,pending);enabled(self.no,pending);enabled(self.flag,True)
    def render(self,state):
        party=state.get('party',{});signature=(json.dumps(party,sort_keys=True),state.get('player',{}).get('scene'),self.app.live_active)
        if signature==self.signature:return
        self.signature=signature;team=own_team(state)
        self.membership.set(f"隊長：{player_name(state,team['leader_id'])}｜成員 {len(team['members'])}/4" if team else '目前未組隊｜目標欄可選附近玩家或輸入確切角色ID')
        self.status.set(party.get('status','尚無隊伍資料'))
        selected=self.members.selection();self.members.delete(*self.members.get_children())
        if team:
            for rid in team['members']:self.members.insert('','end',iid=str(rid),values=(f'{player_name(state,rid)}（{rid}）','隊長' if rid==team['leader_id'] else '隊員'))
        if selected and self.members.exists(selected[0]):self.members.selection_set(selected[0])
        selected=self.requests.selection();self.requests.delete(*self.requests.get_children())
        for key,request in party.get('requests',{}).items():
            kind={'team_invite':'邀請你入隊','team_application':'申請加入','team_leader_offer':'隊長指派'}[request['type']]
            if request['status']!='pending':kind='回覆中'
            self.requests.insert('','end',iid=key,values=(kind,f"{player_name(state,request['role_id'])}（{request['role_id']}）"))
        if selected and self.requests.exists(selected[0]):self.requests.selection_set(selected[0])
        elif self.requests.get_children():self.requests.selection_set(self.requests.get_children()[0])
        self.targets={f"{v['name']}（{v['role_id']}）":v['role_id'] for v in party.get('nearby',{}).values() if v['scene']==state.get('player',{}).get('scene')}
        self.target_combo.configure(values=tuple(self.targets));self.flag.configure(text='關閉組隊' if party.get('enabled_requested',party.get('enabled')) else '開啟組隊',command=lambda:self.act('flag',enabled=not party.get('enabled_requested',party.get('enabled'))))
        count=sum(v['status']=='pending' for v in party.get('requests',{}).values())
        label=f'組隊（{count}）' if count else '組隊'
        launcher=getattr(self.app,'feature_launchers',{}).get('party')
        if launcher is not None and self.app.left_tabs.tab(launcher,'text')!=label:
            self.app.left_tabs.tab(launcher,text=label)
        self.update_buttons()


class AlchemyPanel(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,padding=6);self.app=app;self.signature=None;self.choices={};self.icons=ItemIcons(self);self.item_previews=[];self.preview_images=[]
        self.bind('<Destroy>',self.cleanup_icons,add='+')
        self.mode=tk.StringVar(value='無技能');self.runs=tk.StringVar(value='1');self.status=tk.StringVar(value='先同步包包，再選擇材料')
        title=ttk.Frame(self);title.pack(fill='x')
        heading(title,'煉金','選擇材料與次數，預覽消耗後才會開始。')
        content=ttk.Frame(self);content.pack(fill='both',expand=True)
        side=ttk.Frame(content,width=220,padding=10);side._surface_fill=(13,32,48,200)
        side.pack(side='right',fill='y',padx=(12,0));side.pack_propagate(False)
        form=ttk.Frame(content);form.pack(side='left',fill='both',expand=True);form.columnconfigure(1,weight=1)
        options=ttk.Frame(form);options.grid(row=0,column=0,columnspan=3,sticky='ew',pady=(0,12))
        ttk.Label(options,text='煉金術').pack(side='left');self.mode_combo=ttk.Combobox(options,textvariable=self.mode,values=('無技能',),state='readonly',width=9);self.mode_combo.pack(side='left',padx=6)
        ttk.Label(options,text='執行次數').pack(side='left',padx=(12,0));self.run_entry=ttk.Spinbox(options,from_=1,to=999,textvariable=self.runs,width=5);self.run_entry.pack(side='left',padx=6)
        ttk.Label(form,text='材料格',style='Section.TLabel').grid(row=1,column=0,sticky='w')
        ttk.Label(form,text='包包物品',style='Section.TLabel').grid(row=1,column=1,sticky='w')
        ttk.Label(form,text='每次數量',style='Section.TLabel').grid(row=1,column=2)
        self.slots=[]
        for i in range(5):
            var=tk.StringVar();count=tk.StringVar(value='1');combo=ttk.Combobox(form,textvariable=var,state='readonly',width=28)
            preview=ttk.Label(form,text=str(i+1),compound='left');preview.grid(row=2+i,column=0,padx=(0,8));self.item_previews.append(preview)
            var.trace_add('write',lambda *args:self.refresh_icons())
            combo.grid(row=2+i,column=1,sticky='ew',pady=6)
            entry=ttk.Spinbox(form,from_=1,to=50,textvariable=count,width=5);entry.grid(row=2+i,column=2,padx=(8,0))
            self.slots.append((var,count,combo,entry))
        ttk.Label(form,text='同一疊可重複選取；總消耗會在開始前核對。',style='Muted.TLabel').grid(row=7,column=0,columnspan=3,sticky='w',pady=(10,0))
        ttk.Label(side,text='執行狀態',style='Section.TLabel').pack(anchor='w',pady=(0,8))
        ttk.Label(side,textvariable=self.status,wraplength=195).pack(fill='x')
        actions=ttk.Frame(side);actions.pack(side='bottom',fill='x')
        self.start=ttk.Button(actions,text='預覽消耗／開始',command=self.begin);self.start.pack(fill='x',pady=4)
        self.stop=ttk.Button(actions,text='停止後續煉金',command=lambda:app.send({'type':'stop_alchemy'}));self.stop.pack(fill='x',pady=4)
        self.clear=ttk.Button(actions,text='清空材料',command=lambda:[v.set('') for v,_,_,_ in self.slots]);self.clear.pack(fill='x',pady=4)
        self.render({})
    def cleanup_icons(self,event):
        if event.widget is self:self.icons.close();self.preview_images.clear()
    def refresh_icons(self):
        self.preview_images=[]
        for preview,(var,*_) in zip(self.item_previews,self.slots):
            row=self.choices.get(var.get())
            image=self.icons.get(row['item_id'],24) if row else ''
            if image:self.preview_images.append(image)
            preview.configure(image=image)
    def begin(self):
        try:
            command={'type':'start_alchemy','mode':self.mode.get(),'runs':int(self.runs.get()),'materials':[]}
            for var,count,_,_ in self.slots:
                if not var.get():continue
                item=self.choices.get(var.get())
                if not item:raise ValueError('材料選項已變更，請重新選取')
                command['materials'].append({'index':item['index'],'item_id':item['item_id'],'count':int(count.get())})
            from types import SimpleNamespace
            state=SimpleNamespace(**self.app.snapshot);state.snapshot=lambda:self.app.snapshot
            plan=prepare(state,command)
            text='\n'.join(f"{item_name(row['item_id'])}｜包包#{row['index']}｜每次合計{row['count']}，總消耗{row['count']*plan['runs']}" for row in plan['consumption'])
            if messagebox.askyesno('開始自動煉金',f"{plan['mode']}煉金，共{plan['runs']}次\n{text}\n\n依伺服器結果逐次執行，材料將會消耗。",parent=self.app.root):self.app.send(command)
        except (ValueError,KeyError,TypeError,AttributeError) as exc:messagebox.showinfo('煉金設定',str(exc),parent=self.app.root)
    def render(self,state):
        inv=state.get('inventory',{});alchemy=state.get('alchemy',{});available=modes(state);busy=alchemy.get('enabled') or alchemy.get('pending')
        signature=(inv.get('revision'),tuple(available),busy,self.app.live_active)
        if signature!=self.signature:
            self.signature=signature;old=self.choices
            self.choices={f"#{v['index']} {item_name(v['item_id'])} ×{v['count']}":dict(v) for v in inv.get('items',{}).values() if not material_problem(v)}
            reverse={(v['index'],v['item_id']):key for key,v in self.choices.items()}
            for var,count,combo,entry in self.slots:
                previous=old.get(var.get());combo.configure(values=('',*self.choices),state='disabled' if busy else 'readonly');entry.configure(state='disabled' if busy else 'normal')
                if previous:var.set(reverse.get((previous['index'],previous['item_id']),''))
            self.mode_combo.configure(values=available,state='disabled' if busy else 'readonly')
            if self.mode.get() not in available:self.mode.set(available[-1])
            self.run_entry.configure(state='disabled' if busy else 'normal');self.clear.configure(state='disabled' if busy else 'normal')
        self.refresh_icons()
        self.start.configure(state='normal' if self.app.live_active and not busy and inv.get('ready') and inv.get('reliable') else 'disabled')
        self.stop.configure(state='normal' if self.app.live_active and alchemy.get('enabled') else 'disabled')
        history=alchemy.get('history',[]);last=f"｜末次：{history[-1]['name']} ×{history[-1]['count']}" if history else ''
        self.status.set(f"{alchemy.get('status','尚未啟動')}｜完成 {alchemy.get('completed',0)}/{alchemy.get('requested',0)}{last}")
