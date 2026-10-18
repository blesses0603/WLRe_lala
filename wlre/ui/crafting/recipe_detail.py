"""Crafting recipe details, materials and batch action UI.

All content remains driven by authoritative crafting and inventory state.
"""
import tkinter as tk
from tkinter import ttk
from wlre.ui.theme import group


def build_recipe_detail(self, box, body, embedded):
    right=group(box if embedded else body,text='配方詳情',padding=6 if embedded else 8)
    right.grid(row=0,column=1 if embedded else 2,rowspan=4 if embedded else 1,sticky='nsew',padx=(6,0) if embedded else 0)
    self.detail_panel=right
    if embedded:
        right.configure(width=248);right.pack_propagate(False)
        summary=ttk.Frame(right);summary.pack(fill='x')
    else:summary=right
    title=ttk.Frame(summary);title.pack(fill='x')
    self.large_image=ttk.Label(title);self.large_image.pack(side='left',padx=(0,8))
    self.name=tk.StringVar(value='請選擇製作物');ttk.Label(title,textvariable=self.name,style='Heading.TLabel',wraplength=180 if embedded else 260).pack(side='left',fill='x',expand=True)
    self.hold=tk.StringVar();ttk.Label(summary,textvariable=self.hold,wraplength=0 if embedded else 380).pack(fill='x',pady=3)
    self.device=tk.StringVar();ttk.Label(summary,textvariable=self.device,style='Muted.TLabel',wraplength=225 if embedded else 380).pack(fill='x')
    self.time=tk.StringVar();ttk.Label(summary,textvariable=self.time,style='Muted.TLabel',wraplength=225 if embedded else 380).pack(fill='x',pady=2 if embedded else 4)
    self.material_widgets=[];self.material_table=None
    if embedded:
        self.material_box=ttk.Frame(right)
        self.material_box.pack(fill='both',expand=True,pady=(2,0))
        style=ttk.Style(self.material_box)
        style.configure('Recipe.Treeview',indent=0,padding=0)
        style.configure('Recipe.Treeview.Heading',padding=(2,0))
        style.layout('Recipe.Treeview.Item',[('Treeitem.padding',{'sticky':'nswe','children':[('Treeitem.image',{'side':'left','sticky':''}),('Treeitem.text',{'side':'left','sticky':''})]})])
        self.material_table=ttk.Treeview(self.material_box,style='Recipe.Treeview',columns=('name','usable','required'),height=5,show='tree headings',selectmode='browse')
        for key,label,width in (('name','材料',76),('usable','可用',60),('required','需求',60)):
            self.material_table.heading(key,text=label);self.material_table.column(key,width=width,minwidth=40,stretch=key!='name',anchor='w' if key=='name' else 'center')
        self.material_table.heading('#0',text='');self.material_table.column('#0',width=26,minwidth=26,stretch=False,anchor='w')
        self.material_table.pack(fill='both',expand=True)
        self.material_table.tag_configure('missing',foreground='#f2b0a8')
        self.material_table.tag_configure('ready',foreground='#a8e4c0')
    else:
        self.material_box=group(right,text='材料：背包可用／需求',padding=5)
        self.material_box.pack(fill='both',expand=True,pady=(4,0))
        for i in range(5):
            line=ttk.Frame(self.material_box);line.pack(fill='x',pady=3)
            icon=ttk.Label(line);icon.pack(side='left',padx=(0,5))
            text=ttk.Label(line,wraplength=290);text.pack(side='left',fill='x',expand=True)
            self.material_widgets.append((line,icon,text))
    compose=ttk.Frame(right);compose.pack(side='bottom',fill='x',pady=(6,0),before=summary if embedded else self.material_box)
    batch=ttk.Frame(compose) if embedded else compose
    if embedded:batch.pack(fill='x')
    ttk.Label(batch,text='批數').pack(side='left');self.count=tk.StringVar(value='1')
    ttk.Spinbox(batch,from_=1,to=255,textvariable=self.count,width=5).pack(side='left',padx=4)
    actions=ttk.Frame(compose) if embedded else compose
    if embedded:actions.pack(fill='x',pady=(4,0))
    self.add_button=ttk.Button(actions,text='加入排程',command=self.add,state='disabled');self.add_button.pack(side='right')
    ttk.Button(actions,text='加入自訂',command=lambda:self.panel.open_plan().add(self.selected,self.count.get())).pack(side='right',padx=3)
    self.count.trace_add('write',lambda *args:self.refresh_detail(force=True))
    self.reason=tk.StringVar()
    if not embedded:ttk.Label(right,textvariable=self.reason,style='Muted.TLabel',wraplength=380).pack(side='bottom',fill='x',pady=(5,0),before=self.material_box)
    return right


