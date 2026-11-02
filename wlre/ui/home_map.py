"""Main-page minimap. Single click selects; double click invokes guarded movement."""

from wlre.services.world.catalog_source_policy import is_official_revision
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
from wlre.services.world.portals import (Portals, nearest_marker,
                                         portal_map_pixel, portal_source_diagnostic, marked_portals)
from wlre.services.world.portal_policy import allowed_rows, destination_problem
from wlre.services.world.portal_dedup_1275 import collapse_portal_destinations
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
        # Reserve the NPC list row. Actions must not compete with the list's
        # remaining pack space in the compact dashboard.
        self.npc_tab.rowconfigure(0,weight=1,minsize=48)
        self.npc_tab.columnconfigure(0,weight=1)
        self.npc_message=tk.StringVar(value='選取 NPC 查看資料')
        ttk.Label(self.npc_tab,textvariable=self.npc_message,style='Muted.TLabel',
                  width=1,anchor='w').grid(row=2,column=0,columnspan=2,sticky='ew',pady=(2,0))
        npc_bar=ttk.Scrollbar(self.npc_tab,orient='vertical')
        npc_bar.grid(row=0,column=1,sticky='ns')
        npc_controls=ttk.Frame(self.npc_tab)
        npc_controls.grid(row=1,column=0,columnspan=2,sticky='ew',pady=(3,0))
        npc_controls.columnconfigure((0,1),weight=1)
        self.npc_talk_button=ttk.Button(npc_controls,text='互動',width=4,padding=(2,2),
                                       command=self.interact_npc,state='disabled')
        self.npc_talk_button.grid(row=0,column=0,sticky='ew',padx=(0,2))
        self.npc_next_button=ttk.Button(npc_controls,text='接續',width=4,padding=(2,2),
                                       command=self.next_npc,state='disabled')
        self.npc_next_button.grid(row=0,column=1,sticky='ew')
        # Keep the original action widgets/state guards; the menu invokes
        # those same commands instead of creating a second interaction path.
        self.npc_shop_button=ttk.Button(npc_controls,command=self.show_npc_shop,state='disabled')
        self.npc_options_button=ttk.Button(npc_controls,command=self.show_npc_choices,state='disabled')
        self.npc_history_button=ttk.Button(npc_controls,command=self.view_npc_history,state='disabled')
        self.npc_text_button=ttk.Button(npc_controls,command=self.view_npc_text,state='disabled')
        self.npc_close_button=ttk.Button(npc_controls,command=self.close_npc_option,state='disabled')
        self.npc_action_menu=tk.Menu(npc_controls,tearoff=False,
            background='#203f53',foreground='#f4e4b5',activebackground='#e5d9ad',
            activeforeground='#243b4d',postcommand=self.sync_npc_action_menu)
        self._npc_menu_buttons=[
            ('查看／選擇選項',self.npc_options_button),
            ('查看 NPC 商店',self.npc_shop_button),
            ('查看對話全文',self.npc_text_button),
            ('本輪對話紀錄',self.npc_history_button),
            ('關閉選項',self.npc_close_button)]
        for label,button in self._npc_menu_buttons:
            self.npc_action_menu.add_command(label=label,command=button.invoke,state='disabled')
        self.npc_action_menu.add_separator()
        self.npc_action_menu.add_command(label='NPC 資訊',command=self.show_npc_details)
        self.npc_more_button=ttk.Menubutton(npc_controls,text='更多操作',menu=self.npc_action_menu)
        self.npc_more_button.grid(row=1,column=0,columnspan=2,sticky='ew',pady=(2,0))
        self.npc_list=tk.Listbox(self.npc_tab,exportselection=False,height=3,background='#203f53',
                                 foreground='#f4e4b5',selectbackground='#e5d9ad',
                                 selectforeground='#243b4d',borderwidth=0,
                                 highlightthickness=0,font=('Microsoft JhengHei UI',-14))
        self.npc_list.configure(yscrollcommand=npc_bar.set)
        npc_bar.configure(command=self.npc_list.yview)
        self.npc_list.grid(row=0,column=0,sticky='nsew')
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

    def refresh_runtime_sources(self):
        # The UI may be constructed before the 1275 runtime finishes being
        # installed. Do not pin an empty pre-login portal snapshot forever.
        # The current client must never keep a previously loaded 1262
        # portal list after the 1275 runtime has been installed. Replace the
        # whole cached catalogue rather than mixing old/new rows.
        from wlre.services.world.dynamic_bundle_runtime import current_runtime, dynamic_attempted
        runtime = current_runtime()
        key = runtime.catalog_identity.key if runtime is not None else None
        changed = key != getattr(self, '_runtime_catalog_key', None)
        if changed:
            self.selected_npc=self.selected_portal=None
            for name in ('npc_shop_window','npc_choice_window','npc_history_window'):
                window=getattr(self,name,None)
                if window is not None:
                    try:
                        if window.winfo_exists():
                            window.destroy()
                    except tk.TclError:
                        pass
                    setattr(self,name,None)
            # Rebind all UI snapshots together; old NPC/talk/item IDs cannot
            # survive a timestamp-only republish with the same numeric version.
            self.route = self.image = self.photo = self.mesh = self.projection = None
            self.map_error = '官方資源版本已更新，正在重新載入目前場景'
            self.maps = SmallMaps()
            self.portals = Portals()
            self.npc_index = runtime.npc_index if runtime is not None else None
            self.npc_interacts = runtime.interact_index if runtime is not None else NPCInteractIndex.__new__(NPCInteractIndex)
            if runtime is None:
                self.npc_interacts.scenes = {}
            self.npc_talks = dict(runtime.talks) if runtime is not None else {}
            self.npc_index_error = self.npc_interact_error = self.npc_talk_error = runtime is None
            self._runtime_catalog_key = key
        if dynamic_attempted() and runtime is None:
            self.npc_index = None
            self.npc_interacts.scenes = {}
            self.npc_talks = {}
        return changed

    def refresh_portals(self):
        HomeMap.refresh_runtime_sources(self)
        previous_revision = self.portals.data.get('source_revision')
        if (not is_official_revision(previous_revision)
                or not self.portals.data.get('source_ready')):
            # Early 1262 portals.json files have no source_revision field.
            # Retire only their *portal rows*. NPC/monster reference records
            # were bundled in the same index and must stay separately
            # available for the sidebar until replaced by verified sources.
            old_entities = self.portals.data.get('entities', {})
            if isinstance(old_entities, dict) and old_entities:
                self._legacy_map_entities = old_entities
            self.portals = Portals()
        revision_label = str(self.portals.data.get('source_revision') or '官方新版')
        recovery=self.image is None
        candidates=allowed_rows(self.portals,self.selected_id,self.maps,recovery=recovery)
        marked=marked_portals(candidates, getattr(self, 'projection', None),
                              allow_unprojected=recovery)
        self.portal_rows=collapse_portal_destinations(marked)
        hidden_count=len(candidates)-len(marked)
        merged_count=len(marked)-len(self.portal_rows)
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
            if is_official_revision(p.get('source_revision')):
                prefix = '◇ '  # verified door location, unverified destination
            else:
                prefix='↩ 返回：' if recovery else ('◎ ' if p.get('direct_eligible') else '○ ')
            self.portal_list.insert('end',prefix+p['name'])
            self.list_rows.append(p)
        self.monster_list.delete(0,'end')
        self.monster_rows=[]
        entities=self.portals.data.get('entities',{}).get(str(self.selected_id),[])
        if not entities:
            entities = getattr(self, '_legacy_map_entities', {}).get(
                str(self.selected_id), [])
        self.npc_rows=scene_npcs(self.selected_id,entities,self.npc_index)
        for npc in self.npc_rows:
            marker='◆' if npc['verified'] else '◇'
            self.npc_list.insert('end',f"{marker} {npc['name']}")
        for e in entities:
            if e['kind']!=0:
                self.monster_list.insert('end',f"Lv.{e['level'] if e['level'] is not None else '?'} {e['name']}")
                self.monster_rows.append(e)
        if not self.list_rows:
            if is_official_revision(self.portals.data.get('source_revision')):
                empty = (f'（{revision_label} 門事件資料尚未就緒）'
                         if not self.portals.data.get('source_ready')
                         else '（無已標記傳點）')
            else:
                empty = ('（沒有已確認的返回出口）' if recovery
                         else '（來源未列傳點）')
            self.portal_list.insert('end', empty)
        if not self.npc_rows:self.npc_list.insert('end','（本場景尚無 NPC 資料）')
        if not self.monster_rows:self.monster_list.insert('end','（來源未列怪物）')
        ready=sum(bool(p.get('direct_eligible')) for p in self.portal_rows)
        if hasattr(self, 'portal_info'):
            self.portal_info.set('')
            if is_official_revision(self.portals.data.get('source_revision')):
                source = self.portals.data.get('portal_metadata_status')
                if source not in ('stage_map_ready', 'destination_links_loaded') and (
                        not isinstance(source, str)
                        or not source.startswith('destination_links_')):
                    self.portal_info.set(portal_source_diagnostic(source))
                else:
                    notes=[]
                    if merged_count:notes.append(f'{merged_count} 個同目的入口已合併顯示')
                    if hidden_count:notes.append(f'{hidden_count} 個未確認／未標示點已隱藏')
                    self.portal_info.set('；'.join(notes))
        if is_official_revision(self.portals.data.get('source_revision')):
            count = len(self.portal_rows)
            if self.portals.data.get('source_ready'):
                # Use the same validated scene label as the map header,
                # including safe fallback for out-of-range scene IDs.
                scene = MinimapNavigationMixin.scene_display_name(self)
                named = sum(bool(p.get('official_name')) for p in self.portal_rows)
                name_status = self.portals.data.get(
                    'portal_metadata_status', 'missing_stage_map')
                if name_status not in ('stage_map_ready', 'destination_links_loaded') and (
                        not isinstance(name_status, str)
                        or not name_status.startswith('destination_links_')):
                    hint = portal_source_diagnostic(name_status) + '。'
                else:
                    hint = (f'{named} 個傳點有正式文字名稱；'
                            f'{count-named} 個尚缺有效 NameID／文字對應。'
                            + ('｜' + portal_source_diagnostic(name_status)
                               if isinstance(name_status, str)
                               and name_status.startswith('destination_links_')
                               else ''))
                text = (f'{revision_label} 場景 {scene}：{count} 個傳點，'
                        f'{ready} 個可手動確認試傳。{hint}'
                        '實際換圖以伺服器回覆為準。')
            else:
                text = (f'{revision_label} 官方門事件索引尚未完成校驗／安裝；'
                        '下次切換地圖會重新讀取，不使用 1262 舊傳點。')
        elif recovery:
            text=(f'此圖沒有小地圖；左側保留 {ready} 個已核對的出口，可由清單手動觸發。' if ready
                  else '此圖沒有小地圖，來源未列可確認的返回出口；請使用官方客戶端離開。')
        else:
            text=f'可見 {len(self.portal_rows)} 個傳點；{ready} 個可直接嘗試；已隱藏尚未核對的入口。'
        if is_official_revision(self.portals.data.get('source_revision')):
            duplicate = self.portals.data.get('portal_duplicate_report', {})
            if isinstance(duplicate, dict):
                removed = (duplicate.get('duplicate_event_id_removed', 0)
                           + duplicate.get('duplicate_hidden_removed', 0))
                if removed:
                    text += (f'｜清單已去除 {removed} 筆重複顯示；'
                             '同 ID 衝突的傳點已停用傳送。')
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

