"""Compact recipe browser and server schedule in the fixed left page."""
import time
import tkinter as tk
from tkinter import ttk,messagebox
from wlre.services.items.crafting import RECIPES, recipe_plan, elapsed, effective_time, confirmed_unlocked
from wlre.services.items.combat_resources import item_name
from wlre.core.efficiency import duration
from wlre.network.wire import ProtocolError
from wlre.ui.crafting_browser import ItemIcons

class CraftingPanel(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,padding=6);self.app=app;self.browser=None;self.plan_window=None;self.state={};self.signature=None;self.ids={};self.recipe_id=None;self.search_job=None
        self.icons=ItemIcons(self);self.row_images={}
        self.bind('<Destroy>',self.cleanup_icons,add='+')
        self.columnconfigure(0,weight=1);self.rowconfigure(3,weight=1)
        top=ttk.Frame(self);top.grid(row=0,column=0,sticky='ew')
        ttk.Label(top,text='家具／物品製作',style='Heading.TLabel').pack(side='left')
        ttk.Button(top,text='自訂清單',command=self.open_plan).pack(side='left',padx=2)
        ttk.Button(top,text='圖示製作',command=self.open_browser).pack(side='left',padx=8)
        ttk.Button(top,text='進入自家帳篷',command=lambda:self.command('enter')).pack(side='right')
        choose=ttk.Frame(self);choose.grid(row=1,column=0,sticky='ew',pady=3)
        self.search=tk.StringVar();ttk.Label(choose,text='搜尋').pack(side='left')
        entry=ttk.Entry(choose,textvariable=self.search,width=15);entry.pack(side='left',padx=3);entry.bind('<KeyRelease>',self.defer_search)
        self.choice=tk.StringVar();self.combo=ttk.Combobox(choose,textvariable=self.choice,state='readonly',width=26);self.combo.pack(side='left',fill='x',expand=True,padx=3);self.combo.bind('<<ComboboxSelected>>',lambda e:self.select_recipe())
        self.count=tk.StringVar(value='1');ttk.Spinbox(choose,from_=1,to=255,textvariable=self.count,width=4,command=self.select_recipe).pack(side='left',padx=3)
        ttk.Button(choose,text='加入排程',command=self.add).pack(side='right')
        self.count.trace_add('write',lambda *args:self.select_recipe())
        self.detail=tk.StringVar(value='選擇配方以查看材料及設備')
        ttk.Label(self,textvariable=self.detail,wraplength=620,style='Muted.TLabel').grid(row=2,column=0,sticky='ew',pady=3)
        body=ttk.Frame(self);body.grid(row=3,column=0,sticky='nsew');body.columnconfigure(0,weight=1);body.rowconfigure(0,weight=1)
        self.table=ttk.Treeview(body,columns=['order','name','count','time'],show='tree headings',height=3,selectmode='browse')
        for key,title,width in [('order','順序',48),('name','伺服器製作排程',218),('count','批數',64),('time','剩餘時間',170)]:
            self.table.heading(key,text=title);self.table.column(key,width=width,minwidth=40,anchor='center')
        self.table.heading('#0',text='圖示');self.table.column('#0',width=42,minwidth=42,stretch=False)
        self.table.grid(row=0,column=0,sticky='nsew');bar=ttk.Scrollbar(body,command=self.table.yview);bar.grid(row=0,column=1,sticky='ns');self.table.configure(yscrollcommand=bar.set)
        buttons=ttk.Frame(self);buttons.grid(row=4,column=0,sticky='ew',pady=4)
        for label,action in [('開始／接續','start'),('暫停製作','pause'),('停止接續','stop_auto'),('上移','up'),('下移','down'),('移除','delete')]:ttk.Button(buttons,text=label,command=lambda a=action:self.command(a)).pack(side='left',padx=2)
        self.status=tk.StringVar(value='登入後同步伺服器排程；先進自家帳篷取得工作設備')
        ttk.Label(self,textvariable=self.status,wraplength=620,style='Muted.TLabel').grid(row=5,column=0,sticky='ew')
        self.find();self.after(1000,self.tick)

    def cleanup_icons(self,event):
        if event.widget is self:self.icons.close();self.row_images.clear()

    def open_plan(self):
        if self.plan_window and self.plan_window.window.winfo_exists():
            self.plan_window.window.deiconify();self.plan_window.window.lift();return self.plan_window
        from wlre.ui.crafting_plan_ui import PlanWindow
        self.plan_window=PlanWindow(self);self.plan_window.window.protocol('WM_DELETE_WINDOW',self.plan_window.window.withdraw);return self.plan_window

    def open_browser(self):
        if self.browser and not self.browser.closed:
            self.browser.window.lift();return self.browser
        from wlre.ui.crafting_browser import CraftingBrowser
        self.browser=CraftingBrowser(self);return self.browser

    def defer_search(self,event=None):
        if self.search_job:self.after_cancel(self.search_job)
        self.search_job=self.after(200,self.find)

    def find(self):
        self.search_job=None;q=self.search.get().strip().casefold()
        self.ids={f"{item_name(r['item_id'])}（{r['item_id']}）":r['item_id'] for r in RECIPES.values() if confirmed_unlocked(r) and q in (item_name(r['item_id'])+' '+str(r['item_id'])+' '+item_name(r['tool_id'])).casefold()}
        self.combo.configure(values=list(self.ids))
        if self.choice.get() not in self.ids:self.choice.set(next(iter(self.ids),''))
        self.select_recipe()

    def select_recipe(self):
        sid=self.ids.get(self.choice.get());self.recipe_id=sid;r=RECIPES.get(str(sid))
        if not r:self.detail.set('沒有符合的已確認未鎖定配方；需圖紙或條件未同步項目暫不顯示');return
        try:count=int(self.count.get())
        except ValueError:self.detail.set('請輸入 1～255 批');return
        materials='、'.join(f"{item_name(v['item_id'])} ×{v['count']*count}" for v in r['materials']) or '無'
        text=f"設備：{item_name(r['tool_id'])}｜產量 {r['output']*count}｜原始時間 {duration(r['seconds']*count)}\n材料：{materials}"
        if r['design_id']:text+='｜需圖紙解鎖，目前未同步'
        if r['time_id'] or r['limit_kind']:text+='｜有活動／次數限制，目前未確認'
        self.detail.set(text)

    def command(self,action):
        c=self.state.get('crafting',{});cmd={'type':'craft','action':action}
        if action in ('up','down','delete'):
            selected=self.table.selection()
            if not selected:self.status.set('請先選取伺服器排程');return
            index=int(selected[0]);cmd.update(index=index,revision=c.get('revision'))
            if action=='delete' and not messagebox.askyesno('移除製作排程','確定放棄此製作項目？材料是否退還依伺服器規則。',parent=self.app.root):return
        self.app.send(cmd)

    def add(self):
        try:
            count=int(self.count.get());sid=self.ids.get(self.choice.get())
            from types import SimpleNamespace
            data=self.state
            state=SimpleNamespace(player=data.get('player',{}),furniture=data.get('furniture',{}),crafting=data.get('crafting',{}),inventory=data.get('inventory',{}))
            if not sid:raise ProtocolError('請選擇配方')
            if not data.get('player'):raise ProtocolError('請先登入角色')
            r,allocations,packet=recipe_plan(state,sid,count)
        except (ValueError,KeyError) as exc:self.status.set(str(exc));return
        text=f"製作：{item_name(sid)} ×{r['output']*count}\n設備：{item_name(r['tool_id'])}\n背包消耗："+'、'.join(f"{item_name(a['item_id'])} ×{a['count']}" for a in allocations)
        if not messagebox.askyesno('加入製作排程',text+'\n\n確認送出？',parent=self.app.root):return
        self.app.send({'type':'craft','action':'add','item_id':sid,'count':count})

    def render(self,state):
        self.state=state;c=state.get('crafting',{});key=(c.get('revision'),c.get('active'),c.get('running'),c.get('pending'),c.get('status'),c.get('completed'))
        if key!=self.signature:
            self.signature=key;selected=self.table.selection();existing=set(self.table.get_children());wanted=set(c.get('queue',{}))
            for iid in existing-wanted:self.table.delete(iid);self.row_images.pop(iid,None)
            for iid,row in sorted(c.get('queue',{}).items(),key=lambda x:int(x[0])):
                values=(row['index'],item_name(row['item_id']),row['count'],'—')
                image=self.icons.get(row['item_id'],24);self.row_images[iid]=image
                if iid in existing:self.table.item(iid,values=values,image=image)
                else:self.table.insert('','end',iid=iid,values=values,image=image)
            if selected and selected[0] in wanted:self.table.selection_set(selected[0])
            self.status.set(c.get('status','等待同步')+f"｜本次完成 {c.get('completed',0)} 項｜"+('自動接續已開' if c.get('auto_continue') else '自動接續已關'))
        if self.plan_window:self.plan_window.render(state)
        self.update_times()
        if self.browser and not self.browser.closed:self.browser.update_state(state)

    def update_times(self):
        c=self.state.get('crafting',{});now=time.monotonic()
        for iid,row in c.get('queue',{}).items():
            if self.table.exists(iid):
                real_time=effective_time(self.state,row)
                remaining=max(0,(real_time if real_time is not None else row['base_time'])-elapsed(c,row,now))
                text=('等待完成確認' if c.get('completion_requested') and row['index']==c.get('active') else duration(remaining)+('（原始）' if real_time is None else ''))
                if self.table.set(iid,'time')!=text:self.table.set(iid,'time',text)

    def tick(self):
        if self.winfo_exists():
            if self.winfo_ismapped():self.update_times()
            self.after(1000,self.tick)
