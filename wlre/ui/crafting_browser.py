"""Icon crafting catalog with compact embedded and full-window layouts."""
import math
import tkinter as tk
from wlre.ui.window_layout import configure_dialog
from tkinter import ttk
from wlre.ui.theme import group
from wlre.services.items.crafting import RECIPES, recipe_plan, effective_time, confirmed_unlocked
from wlre.services.items.catalog import item_display_name as item_name
from wlre.services.items.crafting_browser_model import Favorites, owned_counts, material_rows, availability, tool_status, room_known
from wlre.services.world.feature_resource_index import feature_note
from wlre.core.efficiency import duration
from wlre.ui.crafting.item_icons import ItemIcons, ICON_MAP
from wlre.ui.crafting.queue_view import CraftingQueueMixin
from wlre.ui.crafting.catalog_grid import build_catalog_grid, render_catalog_grid
from wlre.ui.crafting.recipe_detail import build_recipe_detail, render_recipe_detail


class CraftingBrowser(CraftingQueueMixin):
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
        self.toolbar=header
        ttk.Button(header,text='自訂清單',command=panel.open_plan,padding=(5,3)).pack(side='left',padx=(12,3))
        ttk.Button(header,text='進入自家帳篷',command=lambda:panel.app.send({'type':'tent','action':'enter'}),padding=(5,3)).pack(side='left',padx=3)
        self.queue_label=tk.StringVar();ttk.Button(header,textvariable=self.queue_label,command=self.show_queue,padding=(5,3)).pack(side='left',padx=3)
        self.source_label=tk.StringVar(value=feature_note('crafting'))
        ttk.Label(header,textvariable=self.source_label,style='Muted.TLabel').pack(side='right',padx=4)
        searchbar=ttk.Frame(box);searchbar.pack(fill='x',pady=(0,4))
        self.only_tools=tk.BooleanVar(value=True);ttk.Checkbutton(searchbar,text='只列小屋已有設備',variable=self.only_tools,command=lambda:self.refresh(force=True)).pack(side='left')
        ttk.Label(searchbar,text='搜尋').pack(side='left',padx=(8,4))
        self.search=tk.StringVar();search=ttk.Entry(searchbar,textvariable=self.search,width=16);search.pack(side='left',fill='x',expand=True);search.bind('<KeyRelease>',self.defer_search)
        body=ttk.Frame(box);body.pack(fill='both',expand=True)
        catalog=body
        catalog.columnconfigure(0,minsize=128 if embedded else 164,weight=0)
        catalog.columnconfigure(1,weight=1)
        catalog.columnconfigure(2,minsize=0 if embedded else 410,weight=0)
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
        build_catalog_grid(self,middle,w,embedded)
        if embedded:
            for widget in (header,searchbar,body):widget.pack_forget()
            box.columnconfigure(0,weight=1);box.columnconfigure(1,minsize=248,weight=0)
            box.rowconfigure(2,weight=1)
            header.grid(row=0,column=0,sticky='ew',pady=(0,4))
            searchbar.grid(row=1,column=0,sticky='ew',pady=(0,4))
            body.grid(row=2,column=0,sticky='nsew')
        right=build_recipe_detail(self,box,body,embedded)
        bottom=ttk.Frame(box)
        if embedded:bottom.grid(row=3,column=0,sticky='ew',pady=(6,0))
        else:bottom.pack(side='bottom',fill='x',pady=(6,0),before=body)
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
        self.source_label.set(feature_note('crafting'))
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
        return render_catalog_grid(self,force,recipes=RECIPES,
                                   confirmed_unlocked=confirmed_unlocked,
                                   room_known=room_known,tool_status=tool_status,
                                   item_name=item_name,availability=availability)

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
        return render_recipe_detail(self,force,recipes=RECIPES,
                                    owned_counts=owned_counts,material_rows=material_rows,
                                    availability=availability,item_name=item_name,
                                    tool_status=tool_status,effective_time=effective_time,
                                    duration=duration,icon_map=ICON_MAP,recipe_plan=recipe_plan)

    def add(self):
        if not self.selected:return
        self.panel.add(self.selected,self.count.get())

    def tick(self):
        if not self.closed:
            if self.queue_window and self.queue_window.winfo_exists():self.update_queue()
            self.tick_job=self.window.after(1000,self.tick)
