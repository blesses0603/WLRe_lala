"""Icon crafting catalog with compact embedded and full-window layouts."""
from wlre.paths import RESOURCE_ROOT
import io,json,zipfile,math,time
from collections import OrderedDict
import tkinter as tk
from wlre.ui.window_layout import configure_dialog
from tkinter import ttk
from wlre.ui.layout import scroll_table
from PIL import Image,ImageDraw,ImageTk
from wlre.ui.theme import group
from wlre.services.items.crafting import RECIPES, recipe_plan, effective_time, elapsed, confirmed_unlocked
from wlre.services.items.combat_resources import item_name
from wlre.services.items.crafting_browser_model import Favorites, owned_counts, material_rows, availability, tool_status, room_known
from wlre.core.efficiency import duration

BASE=RESOURCE_ROOT
ICON_MAP=json.loads((BASE/'item_icon_map.json').read_text(encoding='utf-8'))['items']

class ItemIcons:
    def __init__(self,master):self.master=master;self.archive=zipfile.ZipFile(BASE/'item_icons.zip');self.cache=OrderedDict()
    def get(self,item_id,size=64):
        name=ICON_MAP.get(str(item_id),{}).get('icon','s1000')+'.png'
        if name not in self.archive.NameToInfo:name='s1000.png'
        # Different item IDs may share an original sprite or the native fallback.
        key=name,size
        if key in self.cache:self.cache.move_to_end(key);return self.cache[key]
        try:
            with Image.open(io.BytesIO(self.archive.read(name))) as raw:
                icon=raw.convert('RGBA');icon.thumbnail((size,size),Image.Resampling.LANCZOS)
                canvas=Image.new('RGBA',(size,size));canvas.alpha_composite(icon,((size-icon.width)//2,(size-icon.height)//2))
                image=ImageTk.PhotoImage(canvas,master=self.master)
        except (KeyError,OSError):image=tk.PhotoImage(master=self.master,width=size,height=size)
        self.cache[key]=image
        while len(self.cache)>128:self.cache.popitem(last=False)
        return image

    def close(self):self.archive.close();self.cache.clear()

class CraftingBrowser:
    def __init__(self,panel,embedded=False):
        self.panel=panel;self.app=panel.app;self.state=panel.state;self.page=0;self.rows=[];self.selected=None;self.filter_key='all';self.grid_key=None;self.detail_key=None;self.tool_key=None;self.search_job=None;self.refresh_job=None;self.state_key=None
        self.favorite_store=Favorites();self.icons=None;self.closed=False
        self.embedded=embedded;self.page_size=12
        if embedded:
            w=self.window=ttk.Frame(panel);w.pack(fill='both',expand=True)
        else:
            w=self.window=tk.Toplevel(self.app.root);w.title('製作');configure_dialog(w,1160,700);w.protocol('WM_DELETE_WINDOW',self.close)
        self.icons=ItemIcons(w)
        box=ttk.Frame(w,padding=6 if embedded else 12);box.pack(fill='both',expand=True)
        header=ttk.Frame(box);header.pack(fill='x',pady=(0,4))
        ttk.Label(header,text='製作',style='Heading.TLabel').pack(side='left')
        self.queue_label=tk.StringVar();ttk.Button(header,textvariable=self.queue_label,command=self.show_queue,padding=(5,3)).pack(side='right',padx=3)
        ttk.Button(header,text='進入自家帳篷',command=lambda:panel.command('enter'),padding=(5,3)).pack(side='right',padx=3)
        ttk.Button(header,text='自訂清單',command=panel.open_plan,padding=(5,3)).pack(side='right',padx=3)
        searchbar=ttk.Frame(box);searchbar.pack(fill='x',pady=(0,4))
        self.only_tools=tk.BooleanVar(value=True);ttk.Checkbutton(searchbar,text='只列小屋已有設備',variable=self.only_tools,command=lambda:self.refresh(force=True)).pack(side='left')
        ttk.Label(searchbar,text='搜尋').pack(side='left',padx=(8,4))
        self.search=tk.StringVar();search=ttk.Entry(searchbar,textvariable=self.search,width=16);search.pack(side='left',fill='x',expand=True);search.bind('<KeyRelease>',self.defer_search)
        body=ttk.Frame(box);body.pack(fill='both',expand=True)
        catalog=body
        catalog.columnconfigure(0,minsize=128 if embedded else 164,weight=0)
        catalog.columnconfigure(1,weight=1)
        catalog.columnconfigure(2,minsize=248 if embedded else 410,weight=0)
        catalog.rowconfigure(0,weight=1)
        side=group(catalog,text='工作設備',padding=6);side.grid(row=0,column=0,sticky='nsew',padx=(0,8))
        if embedded:side.configure(width=128);side.pack_propagate(False)
        self.tool_tree=ttk.Treeview(side,show='tree',selectmode='browse',height=15);self.tool_tree.column('#0',width=120 if embedded else 136,stretch=True)
        sb=ttk.Scrollbar(side,command=self.tool_tree.yview);sb.pack(side='right',fill='y');self.tool_tree.configure(yscrollcommand=sb.set);self.tool_tree.pack(fill='both',expand=True);self.tool_tree.bind('<<TreeviewSelect>>',self.pick_tool)
        middle=ttk.Frame(catalog) if embedded else group(catalog,text='製作項目',padding=6);middle.grid(row=0,column=1,sticky='nsew',padx=(0,8))
        nav=ttk.Frame(middle);nav.pack(side='bottom',fill='x',pady=(5,0))
        ttk.Button(nav,text='上一頁',command=lambda:self.change_page(-1)).pack(side='left')
        self.page_label=tk.StringVar();ttk.Label(nav,textvariable=self.page_label).pack(side='left',expand=True)
        ttk.Button(nav,text='下一頁',command=lambda:self.change_page(1)).pack(side='right')
        self.grid=ttk.Frame(middle);self.grid.pack(fill='both',expand=True)
        self.cards=[]
        self.favorite_images={}
        for selected in (False,True):
            image=Image.new('RGBA',(72,72));draw=ImageDraw.Draw(image)
            points=[]
            for step in range(121):
                t=step/120*math.tau
                x=16*math.sin(t)**3;y=13*math.cos(t)-5*math.cos(2*t)-2*math.cos(3*t)-math.cos(4*t)
                points.append((36+x*1.8,31-y*1.8))
            if selected:draw.polygon(points,fill='#ffd784')
            else:draw.line(points,fill='#9acddd',width=5,joint='curve')
            self.favorite_images[selected]=ImageTk.PhotoImage(image.resize((18,18),Image.Resampling.LANCZOS),master=w)
        columns=4
        for i in range(self.page_size):
            cell=ttk.Frame(self.grid,padding=3);cell.grid(row=i//columns,column=i%columns,sticky='nsew',padx=2,pady=2)
            self.grid.columnconfigure(i%columns,weight=1,uniform='cards');self.grid.rowconfigure(i//columns,weight=1,uniform='cards')
            footer=ttk.Frame(cell);footer.pack(side='bottom',fill='x',pady=(2,0))
            favorite=ttk.Button(footer,text='收藏',image=self.favorite_images[False],width=2,padding=(2,1),command=lambda n=i:self.toggle_favorite(n))
            favorite.pack(side='right',padx=(2,0))
            status=ttk.Label(footer,anchor='w',style='Muted.TLabel',width=1);status.pack(side='left',fill='x',expand=True)
            button=ttk.Button(cell,compound='top',padding=(3,2) if embedded else (9,5),command=lambda n=i:self.pick_card(n));button.pack(fill='both',expand=True)
            self.cards.append({'frame':cell,'button':button,'favorite':favorite,'status':status,'id':None,'image':None})
        right=group(body,text='配方詳情',padding=6 if embedded else 8);right.grid(row=0,column=2,sticky='nsew')
        self.detail_panel=right
        if embedded:right.configure(width=248);right.pack_propagate(False)
        title=ttk.Frame(right);title.pack(fill='x')
        self.large_image=ttk.Label(title);self.large_image.pack(side='left',padx=(0,8))
        self.name=tk.StringVar(value='請選擇製作物');ttk.Label(title,textvariable=self.name,style='Heading.TLabel',wraplength=180 if embedded else 260).pack(side='left',fill='x',expand=True)
        self.hold=tk.StringVar();ttk.Label(right,textvariable=self.hold,wraplength=225 if embedded else 380).pack(fill='x',pady=5)
        self.device=tk.StringVar();ttk.Label(right,textvariable=self.device,style='Muted.TLabel',wraplength=225 if embedded else 380).pack(fill='x')
        self.time=tk.StringVar();ttk.Label(right,textvariable=self.time,style='Muted.TLabel',wraplength=225 if embedded else 380).pack(fill='x',pady=4)
        self.material_widgets=[];self.material_table=None
        if embedded:
            self.material_box=ttk.Frame(right)
            self.material_box.pack(fill='both',expand=True,pady=(4,0))
            table_frame,self.material_table=scroll_table(self.material_box,('name','usable','required'),('材料','可用','需求'),(90,50,50),height=3,show='tree headings')
            self.material_table.heading('#0',text='');self.material_table.column('#0',width=28,minwidth=28,stretch=False)
            table_frame.pack(fill='both',expand=True)
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
        compose=ttk.Frame(right);compose.pack(side='bottom',fill='x',pady=(6,0),before=title if embedded else self.material_box)
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
        bottom=ttk.Frame(box);bottom.pack(side='bottom',fill='x',pady=(6,0),before=body)
        self.favorite_count=tk.StringVar();ttk.Label(bottom,textvariable=self.favorite_count,style='Muted.TLabel').pack(side='left',padx=(0,8))
        self.message=tk.StringVar(value='自動隱藏鎖定及條件未確認項目；缺材料仍可查看')
        ttk.Label(bottom,textvariable=self.message,style='Muted.TLabel',wraplength=0 if embedded else 760,width=1 if embedded else 0).pack(side='right',fill='x',expand=True)
        for section in (side,right,self.material_box):section._surface_fill=(13,32,48,190)
        self.queue_window=None;self.refresh(force=True)
        if self.favorite_store.load_error:self.message.set('最愛檔案無法讀取，暫以空清單開啟')
        self.tick_job=self.window.after(1000,self.tick)
        if embedded:self.window.bind('<Map>',lambda e:self.refresh() if e.widget is self.window else None)

    def update_state(self,state):
        self.state=state;c=state.get('crafting',{});inv=state.get('inventory',{});room=state.get('furniture',{})
        key=(state.get('player',{}).get('role_id'),self.app.live_active,inv.get('revision'),inv.get('ready'),inv.get('reliable'),room.get('revision'),room.get('owner'),room.get('ready'),c.get('revision'),c.get('pending'),c.get('uncertain'),c.get('status'))
        if key!=self.state_key:
            self.state_key=key
            if self.embedded and not self.window.winfo_ismapped():return
            if self.refresh_job:self.window.after_cancel(self.refresh_job)
            self.refresh_job=self.window.after_idle(self.refresh)

    def close(self):
        if self.closed:return
        self.closed=True
        if self.search_job:self.window.after_cancel(self.search_job)
        if self.refresh_job:self.window.after_cancel(self.refresh_job)
        self.window.after_cancel(self.tick_job)
        self.icons.close()
        if self.window.winfo_exists():self.window.destroy()
        self.panel.browser=None

    def defer_search(self,event=None):
        if self.search_job:self.window.after_cancel(self.search_job)
        self.search_job=self.window.after(200,self.search_now)
    def search_now(self):self.search_job=None;self.page=0;self.refresh_grid(force=True)

    def refresh(self,force=False):
        self.refresh_job=None
        if self.closed:return
        self.state=self.panel.state;c=self.state.get('crafting',{})
        capacity=5 if any(v['item_id']==39050 and v.get('status')==0 for v in self.state.get('furniture',{}).get('items',{}).values()) else 3
        self.queue_label.set(f"製作排程：{len(c.get('queue',{}))}/{capacity}")
        self.favorite_count.set(f'我的最愛：{len(self.favorite_store.ids)}/100'+('' if self.embedded else '（儲存於本機）'))
        tool_ids=sorted({r['tool_id'] for r in RECIPES.values() if confirmed_unlocked(r)})
        signature=(self.only_tools.get(),room_known(self.state),tuple((sid,tool_status(self.state,sid)) for sid in tool_ids))
        if force or signature!=self.tool_key:
            self.tool_key=signature;selected=self.filter_key;self.tool_tree.delete(*self.tool_tree.get_children())
            self.tool_tree.insert('','end',iid='favorites',text='♡ 我的最愛')
            self.tool_tree.insert('','end',iid='all',text='已確認未鎖定項目')
            for sid in tool_ids:
                status=tool_status(self.state,sid)
                if self.only_tools.get() and room_known(self.state) and status!='已擺放':continue
                self.tool_tree.insert('','end',iid=str(sid),text=item_name(sid)+' · '+status)
            if not self.tool_tree.exists(selected):selected='all';self.filter_key='all';self.page=0
            self.tool_tree.selection_set(selected)
        self.refresh_grid(force=force);self.refresh_detail(force=force)
        if self.queue_window and self.queue_window.winfo_exists():self.update_queue()

    def pick_tool(self,event=None):
        selected=self.tool_tree.selection()
        if selected and selected[0]!=self.filter_key:
            self.filter_key=selected[0];self.page=0;self.refresh_grid(force=True)

    def refresh_grid(self,force=False):
        q=self.search.get().strip().casefold();favs=set(self.favorite_store.ids)
        rows=[r for r in RECIPES.values() if confirmed_unlocked(r) and (self.filter_key=='all' or self.filter_key=='favorites' and r['item_id'] in favs or str(r['tool_id'])==self.filter_key) and q in (item_name(r['item_id'])+' '+str(r['item_id'])+' '+item_name(r['tool_id'])).casefold()]
        if self.only_tools.get() and room_known(self.state) and self.filter_key!='favorites':rows=[r for r in rows if tool_status(self.state,r['tool_id'])=='已擺放']
        self.rows=rows;pages=max(1,math.ceil(len(rows)/self.page_size));self.page=min(self.page,pages-1)
        self.page_label.set(f'{self.page+1}/{pages} · 已解鎖 {len(rows)} 項')
        visible=rows[self.page*self.page_size:(self.page+1)*self.page_size]
        signature=(tuple((r['item_id'],availability(self.state,r)[0],r['item_id'] in favs) for r in visible),self.selected)
        if not force and signature==self.grid_key:return
        self.grid_key=signature
        for i,card in enumerate(self.cards):
            if i>=len(visible):card['frame'].grid_remove();card['id']=None;continue
            card['frame'].grid();r=visible[i];sid=r['item_id'];card['id']=sid
            im=card['image']=self.icons.get(sid,32 if self.embedded else 56);name=item_name(sid)
            # Fixed-size grid and bounded 2-line names, no control per all recipes.
            limit=5 if self.embedded else 7
            caption=name if len(name)<=limit else name[:limit-1]+'…'
            card['button'].configure(text=caption,image=im)
            card['favorite'].configure(text='取消收藏' if sid in favs else '收藏',image=self.favorite_images[sid in favs])
            status=availability(self.state,r)[0]
            card['status'].configure(text=('✓ ' if sid==self.selected else '')+status)
        if self.selected not in [r['item_id'] for r in visible]:self.selected=visible[0]['item_id'] if visible else None;self.detail_key=None
        self.refresh_detail()

    def change_page(self,step):
        self.page=max(0,min(max(0,math.ceil(len(self.rows)/self.page_size)-1),self.page+step));self.refresh_grid(force=True)
    def pick_card(self,index):
        sid=self.cards[index]['id']
        if sid:
            self.selected=sid;self.refresh_grid(force=True);self.refresh_detail(force=True)
    def toggle_favorite(self,index):
        sid=self.cards[index]['id']
        if not sid:return
        try:self.favorite_store.toggle(sid)
        except (OSError,ValueError) as exc:self.message.set('最愛儲存失敗：'+str(exc));return
        self.favorite_count.set(f'我的最愛：{len(self.favorite_store.ids)}/100'+('' if self.embedded else '（儲存於本機）'));self.refresh_grid(force=True)

    def refresh_detail(self,force=False):
        recipe=RECIPES.get(str(self.selected));c=self.state.get('crafting',{})
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
        self.hold.set(f"背包持有 {fmt(counts['bag'])}｜小屋已擺 {fmt(counts['placed'])}\n保管中 {fmt(counts['stored'])}｜排程預計產出 {counts['queued']}")
        tool=recipe['tool_id'];self.device.set(f'設備：{item_name(tool)} · {tool_status(self.state,tool)}')
        meta=ICON_MAP.get(str(self.selected),{});size=f"｜{meta['width']:.1f}×{meta['height']:.1f}" if meta.get('width') and meta.get('height') else ''
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

    def add(self):
        if not self.selected:return
        self.panel.add(self.selected,self.count.get())

    def show_queue(self):
        if self.queue_window and self.queue_window.winfo_exists():self.queue_window.lift();return
        w=self.queue_window=tk.Toplevel(self.window);w.title('製作排程');configure_dialog(w,820,420);w.resizable(False,False)
        body=ttk.Frame(w,padding=12);body.pack(fill='both',expand=True)
        self.queue=ttk.Treeview(body,columns=['order','name','count','time'],show='headings',height=5)
        for key,title,width in [('order','順序',55),('name','製作物',300),('count','批數',65),('time','剩餘時間',220)]:self.queue.heading(key,text=title);self.queue.column(key,width=width,anchor='center')
        self.queue.pack(fill='both',expand=True)
        self.queue_activity=tk.StringVar();ttk.Label(body,textvariable=self.queue_activity,wraplength=760).pack(fill='x',before=self.queue)
        self.queue_progress=ttk.Progressbar(body,maximum=100);self.queue_progress.pack(fill='x',before=self.queue,pady=(3,6))
        buttons=ttk.Frame(body);buttons.pack(fill='x',pady=5)
        for label,action in [('開始／接續','start'),('暫停','pause'),('停止接續','stop_auto'),('上移','up'),('下移','down'),('移除','delete')]:ttk.Button(buttons,text=label,command=lambda a=action:self.queue_command(a)).pack(side='left',padx=3)
        self.queue_status=tk.StringVar();ttk.Label(body,textvariable=self.queue_status,style='Muted.TLabel',wraplength=720).pack(fill='x')
        self.queue_key=None;self.update_queue()

    def queue_command(self,action):
        if action in ('up','down','delete'):
            selected=self.queue.selection()
            if not selected:self.queue_status.set('請先選擇製作排程');return
            return self.panel.command(action,index=selected[0])
        self.panel.command(action)

    def update_queue(self):
        c=self.state.get('crafting',{});now=time.monotonic()
        active=next((r for r in c.get('queue',{}).values() if r['index']==c.get('active')),None)
        if active:
            seconds=effective_time(self.state,active)
            total=seconds if seconds is not None else active['base_time']
            spent=elapsed(c,active,now);remaining=max(0,total-spent)
            phase='製作中' if c.get('running') else '已暫停'
            self.queue_activity.set(f"{phase}：{item_name(active['item_id'])}｜剩餘 {duration(remaining)}｜已完成 {c.get('completed',0)} 項")
            self.queue_progress['value']=min(100,100*spent/total) if total>0 else 0
        else:
            self.queue_activity.set(f"等待製作｜排程 {len(c.get('queue',{}))} 項｜已完成 {c.get('completed',0)} 項")
            self.queue_progress['value']=0
        rows=[]
        for iid,row in sorted(c.get('queue',{}).items(),key=lambda value:int(value[0])):
            seconds=effective_time(self.state,row)
            remaining=max(0,(seconds if seconds is not None else row['base_time'])-elapsed(c,row,now))
            text='等待完成回覆' if c.get('completion_requested') and row['index']==c.get('active') else duration(remaining)
            rows.append((str(iid),(row['index'],item_name(row['item_id']),row['count'],text)))
        key=(c.get('revision'),c.get('status'),tuple(rows))
        if key==getattr(self,'queue_key',None):return
        self.queue_key=key;selected=self.queue.selection();self.queue.delete(*self.queue.get_children())
        for iid,values in rows:self.queue.insert('','end',iid=iid,values=values)
        if selected and self.queue.exists(selected[0]):self.queue.selection_set(selected[0])
        self.queue_status.set(c.get('status','等待同步'))

    def tick(self):
        if not self.closed:
            if self.queue_window and self.queue_window.winfo_exists():self.update_queue()
            self.tick_job=self.window.after(1000,self.tick)
