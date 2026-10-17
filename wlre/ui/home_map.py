"""Main-page minimap. Single click selects; double click invokes guarded movement."""
from wlre.paths import PROJECT_ROOT
import math
import tkinter as tk
from wlre.ui.rounded_notebook import RoundedNotebook
from tkinter import ttk
from PIL import Image,ImageTk
from wlre.ui.minimap import SmallMaps
from wlre.services.world.display_position import current_position
from wlre.services.world.navigation import Repository, NavigationError
from wlre.services.world.map_names import map_label, map_choices, parse_map_id
from wlre.services.world.portals import Portals, nearest_marker
from wlre.services.world.portal_policy import allowed_rows, destination_problem


class HomeMap(ttk.Frame):
    def __init__(self,parent,on_pick,on_navigation,on_move=None,on_portal=None,status_parent=None,show_status=True,compact=False):
        super().__init__(parent,padding=8 if compact else 12)
        self.on_pick,self.on_navigation=on_pick,on_navigation
        self.on_move=on_move
        self.on_portal=on_portal
        self.maps=SmallMaps()
        self.portals=Portals()
        self.portal_rows=[]
        self.selected_portal=None
        self.audit_window=None
        self.repository=Repository()
        self.state={}
        self.route=None
        self.image=None
        self.photo=None
        self.mesh=None
        self.projection=None
        self.selected_id=None
        self._resize_job=None
        self._signature=None
        header=ttk.Frame(self)
        header.grid(row=0,column=0,sticky='ew')
        self.columnconfigure(0,weight=1)
        self.rowconfigure(3,weight=1)
        ttk.Label(header,text='小地圖',style='Heading.TLabel').pack(side='left')
        ttk.Button(header,text='進階導航',command=on_navigation).pack(side='right')
        choose=ttk.Frame(self)
        choose.grid(row=1,column=0,sticky='ew',pady=(10,6))
        self.choice=tk.StringVar(value=map_label(12903))
        self.map_choices=[value for value in map_choices() if self.maps.has_image(parse_map_id(value))]
        combo=ttk.Combobox(choose,textvariable=self.choice,values=self.map_choices,width=30)
        combo.pack(side='left',fill='x',expand=True)
        combo.bind('<<ComboboxSelected>>',lambda e:self.manual_load())
        combo.bind('<Return>',lambda e:self.manual_load())
        ttk.Button(choose,text='載入',command=self.manual_load).pack(side='left',padx=(6,0))
        switches=ttk.Frame(self)
        switches.grid(row=2,column=0,sticky='ew',pady=(0,6))
        self.follow=tk.BooleanVar(value=True)
        self.overlay=tk.BooleanVar(value=False)
        ttk.Checkbutton(switches,text='跟隨目前地圖',variable=self.follow,command=lambda:self.set_state(self.state,True)).pack(side='left')
        ttk.Checkbutton(switches,text='導航邊界',variable=self.overlay,command=self.draw).pack(side='left',padx=10)
        ttk.Label(switches,text='單擊選點・雙擊移動',style='Muted.TLabel').pack(side='right')
        self.portal_status=tk.StringVar(value='單擊選取傳點，按換圖按鈕或雙擊才送出；不會自動走路。')
        body=ttk.Frame(self)
        body.grid(row=3,column=0,sticky='nsew')
        sidebar=ttk.Frame(body,width=155 if compact else 185)
        sidebar.pack(side='left',fill='y',padx=(0,8))
        sidebar.pack_propagate(False)
        lists=RoundedNotebook(sidebar)
        self.npc_tab=ttk.Frame(lists)
        self.monster_tab=ttk.Frame(lists)
        lists.add(self.npc_tab,text='NPC')
        lists.add(self.monster_tab,text='怪物')
        self.portal_list=tk.Listbox(self.npc_tab,exportselection=False,background='#203f53',foreground='#f4e4b5',selectbackground='#e5d9ad',selectforeground='#243b4d',borderwidth=0,highlightthickness=0,activestyle='none',font=('Microsoft JhengHei UI',-16))
        bar=ttk.Scrollbar(self.npc_tab,orient='vertical',command=self.portal_list.yview)
        self.portal_list.configure(yscrollcommand=bar.set)
        bar.pack(side='right',fill='y');self.portal_list.pack(fill='both',expand=True)
        self.portal_list.bind('<<ListboxSelect>>',self.choose_portal)
        self.portal_list.bind('<Double-Button-1>',lambda event:self.go_portal())
        self.monster_list=tk.Listbox(self.monster_tab,exportselection=False,background='#203f53',foreground='#e5eff4',borderwidth=0,highlightthickness=0,font=('Microsoft JhengHei UI',-16))
        mbar=ttk.Scrollbar(self.monster_tab,orient='vertical',command=self.monster_list.yview)
        self.monster_list.configure(yscrollcommand=mbar.set)
        mbar.pack(side='right',fill='y');self.monster_list.pack(fill='both',expand=True)
        self.monster_list.bind('<<ListboxSelect>>',self.choose_monster)
        self.portal_go=ttk.Button(sidebar,text='直接嘗試換圖',command=self.go_portal,state='disabled')
        ttk.Button(sidebar,text='逐圖核對',command=self.show_audit).pack(side='bottom',fill='x')
        self.portal_go.pack(side='bottom',fill='x',pady=(6,3))
        lists.pack(fill='both',expand=True)
        mapbody=ttk.Frame(body)
        mapbody.pack(side='left',fill='both',expand=True)
        self.canvas=tk.Canvas(mapbody,background='#18232c',highlightthickness=0,width=300 if compact else 420,height=240 if compact else 280)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',self.resize)
        self.canvas.bind('<Button-1>',self.pick)
        self.canvas.bind('<Double-Button-1>',self.double_pick)
        self.note=tk.StringVar(value='正在載入小地圖…')
        legend='紅點：角色　黃圈：目的地\n青色：出口　紫色：事件入口　灰色：未確認\n單擊清單選取；按換圖或雙擊才送出'
        self.status_labels=[]
        if show_status:
            if status_parent is None:
                status_parent=ttk.Frame(self)
                status_parent.grid(row=4,column=0,sticky='ew',pady=(6,0))
            self.status_labels=[]
            for options in ({'textvariable':self.note},{'textvariable':self.portal_status},{'text':legend}):
                label=ttk.Label(status_parent,**options,style='Muted.TLabel',wraplength=430)
                label.pack(fill='x',pady=(2,3));self.status_labels.append(label)
            def wrap_status(event):
                for label in self.status_labels:label.configure(wraplength=max(120,event.width-24))
            status_parent.bind('<Configure>',wrap_status,add='+')
        self.after_idle(lambda:self.show_map(12903))

    def manual_load(self):
        self.follow.set(False)
        self.show_map(self.choice.get())

    def show_map(self,map_id):
        self.route=None
        self.image=None
        self.mesh=None
        self.projection=None
        try:
            self.selected_id=parse_map_id(map_id)
            self.choice.set(map_label(self.selected_id))
            self.projection,scene=self.maps.projection(self.selected_id)
            self.image=self.maps.image(scene)
            if self.image is not None:
                try:self.mesh=self.repository.load(scene)
                except NavigationError:pass
                self.note.set(map_label(self.selected_id)+'｜原始小地圖')
            else:
                self.projection=None
                self.note.set(map_label(self.selected_id)+'｜沒有原始小地圖；請使用左側返回出口。')
        except (OSError,ValueError,KeyError) as exc:
            self.image=None;self.mesh=None;self.projection=None
            self.note.set(str(exc))
        self.refresh_portals()
        self.draw()

    def refresh_portals(self):
        recovery=self.image is None
        self.portal_rows=allowed_rows(self.portals,self.selected_id,self.maps,recovery=recovery)
        self.selected_portal=None
        self.portal_list.delete(0,'end')
        self.list_rows=[]
        for p in self.portal_rows:
            prefix='↩ 返回：' if recovery else ('◎ ' if p.get('direct_eligible') else '○ ')
            self.portal_list.insert('end',prefix+p['name'])
            self.list_rows.append(p)
        self.monster_list.delete(0,'end')
        self.monster_rows=[]
        for e in self.portals.data.get('entities',{}).get(str(self.selected_id),[]):
            if e['kind']==0:
                self.portal_list.insert('end','◆ '+e['name']);self.list_rows.append(e)
            else:
                self.monster_list.insert('end',f"Lv.{e['level'] if e['level'] is not None else '?'} {e['name']}")
                self.monster_rows.append(e)
        if not self.list_rows:self.portal_list.insert('end','（沒有已確認的返回出口）' if recovery else '（來源未列 NPC／傳點）')
        if not self.monster_rows:self.monster_list.insert('end','（來源未列怪物）')
        ready=sum(bool(p.get('direct_eligible')) for p in self.portal_rows)
        if recovery:
            text=(f'此圖沒有小地圖；左側保留 {ready} 個返回有圖地圖的出口。' if ready
                  else '此圖沒有小地圖，來源未列可確認的返回出口；請使用官方客戶端離開。')
        else:
            text=f'可見 {len(self.portal_rows)} 個傳點；{ready} 個可直接嘗試；已隱藏缺圖及目的地未確認的入口。'
        self.portal_status.set(text)
        self.update_portal_button()

    def update_portal_button(self):
        p=self.selected_portal
        enabled=bool(p and destination_problem(p,self.maps) is None and p.get('direct_eligible') and self.state.get('player',{}).get('scene')==self.selected_id and not self.state.get('battle',{}).get('active') and not self.state.get('event_flow',{}).get('blocked'))
        self.portal_go.configure(state='normal' if enabled else 'disabled',
                                 text='返回有圖地圖' if self.image is None else '直接嘗試換圖')

    def choose_portal(self,event=None):
        selected=self.portal_list.curselection()
        if not selected or selected[0]>=len(self.list_rows):return
        p=self.list_rows[selected[0]]
        if 'source' in p:
            self.select_portal(p)
        else:
            self.selected_portal=None;self.update_portal_button()
            self.portal_status.set(p['name']+'｜NPC 位置參考；雙擊小地圖即可移動。')
            if p['x'] is not None:self.on_pick(self.selected_id,p['x'],p['y'])
            self.draw()

    def choose_monster(self,event=None):
        selected=self.monster_list.curselection()
        if not selected or selected[0]>=len(self.monster_rows):return
        p=self.monster_rows[selected[0]]
        self.selected_portal=None;self.update_portal_button()
        self.portal_status.set(p['name']+'｜資料表的分布參考點，並非即時怪物位置。')
        if p['x'] is not None:self.on_pick(self.selected_id,p['x'],p['y'])
        self.draw()

    def select_portal(self,p):
        self.selected_portal=p
        self.portal_list.selection_clear(0,'end')
        self.portal_list.selection_set(self.list_rows.index(p))
        self.portal_list.see(self.list_rows.index(p))
        self.portal_status.set(p['name']+'｜'+p.get('direct_note','尚未核對觸碰事件'))
        self.update_portal_button()
        self.draw()

    def go_portal(self):
        if not self.selected_portal:return False
        try:
            problem=destination_problem(self.selected_portal,self.maps)
            if problem:raise ValueError(problem)
            self.portals.direct_target(self.selected_portal,self.state.get('player',{}).get('scene'))
            if self.on_portal is None:
                raise ValueError('尚未接上本機角色的出口觸發功能。')
            self.on_portal(self.selected_portal['id'])
            return True
        except ValueError as exc:
            self.portal_status.set(str(exc));return False

    def show_audit(self):
        if self.audit_window and self.audit_window.winfo_exists():
            self.audit_window.lift();return
        win=tk.Toplevel(self);self.audit_window=win
        win.title('地圖傳送點逐圖核對 · 1262');win.geometry('960x540');win.resizable(False,False)
        ttk.Label(win,text='雙擊地圖列可預覽。已核對數量只代表門編號與觸碰事件有效，正式服是否允許遠距觸發仍待實測。').pack(fill='x',padx=10,pady=8)
        def open_report():
            import webbrowser
            webbrowser.open((PROJECT_ROOT/'docs/Portal_Review_1262.html').as_uri())
        ttk.Button(win,text='開啟完整逐筆核對報告',command=open_report).pack(anchor='e',padx=10,pady=(0,6))
        body=ttk.Frame(win);body.pack(fill='both',expand=True,padx=10)
        cols=('scene','name','count','normal','event','nav','status')
        tree=ttk.Treeview(body,columns=cols,show='headings')
        for c,label,w in zip(cols,('地圖ID','名稱','傳點數','一般出口','事件入口','可直接嘗試','核對結果'),(65,165,65,70,70,100,290)):
            tree.heading(c,text=label);tree.column(c,width=w,minwidth=45)
        bar=ttk.Scrollbar(body,orient='vertical',command=tree.yview);bar.pack(side='right',fill='y')
        tree.configure(yscrollcommand=bar.set);tree.pack(fill='both',expand=True)
        for row in self.portals.audit.values():
            tree.insert('', 'end',iid=str(row['scene']),values=(row['scene'],row['name'],row['count'],row['normal'],row['event'],row.get('direct_ready',0),row['status']))
        def preview(event=None):
            if tree.selection():self.follow.set(False);self.show_map(int(tree.selection()[0]))
        tree.bind('<Double-Button-1>',preview)
        ttk.Button(win,text='預覽選取地圖',command=preview).pack(pady=8)

    def resize(self,event):
        if self._resize_job:self.after_cancel(self._resize_job)
        self._resize_job=self.after(60,self.draw)

    def view(self):
        w,h=self.canvas.winfo_width(),self.canvas.winfo_height()
        size=max(1,min(w,h)-16)
        return (w-size)/2,(h-size)/2,size/1024

    def screen_pixel(self,u,v):
        left,top,scale=self.view()
        return left+u*scale,top+v*scale

    def draw(self):
        self._resize_job=None
        self.canvas.delete('all')
        if not self.projection:
            self.canvas.create_text(self.canvas.winfo_width()/2,self.canvas.winfo_height()/2,
                                    text='此場景沒有原始小地圖\n請從左側清單選擇返回出口\n地圖圖示與座標操作已停用',fill='#c8d3dc',font=('Microsoft JhengHei UI',-16),justify='center')
            return
        left,top,scale=self.view()
        size=max(1,round(1024*scale))
        if self.image:
            image_key=(self.selected_id,size)
            if getattr(self,'_photo_key',None)!=image_key or getattr(self,'_photo_source',None) is not self.image:
                self.photo=ImageTk.PhotoImage(self.image.resize((size,size),Image.Resampling.LANCZOS),master=self.canvas)
                self._photo_key=image_key
                self._photo_source=self.image
            self.canvas.create_image(left,top,image=self.photo,anchor='nw')
        if self.mesh and (self.overlay.get() or self.image is None):
            for tri in self.mesh.faces:
                xy=[c for p in tri for c in self.screen_pixel(*self.projection.navigation_to_pixel(p[0],p[2]))]
                self.canvas.create_polygon(*xy,fill='',outline='#65c6d5',width=1)
        if self.route:
            xy=[c for p in self.route['points'] for c in self.screen_pixel(*self.projection.navigation_to_pixel(p[0],p[2]))]
            if len(xy)>=4:self.canvas.create_line(*xy,fill='#ffce58',width=3)
        for p in self.portal_rows:
            if not p['coordinate_valid']:continue
            px,py=self.screen_pixel(*self.projection.packet_to_pixel(p['x'],p['y']))
            color='#b591ff' if p['kind']=='event' else '#57e9ef'
            if not p.get('direct_eligible'):color='#9b9b9b'
            selected=p is self.selected_portal
            r=8 if selected else 5
            self.canvas.create_oval(px-r-2,py-r-2,px+r+2,py+r+2,fill='#183e4d',outline='#fff6a0' if selected else '#dafcff',width=2)
            spiral=[]
            for step in range(37):
                angle=step/36*math.pi*3.5;radius=step/36*r
                spiral.extend((px+math.cos(angle)*radius,py+math.sin(angle)*radius))
            self.canvas.create_line(*spiral,fill=color,width=2,smooth=True)
            if selected:self.canvas.create_text(px,py-14,text=p['name'],fill='white',anchor='s')
        location=self.state.get('location',{})
        fix=location.get('confirmed')
        displayed=current_position(self.state)
        if displayed and displayed['scene']==self.selected_id:
            if displayed['kind']=='local_report' and fix:
                x,y=self.screen_pixel(*self.projection.packet_to_pixel(fix['x'],fix['y']))
                self.canvas.create_oval(x-5,y-5,x+5,y+5,fill='',outline='#b7bec7',width=2)
                self.canvas.create_text(x+9,y-12,text=f"末次確認 ({fix['x']}, {fix['y']})",fill='#c5cbd3',anchor='w')
            x,y=self.screen_pixel(*self.projection.packet_to_pixel(displayed['x'],displayed['y']))
            self.canvas.create_oval(x-6,y-6,x+6,y+6,fill='#ed4747' if displayed['filled'] else '',outline='#ff5959',width=2)
            self.canvas.create_text(x+9,y+13,text=f"{displayed['label']} ({displayed['x']}, {displayed['y']})",fill='white',anchor='w')
        targets=[t for t in (location.get('requested_destination'),location.get('server_destination')) if t and t.get('scene')==self.selected_id]
        local=self.state.get('local_movement')
        if local and local.get('scene')==self.selected_id:
            targets=[local['target']]
        if targets:
            target=max(targets,key=lambda t:t.get('packet_number',0))
            x,y=self.screen_pixel(*self.projection.packet_to_pixel(target['x'],target['y']))
            self.canvas.create_oval(x-7,y-7,x+7,y+7,outline='#ffc654',width=2)
        if not self.state.get('player'):
            self.canvas.create_text(left+12,top+12,text='離線地圖預覽',fill='white',anchor='nw')

    def pick(self,event):
        if not self.projection:return False
        marker=nearest_marker(self.portal_rows,self.projection,self.screen_pixel,event.x,event.y)
        if marker is not None:
            self.select_portal(marker)
            return False
        self.selected_portal=None
        self.update_portal_button()
        left,top,scale=self.view()
        u,v=(event.x-left)/scale,(event.y-top)/scale
        if not (0<=u<=1024 and 0<=v<=1024):return False
        x,y=self.projection.pixel_to_packet(u,v)
        x,y=round(x),round(y)
        if not (0<=x<=65535 and 0<=y<=65535):
            self.note.set('此處超出遊戲座標範圍。');return False
        return self.on_pick(self.selected_id,x,y) is not False

    def double_pick(self,event):
        marker=nearest_marker(self.portal_rows,self.projection,self.screen_pixel,event.x,event.y) if self.projection else None
        if marker is not None:
            self.select_portal(marker);self.go_portal()
        elif self.pick(event) and self.on_move is not None:self.on_move()
        return 'break'

    def set_state(self,state,force=False):
        previous_navigation=self.state.get('navigation',{})
        self.state=state or {}
        self.update_portal_button()
        scene=self.state.get('player',{}).get('scene')
        if self.follow.get() and scene is not None and (force or scene!=self.selected_id):
            self.show_map(scene)
        travel=self.state.get('portal_travel',{})
        if travel and travel.get('scene')==scene:self.portal_status.set(travel.get('name','')+'｜'+travel.get('reason',''))
        nav=self.state.get('navigation',{})
        if (nav.get('scene')==self.selected_id and
                nav.get('revision')!=previous_navigation.get('revision')):
            self.route=None
        if self.image is not None and nav.get('stale') and nav.get('scene')==self.selected_id:
            self.route=None
            self.note.set('障礙資料已變更，舊路徑已清除。')
        loc=self.state.get('location',{})
        signature=(scene,str(loc),nav.get('revision'),nav.get('stale'),str(self.state.get('local_movement')))
        if force or signature!=self._signature:
            self._signature=signature
            self.draw()

    def set_route(self,result):
        if result is None:
            self.route=None;self.draw();return
        if not self.mesh or result['scene_resource']!=self.mesh.scene_id:return
        nav=self.state.get('navigation',{})
        if self.image is not None and nav.get('stale') and nav.get('scene')==self.selected_id:return
        self.route=result
        self.draw()
