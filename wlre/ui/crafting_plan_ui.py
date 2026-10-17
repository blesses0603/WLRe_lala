"""Editable, portable local crafting plan. No submission until explicit Start."""
import json
import tkinter as tk
from wlre.ui.window_layout import configure_dialog
from tkinter import ttk,messagebox,filedialog
from pathlib import Path
from wlre.services.items.crafting_plan import validate_rows
from wlre.services.items.combat_resources import item_name

class PlanWindow:
    def __init__(self,panel):
        self.panel=panel;self.rows=[];self.follow_revision=None;self.runtime_key=None;self.row_images={}
        self.window=tk.Toplevel(panel);self.window.title('自訂家具製作清單 · 不限項數');configure_dialog(self.window,900,580);self.window.resizable(False,False)
        box=ttk.Frame(self.window,padding=12);box.pack(fill='both',expand=True)
        ttk.Label(box,text='從家具頁或圖示製作選取配方與批數，再按「加入自訂」。開始後會消耗材料。',wraplength=820).pack(fill='x')
        self.table=ttk.Treeview(box,columns=['n','name','count','output'],show='tree headings',height=12,selectmode='browse')
        for key,title,width in [('n','順序',60),('name','家具／製作物',360),('count','批數',100),('output','總產量',140)]:self.table.heading(key,text=title);self.table.column(key,width=width,anchor='center')
        self.table.heading('#0',text='圖示');self.table.column('#0',width=42,minwidth=42,stretch=False)
        self.table.pack(fill='both',expand=True,pady=8)
        scrollbar=ttk.Scrollbar(self.table,orient='vertical',command=self.table.yview);scrollbar.pack(side='right',fill='y');self.table.configure(yscrollcommand=scrollbar.set)
        line=ttk.Frame(box);line.pack(fill='x')
        for text,fn in [('加入目前配方',self.add_current),('上移',lambda:self.move(-1)),('下移',lambda:self.move(1)),('移除',self.remove),('清空',self.clear),('儲存',self.save),('載入',self.load)]:ttk.Button(line,text=text,command=fn).pack(side='left',padx=2)
        line=ttk.Frame(box);line.pack(fill='x',pady=6)
        ttk.Label(line,text='選取項目總批數').pack(side='left');self.count=tk.StringVar(value='1');ttk.Entry(line,width=12,textvariable=self.count).pack(side='left',padx=4)
        ttk.Button(line,text='更新批數',command=self.edit_count).pack(side='left')
        ttk.Button(line,text='開始／繼續清單',command=self.start).pack(side='right')
        ttk.Button(line,text='暫停清單',command=lambda:panel.app.send({'type':'craft','action':'plan_pause'})).pack(side='right',padx=4)
        self.status=tk.StringVar();ttk.Label(box,textvariable=self.status,wraplength=820).pack(fill='x')
        self.table.bind('<<TreeviewSelect>>',self.select)
        self.render(panel.state);self.refresh()

    def editable(self):
        c=self.panel.state.get('crafting',{});p=c.get('local_plan',{})
        if p.get('enabled') or c.get('pending') or self.follow_revision is not None and p.get('revision',0)<self.follow_revision:
            self.status.set('請先暫停清單並等待送出項目確認，再修改');return False
        return True

    def refresh(self):
        from wlre.services.items.crafting import RECIPES
        self.table.delete(*self.table.get_children())
        self.row_images={}
        for i,r in enumerate(self.rows):
            image=self.panel.icons.get(r['item_id'],24);self.row_images[str(i)]=image
            self.table.insert('','end',iid=str(i),image=image,values=(i+1,item_name(r['item_id']),r['count'],RECIPES[str(r['item_id'])]['output']*r['count']))
        self.window.title(f'自訂家具製作清單 · {len(self.rows)} 項')

    def add(self,sid,count):
        if not self.editable():return
        try:self.rows=validate_rows(self.rows+[{'item_id':sid,'count':int(count)}])
        except (ValueError,TypeError) as exc:self.status.set(str(exc));return
        self.refresh();self.status.set(f'已加入自訂清單：{len(self.rows)} 項，尚未送出')

    def add_current(self):self.add(self.panel.recipe_id,self.panel.count.get())
    def selected(self):
        ids=self.table.selection();return int(ids[0]) if ids else None
    def select(self,event=None):
        i=self.selected()
        if i is not None:self.count.set(str(self.rows[i]['count']))
    def move(self,delta):
        if not self.editable():return
        i=self.selected()
        if i is None or not 0<=i+delta<len(self.rows):return
        self.rows[i],self.rows[i+delta]=self.rows[i+delta],self.rows[i];self.refresh();self.table.selection_set(str(i+delta))
    def remove(self):
        if not self.editable():return
        i=self.selected()
        if i is not None:self.rows.pop(i);self.refresh()
    def clear(self):
        if self.editable() and messagebox.askyesno('清空自訂清單','清空所有尚未送出的項目？',parent=self.window):self.rows=[];self.refresh()
    def edit_count(self):
        if not self.editable():return
        i=self.selected()
        if i is None:return
        try:
            rows=[dict(r) for r in self.rows];rows[i]['count']=int(self.count.get());self.rows=validate_rows(rows)
        except ValueError as exc:self.status.set(str(exc));return
        self.refresh();self.table.selection_set(str(i))
    def save(self):
        path=filedialog.asksaveasfilename(parent=self.window,defaultextension='.json',filetypes=[('製作方案','*.json')],initialfile='家具製作方案.json')
        if not path:return
        try:
            rows=validate_rows(self.rows);dest=Path(path);tmp=dest.with_name(dest.name+'.tmp');tmp.write_text(json.dumps({'format':'wlre-crafting-plan','version':1,'rows':rows},ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(dest);self.status.set('方案已儲存')
        except (OSError,ValueError) as exc:self.status.set('儲存失敗：'+str(exc))
    def load(self):
        if not self.editable():return
        path=filedialog.askopenfilename(parent=self.window,filetypes=[('製作方案','*.json')])
        if not path:return
        try:
            data=json.loads(Path(path).read_text(encoding='utf-8'))
            if not isinstance(data,dict) or data.get('format')!='wlre-crafting-plan' or data.get('version')!=1:raise ValueError('不是支援的製作方案')
            rows=validate_rows(data.get('rows'));self.rows=rows;self.refresh();self.status.set('方案已載入，尚未開始')
        except (OSError,ValueError,TypeError) as exc:self.status.set('載入失敗：'+str(exc))
    def start(self):
        if not self.editable():return
        try:rows=validate_rows(self.rows)
        except ValueError as exc:self.status.set(str(exc));return
        if not rows:self.status.set('請先加入製作物');return
        if not self.panel.app.live_active:self.status.set('請先登入角色');return
        if not messagebox.askyesno('啟動自訂製作清單',f'依順序送出 {len(rows)} 項製作，將消耗背包材料。\n每項總批數不限，每次最多送出 255 批。\n伺服器有空位時自動補入，缺材料或設備時暫停。\n\n確認開始？',parent=self.window):return
        p=self.panel.state.get('crafting',{}).get('local_plan',{});revision=p.get('revision',0)
        self.follow_revision=revision+1;self.runtime_key=None;self.row_images={}
        self.panel.app.send({'type':'craft','action':'plan_set','rows':rows,'revision':revision})
        self.panel.app.send({'type':'craft','action':'plan_start','revision':revision+1})
    def render(self,state):
        if not self.window.winfo_exists():return
        p=state.get('crafting',{}).get('local_plan',{});revision=p.get('revision',0)
        key=(revision,p.get('enabled'),p.get('status'),p.get('sent'))
        if key==self.runtime_key:return
        self.runtime_key=key
        if self.follow_revision is None:
            if not self.rows and p.get('rows'):self.rows=[dict(r) for r in p['rows']];self.refresh()
        elif revision>=self.follow_revision:
            self.rows=[dict(r) for r in p.get('rows',[])];self.follow_revision=revision;self.refresh()
        self.status.set(p.get('status','自訂清單尚未啟動')+f"｜待送出 {len(p.get('rows',[]))} 項｜已確認送入 {p.get('sent',0)} 項")
