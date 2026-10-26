"""Main-page minimap. Single click selects; double click invokes guarded movement."""
from wlre.paths import PROJECT_ROOT
import math
import tkinter as tk
from wlre.ui.window_layout import configure_dialog
from wlre.ui.rounded_notebook import RoundedNotebook
from tkinter import ttk, messagebox
from PIL import Image,ImageTk
from wlre.features.minimap.ui.minimap import SmallMaps
from wlre.services.world.display_position import current_position
from wlre.services.world.navigation import Repository, NavigationError
from wlre.services.world.map_names import map_label, parse_map_id
from wlre.features.portals.domain.portals import Portals, nearest_marker
from wlre.services.world.portal_policy import allowed_rows, destination_problem
from wlre.features.npc.domain.npc_catalog import NPCIndex, scene_npcs, npc_detail
from wlre.features.npc.domain.npc_talk import load_catalog as load_npc_talks, dialogue_text
from wlre.features.npc.domain.npc_interact import NPCInteractIndex
from wlre.features.npc.domain.npc_shop import shop_catalog
from wlre.features.npc.domain.npc_item_data import item_catalog, sellable


from wlre.features.npc.ui.map_actions import NpcMapActions


from wlre.features.portals.ui.map_actions import PortalMapActions


class HomeMap(PortalMapActions, NpcMapActions, ttk.Frame):
    def __init__(self,parent,on_pick,on_navigation,on_move=None,on_portal=None,status_parent=None,show_status=True,compact=False,on_npc=None,on_npc_next=None):
        super().__init__(parent,padding=8 if compact else 12)
        self.on_pick,self.on_navigation=on_pick,on_navigation
        self.on_move=on_move
        self.on_portal=on_portal
        self.on_npc=on_npc
        self.on_npc_next=on_npc_next
        self.maps=SmallMaps()
        self.portals=Portals()
        try:
            self.npc_index=NPCIndex()
            self.npc_index_error=False
        except (OSError,ValueError,UnicodeError,EOFError):
            # A corrupt optional catalogue must never crash the whole client
            # or silently enable an unverified NPC interaction.
            self.npc_index=None
            self.npc_index_error=True
        # TalkData is optional until the genuine TalkData_C binary is supplied.
        # Never invent game text from numeric S20 identifiers.
        try:
            self.npc_talks=load_npc_talks()
            self.npc_talk_error=False
        except (OSError,ValueError,UnicodeError,EOFError):
            self.npc_talks={}
            self.npc_talk_error=True
        try:
            self.npc_interacts=NPCInteractIndex()
            self.npc_interact_error=False
        except (OSError,ValueError,UnicodeError,EOFError):
            self.npc_interacts=NPCInteractIndex.__new__(NPCInteractIndex)
            self.npc_interacts.scenes={}
            self.npc_interact_error=True
        self.npc_shop_window=None
        self.npc_choice_window=None
        self.npc_history_window=None
        self.npc_rows=[]
        self.selected_npc=None
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
        self.rowconfigure(1,weight=1)
        self.map_title=tk.StringVar(value='小地圖｜等待角色地圖')
        ttk.Label(header,textvariable=self.map_title,style='Heading.TLabel',wraplength=350).pack(side='left',fill='x',expand=True)
        self.portal_status=tk.StringVar(value='單擊選取傳點，按換圖按鈕或雙擊才送出；不會自動走路。')
        body=ttk.Frame(self)
        body.grid(row=1,column=0,sticky='nsew')
        sidebar=ttk.Frame(body,width=125 if compact else 185)
        sidebar.pack(side='left',fill='y',padx=(0,8))
        sidebar.pack_propagate(False)
        lists=RoundedNotebook(sidebar)
        self.portal_tab=ttk.Frame(lists)
        self.npc_tab=ttk.Frame(lists)
        self.monster_tab=ttk.Frame(lists)
        lists.add(self.portal_tab,text='傳點')
        lists.add(self.npc_tab,text='NPC')
        lists.add(self.monster_tab,text='怪物')
        self.portal_list=tk.Listbox(self.portal_tab,exportselection=False,background='#203f53',foreground='#f4e4b5',selectbackground='#e5d9ad',selectforeground='#243b4d',borderwidth=0,highlightthickness=0,activestyle='none',font=('Microsoft JhengHei UI',-14))
        bar=ttk.Scrollbar(self.portal_tab,orient='vertical',command=self.portal_list.yview)
        self.portal_list.configure(yscrollcommand=bar.set)
        bar.pack(side='right',fill='y');self.portal_list.pack(fill='both',expand=True)
        self.portal_list.bind('<<ListboxSelect>>',self.choose_portal)
        self.portal_list.bind('<Double-Button-1>',lambda event:self.go_portal())
        self.npc_message=tk.StringVar(value='選取 NPC 查看資料；目前不會觸發遊戲事件。')
        ttk.Label(self.npc_tab,textvariable=self.npc_message,style='Muted.TLabel',
                  wraplength=120).pack(side='bottom',fill='x',padx=2,pady=3)
        npc_bar=ttk.Scrollbar(self.npc_tab,orient='vertical')
        npc_bar.pack(side='right',fill='y')
        self.npc_shop_button=ttk.Button(self.npc_tab,text='查看 NPC 商店',
                                  command=self.show_npc_shop,state='disabled')
        self.npc_shop_button.pack(side='bottom',fill='x',pady=2)
        self.npc_options_button=ttk.Button(self.npc_tab,text='查看／選擇選項',
                                   command=self.show_npc_choices,state='disabled')
        self.npc_options_button.pack(side='bottom',fill='x',pady=2)
        self.npc_history_button=ttk.Button(self.npc_tab,text='本輪對話紀錄',
                                  command=self.view_npc_history,state='disabled')
        self.npc_history_button.pack(side='bottom',fill='x',pady=2)
        self.npc_text_button=ttk.Button(self.npc_tab,text='查看對話全文',
                                      command=self.view_npc_text,state='disabled')
        self.npc_text_button.pack(side='bottom',fill='x',pady=2)
        self.npc_close_button=ttk.Button(self.npc_tab,text='關閉選項',
                                       command=self.close_npc_option,state='disabled')
        self.npc_close_button.pack(side='bottom',fill='x',pady=2)
        self.npc_next_button=ttk.Button(self.npc_tab,text='下一段對話',command=self.next_npc,state='disabled')
        self.npc_next_button.pack(side='bottom',fill='x',pady=2)
        self.npc_talk_button=ttk.Button(self.npc_tab,text='手動互動 NPC',command=self.interact_npc,state='disabled')
        self.npc_talk_button.pack(side='bottom',fill='x',pady=2)
        self.npc_list=tk.Listbox(self.npc_tab,exportselection=False,background='#203f53',
                                 foreground='#f4e4b5',selectbackground='#e5d9ad',
                                 selectforeground='#243b4d',borderwidth=0,
                                 highlightthickness=0,font=('Microsoft JhengHei UI',-14))
        self.npc_list.configure(yscrollcommand=npc_bar.set)
        npc_bar.configure(command=self.npc_list.yview)
        self.npc_list.pack(fill='both',expand=True)
        self.npc_list.bind('<<ListboxSelect>>',self.choose_npc)
        self.monster_list=tk.Listbox(self.monster_tab,exportselection=False,background='#203f53',foreground='#e5eff4',borderwidth=0,highlightthickness=0,font=('Microsoft JhengHei UI',-14))
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
        self.note=tk.StringVar(value='等待角色地圖同步…')
        legend='紅點：角色　黃圈：目的地\n青色：出口　紫色：事件入口　灰色：未確認\n單擊清單選取；按換圖或雙擊才送出'
        self.status_labels=[]
        if show_status:
            if status_parent is None:
                status_parent=ttk.Frame(self)
                status_parent.grid(row=2,column=0,sticky='ew',pady=(6,0))
            self.status_labels=[]
            for options in ({'textvariable':self.note},{'textvariable':self.portal_status},{'text':legend}):
                label=ttk.Label(status_parent,**options,style='Muted.TLabel',wraplength=430)
                label.pack(fill='x',pady=(2,3));self.status_labels.append(label)
            def wrap_status(event):
                for label in self.status_labels:label.configure(wraplength=max(120,event.width-24))
            status_parent.bind('<Configure>',wrap_status,add='+')
        self.after_idle(self.draw)

    def show_map(self,map_id):
        self.route=None
        self.image=None
        self.mesh=None
        self.projection=None
        try:
            self.selected_id=parse_map_id(map_id)
            self.map_title.set('小地圖｜'+map_label(self.selected_id))
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
        self.selected_npc=None
        self.portal_list.delete(0,'end')
        self.npc_list.delete(0,'end')
        self.npc_message.set('NPC 索引檔無效：已停用索引資料。' if self.npc_index_error
                             else '選取 NPC 查看名稱、座標與事件索引核對狀態。')
        self.list_rows=[]
        for p in self.portal_rows:
            prefix='↩ 返回：' if recovery else ('◎ ' if p.get('direct_eligible') else '○ ')
            self.portal_list.insert('end',prefix+p['name'])
            self.list_rows.append(p)
        self.monster_list.delete(0,'end')
        self.monster_rows=[]
        entities=self.portals.data.get('entities',{}).get(str(self.selected_id),[])
        self.npc_rows=scene_npcs(self.selected_id,entities,self.npc_index)
        for npc in self.npc_rows:
            marker='◆' if npc['verified'] else '◇'
            self.npc_list.insert('end',f"{marker} {npc['name']}")
        for e in entities:
            if e['kind']!=0:
                self.monster_list.insert('end',f"Lv.{e['level'] if e['level'] is not None else '?'} {e['name']}")
                self.monster_rows.append(e)
        if not self.list_rows:self.portal_list.insert('end','（沒有已確認的返回出口）' if recovery else '（來源未列傳點）')
        if not self.npc_rows:self.npc_list.insert('end','（本場景尚無 NPC 資料）')
        if not self.monster_rows:self.monster_list.insert('end','（來源未列怪物）')
        ready=sum(bool(p.get('direct_eligible')) for p in self.portal_rows)
        if recovery:
            text=(f'此圖沒有小地圖；左側保留 {ready} 個返回有圖地圖的出口。' if ready
                  else '此圖沒有小地圖，來源未列可確認的返回出口；請使用官方客戶端離開。')
        else:
            text=f'可見 {len(self.portal_rows)} 個傳點；{ready} 個可直接嘗試；已隱藏缺圖及目的地未確認的入口。'
        self.portal_status.set(text)
        self.update_portal_button()
















    def choose_monster(self,event=None):
        selected=self.monster_list.curselection()
        if not selected or selected[0]>=len(self.monster_rows):return
        p=self.monster_rows[selected[0]]
        self.selected_portal=None;self.update_portal_button()
        self.portal_status.set(p['name']+'｜資料表的分布參考點，並非即時怪物位置。')
        if p['x'] is not None:self.on_pick(self.selected_id,p['x'],p['y'])
        self.draw()



    def show_audit(self):
        if self.audit_window and self.audit_window.winfo_exists():
            self.audit_window.lift();return
        win=tk.Toplevel(self);self.audit_window=win
        win.title('地圖傳送點逐圖核對 · 1262');configure_dialog(win,1000,600);win.resizable(False,False)
        ttk.Label(win,text='已核對數量只代表門編號與觸碰事件有效，正式服是否允許遠距觸發仍待實測。').pack(fill='x',padx=10,pady=8)
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
                                    text=('等待角色地圖同步…' if self.selected_id is None else '此場景沒有原始小地圖\n請從左側清單選擇返回出口\n地圖圖示與座標操作已停用'),fill='#c8d3dc',font=('Microsoft JhengHei UI',-14),justify='center')
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
        for npc in self.npc_rows:
            x,y=npc['x'],npc['y']
            if x is None or y is None or not 0<=x<=65535 or not 0<=y<=65535:
                continue
            u,v=self.projection.packet_to_pixel(x,y)
            if not 0<=u<=1024 or not 0<=v<=1024:
                continue
            px,py=self.screen_pixel(u,v)
            selected=npc is self.selected_npc
            radius=5 if selected else 3
            self.canvas.create_oval(px-radius,py-radius,px+radius,py+radius,
                                    fill='#be8bec',outline='#fff3c1' if selected else '')
            if selected:
                self.canvas.create_text(px,py-12,text=npc['name'],fill='white',anchor='s')
        location=self.state.get('location',{})
        fix=location.get('confirmed')
        displayed=current_position(self.state)
        if displayed and displayed['scene']==self.selected_id:
            if displayed['kind']=='local_report' and fix:
                x,y=self.screen_pixel(*self.projection.packet_to_pixel(fix['x'],fix['y']))
                self.canvas.create_oval(x-5,y-5,x+5,y+5,fill='',outline='#b7bec7',width=2)
                self.canvas.create_text(x+9,y-12,text=f"上次位置 ({fix['x']}, {fix['y']})",fill='#c5cbd3',anchor='w')
            x,y=self.screen_pixel(*self.projection.packet_to_pixel(displayed['x'],displayed['y']))
            self.canvas.create_oval(x-6,y-6,x+6,y+6,fill='#ed4747' if displayed['filled'] else '',outline='#ff5959',width=2)
            self.canvas.create_text(x+9,y+13,text=f"({displayed['x']}, {displayed['y']})",fill='white',anchor='w')
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
        # NPC markers are position references, not walk or event commands.
        npc_candidates=[]
        for npc in self.npc_rows:
            if npc['x'] is None or npc['y'] is None or not 0<=npc['x']<=65535 or not 0<=npc['y']<=65535:
                continue
            u,v=self.projection.packet_to_pixel(npc['x'],npc['y'])
            if not 0<=u<=1024 or not 0<=v<=1024:
                continue
            px,py=self.screen_pixel(u,v)
            if math.hypot(px-event.x,py-event.y)<=8:
                npc_candidates.append((math.hypot(px-event.x,py-event.y),npc))
        if npc_candidates:
            self.select_npc(min(npc_candidates,key=lambda x:x[0])[1])
            return False
        self.selected_portal=None
        self.selected_npc=None
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
        if scene is not None and (force or scene!=self.selected_id):
            self.show_map(scene)
        self.update_npc_buttons()
        self.show_dialogue_status()
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
