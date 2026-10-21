"""Main-page minimap. Single click selects; double click invokes guarded movement."""
from wlre.paths import PROJECT_ROOT
import math
import tkinter as tk
from wlre.ui.window_layout import configure_dialog
from wlre.ui.rounded_notebook import RoundedNotebook
from tkinter import ttk, messagebox
from PIL import Image,ImageTk
from wlre.ui.minimap import SmallMaps
from wlre.services.world.display_position import current_position
from wlre.services.world.navigation import Repository, NavigationError
from wlre.services.world.map_names import map_label, parse_map_id
from wlre.services.world.portals import Portals, nearest_marker
from wlre.services.world.portal_policy import allowed_rows, destination_problem
from wlre.services.world.npc_catalog import NPCIndex, scene_npcs, npc_detail
from wlre.services.world.npc_talk import load_catalog as load_npc_talks, dialogue_text
from wlre.services.world.npc_interact import NPCInteractIndex
from wlre.services.world.npc_shop import shop_catalog
from wlre.services.world.npc_item_data import item_catalog, sellable


class HomeMap(ttk.Frame):
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

    def update_portal_button(self):
        p=self.selected_portal
        enabled=bool(p and destination_problem(p,self.maps) is None and p.get('direct_eligible') and self.state.get('player',{}).get('scene')==self.selected_id and not self.state.get('battle',{}).get('active') and not self.state.get('event_flow',{}).get('blocked'))
        self.portal_go.configure(state='normal' if enabled else 'disabled',
                                 text='返回有圖地圖' if self.image is None else '直接嘗試換圖')

    def choose_portal(self,event=None):
        selected=self.portal_list.curselection()
        if not selected or selected[0]>=len(self.list_rows):return
        p=self.list_rows[selected[0]]
        self.select_portal(p)

    def choose_npc(self,event=None):
        selected=self.npc_list.curselection()
        if not selected or selected[0]>=len(self.npc_rows):return
        npc=self.npc_rows[selected[0]]
        self.select_npc(npc)
        if npc['x'] is not None and 0<=npc['x']<=65535 and 0<=npc['y']<=65535:
            self.on_pick(self.selected_id,npc['x'],npc['y'])

    def select_npc(self,npc):
        self.selected_npc=npc
        self.selected_portal=None
        self.portal_list.selection_clear(0,'end')
        self.update_portal_button()
        self.npc_list.selection_clear(0,'end')
        pos=next((i for i,row in enumerate(self.npc_rows) if row is npc),None)
        if pos is not None:
            self.npc_list.selection_set(pos)
            self.npc_list.see(pos)
        self.npc_message.set(npc_detail(npc))
        self.update_npc_buttons()
        self.draw()

    def update_npc_buttons(self):
        npc=self.selected_npc
        current=self.state or {}
        player=current.get('player',{})
        loc=current.get('location',{})
        confirmed=loc.get('confirmed') or {}
        battle=current.get('battle',{})
        dialogue=current.get('npc_dialogue',{})
        post=(battle.get('post_event') or {}).get('status')
        moving=(current.get('local_movement') or {}).get('status') in ('running','finished')
        can_start=(self.on_npc is not None and npc is not None and npc.get('verified')
                   and npc.get('event_count',0)>0 and current.get('phase')=='world_ready'
                   and npc.get('scene')==player.get('scene')==confirmed.get('scene')
                   and loc.get('confirmed_is_current') and not moving
                   and not current.get('roaming',{}).get('enabled')
                   and not battle.get('active') and post in (None,'completed')
                   and not current.get('event_flow',{}).get('blocked'))
        self.npc_talk_button.configure(state='normal' if can_start else 'disabled')
        can_next=(self.on_npc_next is not None and not battle.get('active')
                  and dialogue.get('active')
                  and dialogue.get('scene')==player.get('scene')
                  and dialogue.get('phase') in ('talk','continue'))
        self.npc_next_button.configure(state='normal' if can_next else 'disabled')
        can_close=(self.on_npc_next is not None and dialogue.get('active')
                   and dialogue.get('phase')=='choice_unavailable'
                   and dialogue.get('effect_type')==6
                   and dialogue.get('scene')==player.get('scene')
                   and not battle.get('active'))
        known_shop=(self.npc_interacts.get(dialogue.get('scene'),dialogue.get('option_index'))
                    if can_close else None)
        is_shop=bool(known_shop and known_shop['form_kind'] in (2,3))
        self.npc_close_button.configure(state='normal' if can_close and not is_shop else 'disabled')
        current_shop=(shop_catalog(dialogue.get('scene'),dialogue.get('option_index'),
                      index=self.npc_interacts) if is_shop else None)
        self.npc_shop_button.configure(
            state='normal' if is_shop and current_shop and self.on_npc_next is not None
            else 'disabled')
        can_view=(dialogue.get('active') and dialogue.get('phase')=='talk'
                  and dialogue_text(self.npc_talks,dialogue.get('text_id')) is not None)
        self.npc_text_button.configure(state='normal' if can_view else 'disabled')
        history=dialogue.get('history') or []
        self.npc_history_button.configure(state='normal' if history else 'disabled')
        choices=(self.npc_interacts.choices(dialogue.get('scene'),
                 dialogue.get('option_index'), self.npc_talks)
                 if dialogue.get('active') and dialogue.get('phase')=='choice_unavailable'
                 and dialogue.get('scene')==player.get('scene') and not battle.get('active')
                 else None)
        self.npc_options_button.configure(
            state='normal' if choices is not None and self.on_npc_next is not None else 'disabled')

    def interact_npc(self):
        npc=self.selected_npc
        if npc is None or str(self.npc_talk_button.cget('state'))!='normal':
            return
        if not messagebox.askyesno('確認 NPC 互動',
                '只送出一次官方 C20-1。NPC 事件可能啟動戰鬥、任務或未支援的選項。'
                '\n不會自動靠近、購物或重送封包。確定要互動嗎？',parent=self):
            return
        self.on_npc({'type':'npc_start','confirmed':True,'scene':npc['scene'],
                     'npc_index':npc['npc_index'],'npc_id':npc['npc_id'],
                     'x':npc['x'],'y':npc['y']})

    def next_npc(self):
        if str(self.npc_next_button.cget('state'))=='normal':
            self.on_npc_next({'type':'npc_next'})

    def show_npc_shop(self):
        """Read-only shop listing backed by official Eve; never send purchases."""
        if str(self.npc_shop_button.cget('state'))!='normal':
            return
        info=self.state.get('npc_dialogue',{})
        if (not info.get('active') or info.get('phase')!='choice_unavailable'
                or self.state.get('player',{}).get('scene')!=info.get('scene')):
            return
        catalog=shop_catalog(info.get('scene'),info.get('option_index'),
                             index=self.npc_interacts)
        if catalog is None:
            return
        if self.npc_shop_window is not None:
            try:
                if self.npc_shop_window.winfo_exists():
                    self.npc_shop_window.destroy()
            except tk.TclError:
                pass
        win=tk.Toplevel(self)
        self.npc_shop_window=win
        win.title('NPC '+catalog['title']+'（官方價格預覽／交易未啟用）')
        win.geometry('680x440')
        win.transient(self.winfo_toplevel())
        body=ttk.Frame(win,padding=12)
        body.pack(fill='both',expand=True)
        ttk.Label(body,text=catalog['title']+'｜商品 ID：Eve 1262；金額：ItemData_C 基礎價',
                  wraplength=640).pack(fill='x',pady=(0,6))
        tabs=ttk.Notebook(body)
        tabs.pack(fill='both',expand=True)
        offers=ttk.Frame(tabs)
        owned=ttk.Frame(tabs)
        tabs.add(offers,text='購買商品（唯讀）')
        tabs.add(owned,text='背包／販售預覽（唯讀）')
        def add_grid(parent,columns,widths):
            frame=ttk.Frame(parent)
            frame.pack(fill='both',expand=True,pady=5)
            tree=ttk.Treeview(frame,columns=columns,show='headings',selectmode='browse')
            for key,title,width in widths:
                tree.heading(key,text=title)
                tree.column(key,width=width,anchor='w')
            scroll=ttk.Scrollbar(frame,orient='vertical',command=tree.yview)
            tree.configure(yscrollcommand=scroll.set)
            scroll.pack(side='right',fill='y')
            tree.pack(side='left',fill='both',expand=True)
            return tree
        items=add_grid(offers,('index','id','name','price'),(
            ('index','商品索引',85),('id','官方物品 ID',105),
            ('name','官方物品名稱',260),('price','金幣基礎價',125)))
        for row in catalog['products']:
            items.insert('','end',values=(row['offer_index'],row['item_id'],
                         row['name'],row['price_gold'] if row['price_gold'] is not None else '資料未核實'))
        bag=add_grid(owned,('slot','id','name','count','sale'),(
            ('slot','格位',70),('id','物品 ID',95),('name','物品名稱',230),
            ('count','數量',75),('sale','NPC 收購價／限制',150)))
        try:
            verified_items=item_catalog()
        except (OSError,ValueError,EOFError,UnicodeError):
            verified_items={}
        inv=self.state.get('inventory',{})
        if inv.get('ready') and inv.get('reliable'):
            for slot,record in sorted(inv.get('items',{}).items(),
                                      key=lambda x:int(x[0])):
                item_id=record.get('item_id')
                if type(item_id) is int:
                    official=verified_items.get(item_id)
                    sale=(('不可賣給 NPC' if not sellable(official)
                           else str(official['sell_price'])) if official else '來源未核實')
                    bag.insert('','end',values=(slot,item_id,
                               official['name'] if official else f'物品 {item_id}',
                               record.get('count',0),sale))
        else:
            ttk.Label(owned,text='背包尚未由伺服器可靠同步，不顯示推定可售商品。').pack()
        ttk.Label(body,text=catalog['reason'],wraplength=640,
                  foreground='#ad5b32').pack(fill='x',pady=6)
        ttk.Label(body,text='顯示 ItemData_C 官方基礎價；實際折扣後價格和當前持有金幣尚待同步。禁止購買或販售。',
                  wraplength=640).pack(fill='x')
        ttk.Button(body,text='關閉商店（需伺服器確認）',
                   command=lambda:self.close_npc_shop_dialog(catalog)).pack(fill='x',pady=(8,0))
        win.protocol('WM_DELETE_WINDOW',lambda:self.close_npc_shop_dialog(catalog))

    def close_npc_shop_dialog(self,catalog):
        info=self.state.get('npc_dialogue',{})
        if (not info.get('active') or info.get('phase')!='choice_unavailable'
                or info.get('effect_type')!=6
                or info.get('scene')!=catalog['scene']
                or info.get('option_index')!=catalog['interact_index']
                or self.state.get('battle',{}).get('active')
                or self.on_npc_next is None):
            return
        current=shop_catalog(info['scene'],info['option_index'],
                             index=self.npc_interacts)
        if current!=catalog:
            return
        if not messagebox.askyesno('確認關閉商店',
                '官方 C20-9 空內容關閉商店，不會購買／出售任何物品。'
                '\n只送出一次，需等待伺服器 S20-8；確認關閉嗎？',
                parent=self.npc_shop_window or self):
            return
        if self.npc_shop_window is not None and self.npc_shop_window.winfo_exists():
            self.npc_shop_window.destroy()
            self.npc_shop_window=None
        self.on_npc_next({'type':'npc_close_shop','confirmed':True})

    def show_npc_choices(self):
        dialogue=self.state.get('npc_dialogue',{})
        if str(self.npc_options_button.cget('state'))!='normal':
            return
        options=self.npc_interacts.choices(dialogue.get('scene'),
                        dialogue.get('option_index'), self.npc_talks)
        if options is None:
            return
        # Never allow old dialogs to remain actionable after a state change.
        if self.npc_choice_window is not None:
            try:
                if self.npc_choice_window.winfo_exists():
                    self.npc_choice_window.destroy()
            except tk.TclError:
                pass
        win=tk.Toplevel(self)
        self.npc_choice_window=win
        win.title('NPC 互動選項（一般對話）')
        win.geometry('520x360')
        win.transient(self.winfo_toplevel())
        panel=ttk.Frame(win,padding=12)
        panel.pack(fill='both',expand=True)
        ttk.Label(panel,text=options['title'],wraplength=470).pack(fill='x',pady=(0,8))
        frame=ttk.Frame(panel)
        frame.pack(fill='both',expand=True)
        canvas=tk.Canvas(frame,highlightthickness=0,background='#203f53')
        scroll=ttk.Scrollbar(frame,orient='vertical',command=canvas.yview)
        contents=ttk.Frame(canvas)
        contents.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0,0),window=contents,anchor='nw')
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y')
        canvas.pack(side='left',fill='both',expand=True)
        for choice in options['options']:
            label=choice['text']
            btn=ttk.Button(contents,text=label,command=lambda item=choice:
                           self.choose_npc_reply(options,item),width=48)
            btn.pack(fill='x',pady=3)
        ttk.Label(panel,text='僅手動確認後送出一次；任務效果由伺服器決定。',
                  wraplength=470).pack(fill='x',pady=(8,0))

    def choose_npc_reply(self, options, item):
        dialogue=self.state.get('npc_dialogue',{})
        if (not dialogue.get('active') or dialogue.get('phase')!='choice_unavailable'
                or dialogue.get('scene')!=options['scene']
                or dialogue.get('option_index')!=options['index']
                or self.state.get('battle',{}).get('active')):
            return
        fresh=self.npc_interacts.choices(options['scene'],options['index'],self.npc_talks)
        if fresh!=options or item not in options['options']:
            return
        if not messagebox.askyesno('確認 NPC 選項',
                f"你選擇：「{item['text']}」\n此操作可能觸發任務、物品或戰鬥效果。"
                "\n只會發送一次，不會自動重試。確定送出嗎？",
                parent=self.npc_choice_window or self):
            return
        if self.npc_choice_window is not None and self.npc_choice_window.winfo_exists():
            self.npc_choice_window.destroy()
            self.npc_choice_window=None
        self.on_npc_next({'type':'npc_choose','confirmed':True,
                          'scene':options['scene'],'interact_index':options['index'],
                          'choice':item['choice'],'text_id':item['text_id']})

    def close_npc_option(self):
        if str(self.npc_close_button.cget('state'))!='normal':
            return
        if not messagebox.askyesno('確認關閉 NPC 選項',
                '使用官方 C20-9 40 關閉這個選項清單，不選擇任何選項。'
                '\n需等待伺服器 S20-8；逾時不會重送。確定嗎？',parent=self):
            return
        self.on_npc_next({'type':'npc_close_choice','confirmed':True})

    def view_npc_text(self):
        dialogue=self.state.get('npc_dialogue',{})
        if dialogue.get('active') and dialogue.get('phase')=='talk':
            text=dialogue_text(self.npc_talks,dialogue.get('text_id'))
            if text is not None:
                messagebox.showinfo('NPC 對話（官方文字 ID '+str(dialogue['text_id'])+'）',
                                    text or '（空白對話）',parent=self)

    def view_npc_history(self):
        """Read-only, bounded record of this manually started dialogue."""
        history=(self.state.get('npc_dialogue',{}).get('history') or [])[-50:]
        if not history:
            return
        if self.npc_history_window is not None:
            try:
                if self.npc_history_window.winfo_exists():
                    self.npc_history_window.destroy()
            except tk.TclError:
                pass
        win=tk.Toplevel(self)
        self.npc_history_window=win
        win.title('NPC 本輪對話紀錄')
        win.geometry('560x360')
        panel=ttk.Frame(win,padding=10)
        panel.pack(fill='both',expand=True)
        scroll=ttk.Scrollbar(panel,orient='vertical')
        scroll.pack(side='right',fill='y')
        content=tk.Text(panel,wrap='word',yscrollcommand=scroll.set,
                        background='#203f53',foreground='#f4e4b5',
                        borderwidth=0,highlightthickness=0,
                        font=('Microsoft JhengHei UI',11))
        content.pack(side='left',fill='both',expand=True)
        scroll.configure(command=content.yview)
        for number,text_id in enumerate(history,1):
            text=dialogue_text(self.npc_talks,text_id)
            content.insert('end',f'{number:02d}. 對話 ID {text_id}\n'
                + (text if text is not None else '（未取得對應原文）')
                + '\n\n')
        content.configure(state='disabled')
        win.transient(self.winfo_toplevel())

    def show_dialogue_status(self):
        dialogue=self.state.get('npc_dialogue',{})
        if dialogue.get('active'):
            phase=dialogue.get('phase')
            if phase=='talk':
                text_id=dialogue.get('text_id')
                content=dialogue_text(self.npc_talks,text_id)
                if content is not None:
                    excerpt=content.replace('\r','').replace('\n',' ')[:85]
                    self.npc_message.set(f'對話 ID {text_id}：{excerpt}'
                        + ('…（可查看全文）' if len(content)>85 else ''))
                else:
                    self.npc_message.set(
                        f"對話文字 ID {text_id}；尚無已驗證的文字表，請手動接續。")
            elif phase=='continue':
                self.npc_message.set('伺服器允許繼續，請按下一段對話。')
            elif phase=='choice_unavailable' and (
                    (shop_catalog(dialogue.get('scene'),dialogue.get('option_index'),
                     index=self.npc_interacts) is not None)):
                self.npc_message.set('NPC 商店已開啟：可查看官方商品基礎價與不可販售標記；'
                                     '折扣與金幣同步未確認，不會購買或販售。')
            elif phase=='closing_shop':
                self.npc_message.set('已要求關閉 NPC 商店，等待伺服器確認；不會重送。')
            elif phase=='choice_unavailable':
                self.npc_message.set(
                    f"選項索引 {dialogue.get('option_index')} 尚無可信資料；"
                    "不會自行選擇；可手動按「關閉選項」，或重新登入同步。")
            elif phase=='awaiting_choice':
                self.npc_message.set('已送出一般 NPC 選項；等待伺服器回覆，不會重送。')
            elif phase=='closing':
                self.npc_message.set('已要求關閉選項，等待伺服器 S20-8；不自動重送。')
            elif phase=='effect_unavailable':
                self.npc_message.set('收到未支援的事件效果；停止自動接續，必要時重新登入。')
            else:
                self.npc_message.set('等待 NPC 伺服器回覆中；不自動重送。')
        elif dialogue.get('phase')=='ended':
            self.npc_message.set('NPC 事件已由伺服器 S20-8 確認結束。')
        elif dialogue.get('phase')=='rejected':
            self.npc_message.set('NPC 事件被伺服器拒絕：'+dialogue.get('reason',''))

    def choose_monster(self,event=None):
        selected=self.monster_list.curselection()
        if not selected or selected[0]>=len(self.monster_rows):return
        p=self.monster_rows[selected[0]]
        self.selected_portal=None;self.update_portal_button()
        self.portal_status.set(p['name']+'｜資料表的分布參考點，並非即時怪物位置。')
        if p['x'] is not None:self.on_pick(self.selected_id,p['x'],p['y'])
        self.draw()

    def select_portal(self,p):
        self.selected_npc=None
        self.npc_list.selection_clear(0,'end')
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