def render_recipe_detail(self, force=False, *, recipes, owned_counts, material_rows,
                         availability, item_name, tool_status, effective_time,
                         duration, icon_map, recipe_plan):
    recipe=recipes.get(str(self.selected));c=self.state.get('crafting',{})
    if recipe is None:
        self.name.set('沒有符合的未鎖定項目');self.hold.set('');self.device.set('');self.time.set('');self.reason.set('調整設備篩選、搜尋，或先同步小屋資料');self.large_image.configure(image='');self.add_button.configure(state='disabled')
        for line,icon,text in self.material_widgets:line.pack_forget()
        if self.material_table is not None:self.material_table.delete(*self.material_table.get_children())
        return
    try:count=int(self.count.get())
    except ValueError:count=0
    valid=1<=count<=255;counts=owned_counts(self.state,self.selected);materials=material_rows(self.state,recipe,max(1,count));status,reason=availability(self.state,recipe,max(1,count))
    signature=(self.selected,count,self.app.live_active,tuple(counts.items()),tuple(tuple(m.items()) for m in materials),status,c.get('pending'),c.get('revision'),self.state.get('furniture',{}).get('revision'))
    if not force and signature==self.detail_key:return
    self.detail_key=signature;self.name.set(item_name(self.selected));self.large_photo=self.icons.get(self.selected,32 if self.embedded else 80);self.large_image.configure(image=self.large_photo)
    fmt=lambda v:'待同步' if v is None else str(v)
    if self.embedded:
        number=lambda v:'—' if v is None else str(v)
        self.hold.set(f"背包 {number(counts['bag'])}｜小屋 {number(counts['placed'])}\n保管 {number(counts['stored'])}｜排程 {counts['queued']}")
    else:self.hold.set(f"背包持有 {fmt(counts['bag'])}｜小屋已擺 {fmt(counts['placed'])}\n保管中 {fmt(counts['stored'])}｜排程預計產出 {counts['queued']}")
    tool=recipe['tool_id'];self.device.set(f'設備：{item_name(tool)} · {tool_status(self.state,tool)}')
    meta=icon_map.get(str(self.selected),{});size=f"｜{meta['width']:.1f}×{meta['height']:.1f}" if meta.get('width') and meta.get('height') else ''
    seconds=recipe['seconds']*max(1,count);adjusted=effective_time(self.state,{'base_time':seconds})
    self.time.set((f"產量 {recipe['output']*max(1,count)}｜時間 {duration(adjusted if adjusted is not None else seconds)}" if self.embedded else f"產量 {recipe['output']*max(1,count)}{size}\n時間：{duration(seconds)}"+(f' → {duration(adjusted)}' if adjusted is not None and seconds else '')))
    for i,(line,icon,text) in enumerate(self.material_widgets):
        if i>=len(materials):line.pack_forget();continue
        line.pack(fill='x',pady=2);m=materials[i];icon.image=self.icons.get(m['item_id'],28);icon.configure(image=icon.image)
        text.configure(text=f"{m['name']}   {fmt(m['usable'])}/{m['required']}"+(f"｜已擺 {m['placed']} 不計入" if m['placed'] else ''),foreground='#f2b0a8' if m['usable'] is None or m['usable']<m['required'] else '#a8e4c0')
    if self.material_table is not None:
        self.material_table.delete(*self.material_table.get_children());self.material_images=[]
        for material in materials:
            image=self.icons.get(material['item_id'],24);self.material_images.append(image)
            tag='missing' if material['usable'] is None or material['usable']<material['required'] else 'ready'
            name=material['name']+(f"（已擺 {material['placed']} 不計入）" if material['placed'] else '')
            self.material_table.insert('','end',image=image,values=(name,fmt(material['usable']),material['required']),tags=(tag,))
    plan_ok=False
    if valid and status=='可製作' and not c.get('pending') and not c.get('uncertain'):
        from types import SimpleNamespace
        try:recipe_plan(SimpleNamespace(**self.state),self.selected,count);plan_ok=True
        except (ValueError,KeyError,AttributeError) as exc:reason=str(exc)
    if not valid:reason='批數請輸入 1～255'
    if c.get('pending'):reason='製作處理中，請稍候'
    self.reason.set(reason)
    if self.embedded:self.message.set(reason)
    self.add_button.configure(state='normal' if plan_ok and self.app.live_active else 'disabled')

