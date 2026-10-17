"""Ten ordered supply slots and independent player/follower recovery thresholds."""
import math
import tkinter as tk
from tkinter import ttk
from wlre.services.items.combat_resources import item_name, heal_effects, available, field_context
from wlre.ui.crafting_browser import ItemIcons

class SupplyPicker:
    def __init__(self,page,index):
        self.page=page;self.index=index;self.offset=0;self.rows=[];self.row_images=[]
        self.window=w=tk.Toplevel(page);w.title('選擇'+page.resource.upper()+'補品');w.geometry('660x480');w.resizable(False,False)
        box=ttk.Frame(w,padding=12);box.pack(fill='both',expand=True)
        top=ttk.Frame(box);top.pack(fill='x');ttk.Label(top,text='搜尋包包補品').pack(side='left')
        self.search=tk.StringVar();entry=ttk.Entry(top,textvariable=self.search);entry.pack(side='left',fill='x',expand=True,padx=8)
        self.search.trace_add('write',lambda *a:self.find())
        self.table=ttk.Treeview(box,columns=('name','count','effect'),show='tree headings',height=9,selectmode='browse')
        for k,t,width in [('name','物品名稱',300),('count','可用數量',100),('effect','回復量',140)]:
            self.table.heading(k,text=t);self.table.column(k,width=width,anchor='center')
        self.table.heading('#0',text='圖示');self.table.column('#0',width=42,minwidth=42,stretch=False)
        self.table.pack(fill='both',expand=True,pady=10);self.table.bind('<Double-1>',lambda e:self.choose())
        nav=ttk.Frame(box);nav.pack(fill='x');ttk.Button(nav,text='上一頁',command=lambda:self.move(-1)).pack(side='left')
        self.label=tk.StringVar();ttk.Label(nav,textvariable=self.label).pack(side='left',padx=12)
        ttk.Button(nav,text='下一頁',command=lambda:self.move(1)).pack(side='left')
        footer=ttk.Frame(box);footer.pack(fill='x',pady=(10,0))
        ttk.Button(footer,text='清除此格',command=lambda:self.commit(0)).pack(side='left')
        ttk.Button(footer,text='取消',command=w.destroy).pack(side='right')
        ttk.Button(footer,text='選取',command=self.choose).pack(side='right',padx=8)
        self.find();page.editor.app.theme.attach(w)
    def find(self):
        inv=self.page.editor.app.snapshot.get('inventory',{});counts={}
        if inv.get('ready') and inv.get('reliable'):
            for index,row in inv.get('items',{}).items():
                if row.get('locked') or row.get('available_time') or row.get('limited_time'):continue
                sid=row['item_id'];amount=available(inv,index)
                if heal_effects(sid).get(self.page.resource) and amount>0:counts[sid]=counts.get(sid,0)+amount
        q=self.search.get().strip().casefold()
        self.rows=[(sid,count) for sid,count in sorted(counts.items(),key=lambda p:item_name(p[0])) if not q or q in item_name(sid).casefold() or q==str(sid)]
        self.offset=0;self.render()
    def render(self):
        self.table.delete(*self.table.get_children())
        self.row_images=[]
        for sid,count in self.rows[self.offset:self.offset+9]:
            image=self.page.icons.get(sid,24);self.row_images.append(image)
            self.table.insert('', 'end',iid=str(sid),image=image,values=(item_name(sid),count,heal_effects(sid)[self.page.resource]))
        self.label.set(f'{self.offset//9+1}／{max(1,math.ceil(len(self.rows)/9))} 頁（{len(self.rows)} 種）')
    def move(self,direction):
        self.offset=max(0,min(max(0,(len(self.rows)-1)//9)*9,self.offset+direction*9));self.render()
    def commit(self,sid):self.page.items[self.index]=sid;self.page.render_slots();self.window.destroy()
    def choose(self):
        selected=self.table.selection()
        if selected:self.commit(int(selected[0]))

class RecoveryPage(ttk.Frame):
    def __init__(self,parent,editor,resource,master_enabled):
        super().__init__(parent,padding=10);self.editor=editor;self.resource=resource;self.items=[0]*10;self.images=[];self.timer=None
        self.icons=ItemIcons(self);self.buttons=[];self.vars={k:tk.BooleanVar() for k in ('enabled','other_items','first','after')}
        head=ttk.Frame(self);head.pack(fill='x')
        ttk.Checkbutton(head,text='啟用戰後補給',variable=master_enabled).pack(side='left')
        self.balance=tk.StringVar();ttk.Label(head,textvariable=self.balance,style='Muted.TLabel').pack(side='right')
        ttk.Checkbutton(self,text='優先使用藥水儲存槽回復'+resource.upper(),variable=self.vars['first'],command=self.first_changed).pack(anchor='w',pady=4)
        ttk.Checkbutton(self,text='自動使用指定'+resource.upper()+'補品（由左至右、上至下）',variable=self.vars['enabled']).pack(anchor='w',pady=3)
        grid=ttk.Frame(self);grid.pack(fill='x',pady=4)
        for i in range(10):
            grid.columnconfigure(i%5,weight=1)
            button=ttk.Button(grid,text=f'{i+1}　＋',compound='left',command=lambda i=i:SupplyPicker(self,i))
            button.grid(row=i//5,column=i%5,sticky='nsew',padx=3,pady=3,ipady=5)
            button.bind('<Button-3>',lambda e,i=i:self.clear(i));self.buttons.append(button)
        ttk.Label(self,text='點選空格選補品；右鍵清除。缺少的物品會跳過，順序保留。',style='Muted.TLabel').pack(anchor='w')
        ttk.Checkbutton(self,text='指定補品用完後，使用藥水儲存槽',variable=self.vars['after'],command=self.after_changed).pack(anchor='w',pady=4)
        ttk.Checkbutton(self,text='指定補品用完後，使用包包內其他'+resource.upper()+'補品',variable=self.vars['other_items']).pack(anchor='w',pady=4)
        self.percents={};self.amounts={}
        for who,title in (('player','玩家'),('partner','夥伴')):
            row=ttk.Frame(self);row.pack(fill='x',pady=4)
            ttk.Label(row,text=title+resource.upper()+'低於設定時使用',width=25).pack(side='left')
            v=tk.IntVar(value=0);self.percents[who]=v
            ttk.Button(row,text='－',width=3,command=lambda v=v:self.step(v,-1)).pack(side='left')
            scale=ttk.Scale(row,from_=0,to=100,command=lambda n,v=v:v.set(round(float(n))));scale.pack(side='left',fill='x',expand=True,padx=6)
            # Keep an integer model even when ttk.Scale supplies a floating value.
            v.trace_add('write',lambda *a,v=v,scale=scale:self.sync_scale(v,scale))
            ttk.Button(row,text='＋',width=3,command=lambda v=v:self.step(v,1)).pack(side='left')
            amount=tk.StringVar();self.amounts[who]=amount
            ttk.Label(row,textvariable=amount,width=25,anchor='e').pack(side='right')
        self.bind('<Destroy>',self.destroyed,add='+');self.refresh_stats()
    def sync_scale(self,v,scale):
        if abs(scale.get()-v.get())>.01:scale.set(v.get())
        self.show_amounts()
    def step(self,v,d):v.set(max(0,min(100,v.get()+d)))
    def first_changed(self):
        if self.vars['first'].get():self.vars['after'].set(False)
    def after_changed(self):
        if self.vars['after'].get():self.vars['first'].set(False)
    def clear(self,index):self.items[index]=0;self.render_slots()
    def render_slots(self):
        self.images=[]
        for i,(sid,button) in enumerate(zip(self.items,self.buttons)):
            if sid:
                image=self.icons.get(sid,36);self.images.append(image)
                button.configure(text=f'{i+1} '+item_name(sid)[:7],image=image)
            else:button.configure(text=f'{i+1}　＋',image='')
    def render(self,value):
        self.items=list(value['items'])
        for k in ('enabled','other_items'):self.vars[k].set(value[k])
        self.vars['first'].set(value['storage']=='first');self.vars['after'].set(value['storage']=='after')
        for who,v in self.percents.items():v.set(value[who+'_percent'])
        self.render_slots();self.show_amounts()
    def collect(self):
        return {'enabled':self.vars['enabled'].get(),'other_items':self.vars['other_items'].get(),
            'storage':'first' if self.vars['first'].get() else 'after' if self.vars['after'].get() else 'off',
            'items':list(self.items),**{who+'_percent':v.get() for who,v in self.percents.items()}}
    def show_amounts(self):
        context,actor=field_context(self.editor.app.snapshot)
        for who,var in self.amounts.items():
            unit=actor if who=='player' else next((u for u in context['battle_units'].values() if u.get('npc_index',0)),{})
            current,maximum=unit.get(self.resource),unit.get('max_'+self.resource)
            var.set(f"{self.percents[who].get()}%（{current}/{maximum}）" if current is not None and maximum else f"{self.percents[who].get()}%（尚未同步）")
    def refresh_stats(self):
        balance=self.editor.app.snapshot.get('potion_storage',{}).get(self.resource,{})
        self.balance.set('藥水儲存槽：'+(f"{balance['value']:,}" if 'value' in balance else '尚未同步'))
        self.show_amounts();self.timer=self.after(1000,self.refresh_stats)
    def destroyed(self,event):
        if event.widget is self:
            if self.timer:self.after_cancel(self.timer);self.timer=None
            self.icons.archive.close()
