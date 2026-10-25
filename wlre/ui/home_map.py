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
from wlre.features.minimap.map_view import MinimapCanvasMixin
from wlre.features.minimap.buttons import MinimapPickMixin
from wlre.features.minimap.navigation_ui import MinimapNavigationMixin
from wlre.features.npc.panel import NPCInteractionMixin
from wlre.features.portals.panel import PortalInteractionMixin


class HomeMap(MinimapCanvasMixin, MinimapPickMixin,
              MinimapNavigationMixin, NPCInteractionMixin,
              PortalInteractionMixin, ttk.Frame):
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
        bar.pack(side='right',fill='y')
        # Compact dashboard hides the generic status strip. Keep a short
        # actionable resource diagnostic visible beside the portal list.
        self.portal_info=tk.StringVar(value='')
        ttk.Label(self.portal_tab, textvariable=self.portal_info,
                  style='Muted.TLabel',
                  wraplength=108 if compact else 160).pack(
                      side='bottom',fill='x',padx=1,pady=(3,2))
        self.portal_list.pack(fill='both',expand=True)
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

    def refresh_portals(self):
        # The UI may be constructed before the 1275 runtime finishes being
        # installed. Do not pin an empty pre-login portal snapshot forever.
        if (self.portals.data.get('source_revision') == 1275
                and not self.portals.data.get('source_ready')):
            self.portals = Portals()
        recovery=self.image is None
        self.portal_rows=allowed_rows(self.portals,self.selected_id,self.maps,recovery=recovery)
        # A scene title is never derived from portal selection or door IDs.
        # Update it even before 1275 names become available, so old labels
        # cannot survive a scene change or an asynchronous source reload.
        if hasattr(self, 'map_title'):
            MinimapNavigationMixin.update_scene_title(self)
        self.selected_portal=None
        self.selected_npc=None
        self.portal_list.delete(0,'end')
        self.npc_list.delete(0,'end')
        self.npc_message.set('NPC 索引檔無效：已停用索引資料。' if self.npc_index_error
                             else '選取 NPC 查看名稱、座標與事件索引核對狀態。')
        self.list_rows=[]
        for p in self.portal_rows:
            if p.get('source_revision') == 1275:
                prefix = '◇ '  # verified door location, unverified destination
            else:
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
        if not self.list_rows:
            if self.portals.data.get('source_revision') == 1275:
                empty = ('（1275 門事件資料尚未就緒）'
                         if not self.portals.data.get('source_ready')
                         else '（此場景尚無經核對的傳點）')
            else:
                empty = ('（沒有已確認的返回出口）' if recovery
                         else '（來源未列傳點）')
            self.portal_list.insert('end', empty)
        if not self.npc_rows:self.npc_list.insert('end','（本場景尚無 NPC 資料）')
        if not self.monster_rows:self.monster_list.insert('end','（來源未列怪物）')
        ready=sum(bool(p.get('direct_eligible')) for p in self.portal_rows)
        if hasattr(self, 'portal_info'):
            self.portal_info.set('')
            if self.portals.data.get('source_revision') == 1275:
                source = self.portals.data.get('portal_metadata_status')
                named = sum(bool(p.get('official_name')) for p in self.portal_rows)
                if source in ('missing_stage_map', 'core_runtime_unavailable'):
                    self.portal_info.set('尚缺 1275 官方傳點名稱資料')
                elif source == 'stage_map_invalid':
                    self.portal_info.set('1275 傳點名稱表格式無法解析')
                elif named < len(self.portal_rows):
                    self.portal_info.set(
                        f'{len(self.portal_rows)-named} 個傳點未取得官方名稱')
        if self.portals.data.get('source_revision') == 1275:
            count = len(self.portal_rows)
            if self.portals.data.get('source_ready'):
                # Use the same validated scene label as the map header,
                # including safe fallback for out-of-range scene IDs.
                scene = MinimapNavigationMixin.scene_display_name(self)
                named = sum(bool(p.get('official_name')) for p in self.portal_rows)
                name_status = self.portals.data.get(
                    'portal_metadata_status', 'missing_stage_map')
                if name_status == 'missing_stage_map':
                    hint = ('1275 StageMapData_C 傳點名稱表尚未載入；'
                            '需完成官方附加 Bundle 下載或安裝含此表的正式資料。')
                elif name_status == 'stage_map_invalid':
                    hint = '1275 StageMapData_C 傳點名稱表解析失敗；未採用舊版猜測名稱。'
                else:
                    hint = (f'{named} 個傳點有正式文字名稱；'
                            f'{count-named} 個尚缺有效 NameID／文字對應。')
                text = (f'1275 場景 {scene}：{count} 個傳點，'
                        f'{ready} 個可手動確認試傳。{hint}'
                        '實際換圖以伺服器回覆為準。')
            else:
                text = ('1275 官方門事件索引尚未完成校驗／安裝；'
                        '下次切換地圖會重新讀取，不使用 1262 舊傳點。')
        elif recovery:
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

